"""
What every "build it and run it" test of a generated backend shares (not a
test module itself — see test_gin_e2e.py and its siblings).

A backend written in a language other than Python can't be imported and
driven in-process the way test_deterministic_migrations_e2e.py drives the
FastAPI one, so these tests compile the generated project with its real
toolchain, start the real server on a real SQLite file and talk to it over
HTTP. The scenario and the expected answers are the same for every backend
— same schema, same requests, same sentences — which is the point: the
generated REST contract doesn't depend on the stack behind it.

The scenario (run_lifecycle): the initial schema; an additive change
regenerated against the SAME database; a confirmed column drop; `revert`
of the newest migration, then of the whole history; and everything
applied again from an empty database.

What differs between backends is described by a Backend: how it is built
and started, where its migrations live and how they are applied and undone
(the backends that run the shared SQL files do it themselves at startup;
Rails has `db:migrate` and `db:rollback`, Laravel `migrate` and
`migrate:rollback`).

Toolchains: a test asks for its toolchain with toolchain(). Without it the
test is skipped — unless VENGAI_REQUIRE_TOOLCHAINS lists it, which the
backend CI job does, so a missing toolchain fails there instead of passing
as a skip.
"""

import copy
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

import pytest
from test_deterministic_migrations_e2e import SHOP, FakeProject, evolved

from app.ai import codegen_deterministic as dc
from app.ai import db_schema, migrations_gen

EXE = ".exe" if os.name == "nt" else ""
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def stack(backend: str) -> dict:
    return {
        "frontend_framework": "react",
        "backend_framework": backend,
        "api_style": "rest",
        "codegen_target": f"react_{backend}",
        "source": "selected_stack",
    }


def toolchain(name: str, program: str | None = None) -> str:
    """The program's path — or the test is skipped (failed, where
    VENGAI_REQUIRE_TOOLCHAINS says this toolchain has to be there)."""
    path = shutil.which(program or name)
    if path is None:
        if name in os.environ.get("VENGAI_REQUIRE_TOOLCHAINS", "").split(","):
            pytest.fail(
                f"VENGAI_REQUIRE_TOOLCHAINS lists {name}, but `{program or name}` isn't on PATH"
            )
        pytest.skip(f"needs the {name} toolchain (the backend CI job installs it)")
    return path


def run(args: list[str], cwd: str, timeout: int = 900, env: dict | None = None) -> str:
    proc = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
    )
    assert proc.returncode == 0, (
        f"`{' '.join(args)}` failed:\n{proc.stdout[-8000:]}\n{proc.stderr[-8000:]}"
    )
    return proc.stdout


def write_backend(data: dict, root, sources: tuple[str, ...]) -> str:
    """Replaces root/backend's source files (those with a suffix in
    `sources`) with this generation's, the way a regenerated project
    replaces the old one; lock files and build output stay."""
    backend = root / "backend"
    wanted = {
        f["path"]: f["content"]
        for f in data["codegen"]["files"]
        if f["path"].startswith("backend/")
    }
    if backend.exists():
        for path in backend.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_file() and path.suffix in sources and relative not in wanted:
                # Build output (bin/, obj/, vendor/) holds sources of its own.
                if not any(
                    part in ("bin", "obj", "vendor", "node_modules")
                    for part in path.relative_to(backend).parts
                ):
                    path.unlink()
    for path, content in wanted.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    return str(backend)


class Server:
    """The generated app, serving on a free port: PORT in its environment,
    and "{port}" in its command replaced by it (`php artisan serve` takes
    the port as an option)."""

    def __init__(self, command: list[str], env: dict, log_path: str, cwd: str):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.log_path = log_path
        self.log = open(log_path, "ab")
        self.proc = subprocess.Popen(
            [arg.replace("{port}", str(self.port)) for arg in command],
            cwd=cwd,
            env={**env, "PORT": str(self.port)},
            stdout=self.log,
            stderr=subprocess.STDOUT,
            # Its own process group, so a server that runs in a child process
            # (`php artisan serve` starts `php -S`) is stopped with it.
            start_new_session=os.name != "nt",
        )

    def output(self) -> str:
        self.log.flush()
        with open(self.log_path, encoding="utf-8", errors="replace") as f:
            return f.read()[-8000:]

    def __enter__(self):
        deadline = time.time() + 90
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"the app exited at startup:\n{self.output()}")
            try:
                if self.call("GET", "/")[0] == 200:
                    return self
            except OSError:
                pass
            time.sleep(0.2)
        raise AssertionError(f"the app never answered:\n{self.output()}")

    def __exit__(self, kind, error, traceback):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=20)
        if os.name != "nt":
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # the whole group is already gone
        if error is not None:
            # What the server said, next to the assertion that failed.
            print(f"--- server log ---\n{self.output()}")
        self.log.close()

    def call(self, method: str, path: str, body=None, raw: bytes | None = None):
        data = (
            raw
            if raw is not None
            else (None if body is None else json.dumps(body).encode("utf-8"))
        )
        headers = {"Content-Type": "application/json", "Origin": "tauri://localhost"}
        if method == "OPTIONS":
            # What a browser's preflight for a PUT sends.
            headers["Access-Control-Request-Method"] = "PUT"
            headers["Access-Control-Request-Headers"] = "content-type"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8")
                return (
                    response.status,
                    json.loads(text) if text else None,
                    response.headers,
                )
        except urllib.error.HTTPError as err:
            text = err.read().decode("utf-8")
            try:
                parsed = json.loads(text) if text else None
            except ValueError:
                parsed = text
            return err.code, parsed, err.headers

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body):
        return self.call("POST", path, body)

    def put(self, path, body):
        return self.call("PUT", path, body)

    def delete(self, path):
        return self.call("DELETE", path)


def app_env(database: str, **extra: str) -> dict:
    return {
        **os.environ,
        "DATABASE_PATH": database,
        "GIN_MODE": "release",
        "ASPNETCORE_ENVIRONMENT": "Production",
        "DOTNET_NOLOGO": "1",
        **extra,
    }


def cache_dir(name: str) -> str:
    """A build cache kept between runs (a Rust target directory, installed
    packages): VENGAI_E2E_CACHE/<name>, by default under ~/.cache rather
    than the temp folder, which Windows empties when the disk runs low."""
    root = os.environ.get("VENGAI_E2E_CACHE") or os.path.join(
        os.path.expanduser("~"), ".cache", "vengaicode-e2e"
    )
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    return path


def query(database: str, sql: str) -> list[tuple]:
    db = sqlite3.connect(database)
    try:
        return db.execute(sql).fetchall()
    finally:
        db.close()


def versions(database: str) -> list[tuple[int, str]]:
    """What the runners of the shared SQL files record: (number, name)."""
    return query(database, "select version, name from _migrations order by version")


def sql_family_applied(database: str) -> list[int]:
    return [version for version, _ in versions(database)]


@dataclass
class Backend:
    """How one generated backend is built, started and migrated."""

    key: str  # the stack's backend_framework
    error_key: str  # where its error responses carry the sentence
    tool: str  # its migration tool id
    sources: tuple[str, ...]  # suffixes of the files a regeneration replaces
    build: Callable[[str], None]  # backend dir -> compiled, ready to run
    command: Callable[[str], list[str]]  # backend dir -> the server's argv
    first_build_checks: Callable[[str], None] = lambda folder: None
    # Run before every start, with the environment the server gets — for a
    # backend whose migrations are a command rather than part of startup.
    prepare: Callable[[str, dict], None] = lambda folder, env: None
    # The argv that undoes the newest migration (default: the server's + "revert").
    revert: Callable[[str], list[str]] | None = None
    # The migrations a database has had, as their numbers: 1, 2, 3, ...
    applied: Callable[[str], list[int]] = sql_family_applied
    # The tables the migration tool keeps for itself.
    bookkeeping: frozenset = frozenset({"_migrations"})
    # Where a revision's file is: (path prefix, suffix).
    migrations: tuple[str, str] = ("backend/migrations/", ".sql")
    # Whether the server (and revert) run from the project's own folder.
    runs_in_project: bool = False
    # Environment beyond DATABASE_PATH, for a database path (Rust reads a
    # DATABASE_URL instead).
    env: Callable[[str], dict] = lambda database: {}

    def cwd(self, folder: str, elsewhere: str) -> str:
        return folder if self.runs_in_project else elsewhere

    def environment(self, database: str) -> dict:
        """What the server, its migrations and revert run with."""
        return app_env(database, **self.env(database))

    def migration_files(self, data: dict) -> dict[str, str]:
        prefix, suffix = self.migrations
        return {
            f["path"]: f["content"]
            for f in data["codegen"]["files"]
            if f["path"].startswith(prefix) and f["path"].endswith(suffix)
        }


def initial_checks(app: Server, database: str, backend: Backend) -> None:
    key = backend.error_key

    def problem(response):
        """(status, the error sentence)."""
        return response[0], (response[1] or {}).get(key)

    db = sqlite3.connect(database)
    tables = {
        r[0] for r in db.execute("select name from sqlite_master where type='table'")
    }
    assert {
        "customers",
        "orders",
        "order_items",
        "products",
        "coupons",
        "employees",
        "notes",
    } <= tables
    db.close()
    assert backend.applied(database) == [1]

    status, root, headers = app.get("/")
    assert root == {"message": "Shop's (Demo API is running"}
    assert headers["Access-Control-Allow-Origin"] == "*"
    # A browser's preflight is answered without reaching a route.
    status, _, headers = app.call("OPTIONS", "/api/customers")
    assert status in (200, 204) and "PUT" in headers["Access-Control-Allow-Methods"]

    # An empty table is [], never null.
    assert app.get("/api/products")[:2] == (200, [])

    status, rows, _ = app.get("/api/customers")
    assert [r["email"] for r in rows] == ["a@x.io", "b@x.io"], "seed rows"
    assert rows[0]["is_active"] is True and rows[1]["is_active"] is False
    assert rows[0]["profile"] == {"tier": "basic"}, "json default, answered as JSON"
    assert RFC3339_UTC.match(rows[0]["created_at"]), rows[0]["created_at"]
    coupon_id = app.get("/api/coupons")[1][0]["id"]

    status, cust, _ = app.post("/api/customers", {"email": "c@x.io"})
    assert status == 201 and cust["is_active"] is True, "create applies defaults"
    assert cust["name"] is None and cust["id"] == 3
    assert cust["profile"] == {"tier": "basic"}
    assert RFC3339_UTC.match(cust["created_at"]), cust["created_at"]
    assert app.get("/api/customers/3")[1] == cust, "answered as stored"
    status, text = problem(app.post("/api/customers", {"email": "c@x.io"}))
    assert status == 409 and "already has this email" in text, text
    status, text = problem(app.post("/api/customers", {"email": "no-at-sign"}))
    assert status == 422 and "email has at" in text, text
    assert problem(app.post("/api/customers", {"name": "x"})) == (
        422,
        "email: is required",
    )
    # Every problem at once: the wrong kind, then what's missing.
    status, text = problem(app.post("/api/customers", {"is_active": "yes", "name": 5}))
    assert (status, text.split("\n")) == (
        422,
        [
            "name: expected text",
            "is_active: expected true or false",
            "email: is required",
        ],
    )
    not_an_object = (400, "Send the record as a JSON object.")
    assert problem(app.post("/api/customers", [1])) == not_an_object
    assert problem(app.call("POST", "/api/customers", raw=b"{nope")) == not_an_object
    assert problem(app.call("POST", "/api/customers", raw=b"")) == not_an_object
    assert problem(app.get("/api/customers/abc")) == (400, "id: not a valid id")
    assert problem(app.get("/api/customers/999")) == (404, "customers 999 not found.")

    status, body, _ = app.put(
        f"/api/customers/{cust['id']}", {"profile": {"a": [1, 2]}, "name": "Cy"}
    )
    assert status == 200 and body["profile"] == {"a": [1, 2]} and body["name"] == "Cy"
    assert body["email"] == "c@x.io", "a field the request left out is kept"
    status, body, _ = app.put(f"/api/customers/{cust['id']}", {"profile": None})
    assert status == 200 and body["profile"] is None and body["name"] == "Cy"
    # An explicit null on create is stored as null, not replaced by the default.
    status, body, _ = app.post("/api/customers", {"email": "n@x.io", "profile": None})
    assert status == 201 and body["profile"] is None and body["is_active"] is True
    assert app.delete(f"/api/customers/{body['id']}")[0] == 204

    assert problem(app.post("/api/orders", {"customer_id": "abc"})) == (
        422,
        "customer_id: expected a whole number",
    )
    assert problem(app.post("/api/orders", {"customer_id": 9999})) == (
        422,
        "customer_id: no row in customers has id 9999.",
    )

    status, order, _ = app.post(
        "/api/orders",
        {"customer_id": cust["id"], "coupon_id": coupon_id, "ship_date": "2026-10-01"},
    )
    assert status == 201 and order["status"] == "draft" and order["total"] == 0
    assert RFC3339_UTC.match(order["placed_at"]), "the `now` default"
    assert order["ship_date"] == "2026-10-01"
    orders = f"/api/orders/{order['id']}"
    for bad, why in (
        ({"total": "-1.00"}, "total non negative"),
        ({"status": "bogus"}, "status known"),
    ):
        status, text = problem(
            app.post("/api/orders", {"customer_id": cust["id"], **bad})
        )
        assert status == 422 and why in text, text
    for total, why in (
        ("1.234", "total: only 2 decimal places are stored"),
        ("12345678901.5", "total: number is too large"),
        ("12,5", "total: expected a number like 12.50"),
        (True, "total: expected a number like 12.50"),
    ):
        assert problem(
            app.post("/api/orders", {"customer_id": cust["id"], "total": total})
        ) == (422, why)
    assert problem(app.put(orders, {"status": None})) == (
        422,
        "status: may not be null",
    )
    assert problem(app.put(orders, {"placed_at": "soon"})) == (
        422,
        "placed_at: expected a date and time like 2024-01-31T09:30:00Z",
    )
    status, body, _ = app.put(
        orders,
        {"status": "paid", "total": "12.50", "placed_at": "2024-01-31T09:30:00+02:00"},
    )
    assert status == 200 and body["status"] == "paid" and body["total"] == 12.5
    assert body["placed_at"] == "2024-01-31T07:30:00Z", "stored and answered in UTC"
    assert body["customer_id"] == cust["id"], "partial update"
    assert app.get(orders)[1] == body, "answered as stored"
    assert app.put(orders, {"total": 3})[1]["total"] == 3
    # A JSON number in exponent form is still a number.
    assert app.call("PUT", orders, raw=b'{"total": 1.25e1}')[1]["total"] == 12.5
    assert app.put(orders, {"placed_at": "2024-02-01T10:15"})[1]["placed_at"] == (
        "2024-02-01T10:15:00Z"
    ), "no offset is read as UTC"
    assert app.put("/api/orders/999", {"total": 3})[0] == 404

    status, product, _ = app.post(
        "/api/products", {"sku": "SKU1", "title": "Widget", "price": 9.5}
    )
    assert status == 201 and product["price"] == 9.5
    status, text = problem(app.post("/api/products", {"sku": "SKU1"}))
    assert status == 409 and "already has this sku" in text, text
    assert problem(app.post("/api/products", {"sku": "x" * 256})) == (
        422,
        "sku: at most 255 characters",
    )
    items = {"order_id": order["id"], "product_id": product["id"]}
    status, item, _ = app.post("/api/order_items", {**items, "quantity": 2})
    assert status == 201 and item["quantity"] == 2
    status, text = problem(app.post("/api/order_items", items))
    assert status == 409 and "order_id, product_id" in text, text
    status, text = problem(
        app.post("/api/order_items", {"order_id": order["id"], "quantity": 0})
    )
    assert status == 422 and "qty positive" in text, text

    status, text = problem(app.delete(f"/api/products/{product['id']}"))
    assert status == 409 and "order items" in text, "ON DELETE RESTRICT"
    assert app.delete(f"/api/coupons/{coupon_id}")[:2] == (204, None)
    assert app.get(orders)[1]["coupon_id"] is None, "ON DELETE SET NULL"
    assert app.delete(f"/api/customers/{cust['id']}")[0] == 204
    assert app.get(orders)[0] == 404, "cascade to orders"
    assert app.get(f"/api/order_items/{item['id']}")[0] == 404, "cascade two levels"
    assert app.delete(f"/api/products/{product['id']}")[0] == 204
    assert app.delete(f"/api/products/{product['id']}")[0] == 404

    boss = app.post("/api/employees", {"name": "Boss"})[1]
    worker = app.post("/api/employees", {"name": "W", "manager_id": boss["id"]})[1]
    app.delete(f"/api/employees/{boss['id']}")
    assert app.get(f"/api/employees/{worker['id']}")[1]["manager_id"] is None

    status, note, _ = app.post(
        "/api/notes", {"date": "2026-01-02", "due": "2026-02-03", "copy": "c"}
    )
    assert status == 201 and note["due"] == "2026-02-03" and note["title"] is None
    assert problem(app.post("/api/notes", {"due": "not a date"})) == (
        422,
        "due: expected a date like 2024-01-31",
    )

    # Rows the next migration must carry forward.
    app.post("/api/products", {"sku": "KEEP", "title": "Kept", "stock_count": 4})


def evolved_checks(app: Server, database: str, backend: Backend) -> None:
    key = backend.error_key
    assert backend.applied(database) == [1, 2]
    if backend.applied is sql_family_applied:
        assert versions(database)[1] == (2, "create_reviews_and_more")
    rows = app.get("/api/customers")[1]
    assert next(r for r in rows if r["email"] == "pre@x.io")["name"] == "anon", (
        "NULL backfilled before NOT NULL"
    )
    status, body, _ = app.post("/api/customers", {"email": "d@x.io"})
    assert status == 201 and body["name"] == "anon", "the new default"
    kept = next(p for p in app.get("/api/products")[1] if p["sku"] == "KEEP")
    assert kept["is_featured"] is False and kept["stock_count"] == 4
    status, body, _ = app.post("/api/products", {"sku": "N2", "price": -3})
    assert status == 422 and "price positive" in body[key], body
    status, review, _ = app.post("/api/reviews", {"product_id": kept["id"]})
    assert status == 201 and review["rating"] == 5, "new table with a foreign key"
    status, body, _ = app.post("/api/reviews", {"product_id": kept["id"], "rating": 9})
    assert status == 422 and "rating range" in body[key], body
    db = sqlite3.connect(database)
    assert "ix_products_title" in [
        r[1] for r in db.execute("pragma index_list('products')")
    ]
    db.close()


def destroyed_checks(app: Server, database: str, backend: Backend) -> None:
    assert backend.applied(database) == [1, 2, 3]
    db = sqlite3.connect(database)
    columns = [r[1] for r in db.execute("pragma table_info('products')")]
    assert "stock_count" not in columns and "sku" in columns
    # products was rebuilt; with foreign keys on, dropping the old table
    # would have cascaded into reviews.
    assert db.execute("pragma foreign_key_check").fetchall() == []
    db.close()
    assert any(p["sku"] == "KEEP" for p in app.get("/api/products")[1])
    assert len(app.get("/api/reviews")[1]) == 1, "child rows survive the rebuild"


def run_lifecycle(backend: Backend, tmp_path) -> None:
    database = str(tmp_path / "app.db")
    log_path = str(tmp_path / "server.log")
    stack_info = stack(backend.key)
    env = backend.environment(database)

    def serve(folder: str) -> Server:
        backend.prepare(folder, env)
        return Server(
            backend.command(folder),
            env,
            log_path,
            backend.cwd(folder, str(tmp_path)),
        )

    first = dc.build_deterministic_codegen_data(FakeProject(SHOP), stack_info)
    assert first["validation_warnings"] == []
    assert first["migrations"]["tool"] == backend.tool
    folder = write_backend(first, tmp_path, backend.sources)
    backend.build(folder)
    backend.first_build_checks(folder)

    with serve(folder) as app:
        initial_checks(app, database, backend)
    db = sqlite3.connect(database)
    db.execute("insert into customers (email) values ('pre@x.io')")
    db.commit()
    db.close()

    # Regenerating an unchanged schema adds nothing.
    same = dc.build_deterministic_codegen_data(FakeProject(SHOP, first), stack_info)
    assert backend.migration_files(same) == backend.migration_files(first)

    second = dc.build_deterministic_codegen_data(
        FakeProject(evolved(SHOP), first), stack_info
    )
    added = set(backend.migration_files(second)) - set(backend.migration_files(first))
    assert len(added) == 1 and "create_reviews_and_more" in added.pop()
    for file, content in backend.migration_files(first).items():
        assert backend.migration_files(second)[file] == content, (
            "an earlier revision was rewritten"
        )
    folder = write_backend(second, tmp_path, backend.sources)
    backend.build(folder)
    with serve(folder) as app:
        evolved_checks(app, database, backend)

    # A column drop is refused until the user confirms it.
    dropped = evolved(SHOP)
    dropped[3]["key_fields"].remove("stock_count")
    with pytest.raises(migrations_gen.DestructiveMigrationError):
        dc.build_deterministic_codegen_data(FakeProject(dropped, second), stack_info)
    third = dc.build_deterministic_codegen_data(
        FakeProject(dropped, second), stack_info, allow_destructive_migration=True
    )
    folder = write_backend(third, tmp_path, backend.sources)
    backend.build(folder)
    with serve(folder) as app:
        destroyed_checks(app, database, backend)

    # Undoing the newest migration brings the dropped column back.
    revert = (
        backend.revert(folder)
        if backend.revert
        else [*backend.command(folder), "revert"]
    )
    where = backend.cwd(folder, str(tmp_path))
    run(revert, where, timeout=180, env=env)
    assert backend.applied(database) == [1, 2]
    db = sqlite3.connect(database)
    assert "stock_count" in [r[1] for r in db.execute("pragma table_info('products')")]
    assert db.execute("select count(*) from reviews").fetchone()[0] == 1
    assert db.execute("pragma foreign_key_check").fetchall() == []
    db.close()

    # The whole history goes down to nothing and back up again.
    for _ in range(2):
        run(revert, where, timeout=180, env=env)
    left = {
        r[0]
        for r in query(
            database,
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'",
        )
    }
    assert left == set(backend.bookkeeping) and backend.applied(database) == []
    with serve(folder) as app:
        assert backend.applied(database) == [1, 2, 3]
        assert [r["email"] for r in app.get("/api/customers")[1]] == [
            "a@x.io",
            "b@x.io",
        ], "seed rows again"


# Names a generator has to survive: keywords of the languages generated here,
# names its own code uses, names of framework types, and tables stored under
# the names migration tools keep their history in (`migrations` is Laravel's
# and TypeORM's, `schema_migrations` Rails'; every other backend has to run
# them as ordinary tables).
AWKWARD_TABLES = [
    {
        "name": "Type",
        "key_fields": ["func", "range", "map", "select", "go", "defer", "var", "len"],
    },
    {
        "name": "Table",
        "key_fields": ["class", "event", "object", "string", "namespace", "new_value"],
    },
    {
        "name": "Support",
        "key_fields": ["input", "row", "body", "creating", "db", "label", "items"],
    },
    {
        "name": "Data",
        "key_fields": ["rows", "err", "ctx", "columns", "values", "query", "done"],
    },
    {
        "name": "Models",
        "key_fields": ["date_time", "date_only", "parent", "problems", "sets"],
        "field_specs": [
            {"name": "date_time", "type": "datetime"},
            {"name": "date_only", "type": "date"},
        ],
    },
    {
        "name": "Api",
        "key_fields": ["system", "task", "list", "find", "read", "store", "fields"],
    },
    {
        "name": "System",
        "key_fields": ["type_id", "table_id", "api_id", "item", "context", "error"],
        "foreign_keys": [
            {"field": "type_id", "references_table": "Type"},
            {"field": "table_id", "references_table": "Table"},
            {"field": "api_id", "references_table": "Api"},
        ],
    },
    {"name": "Error", "key_fields": ["message", "status", "detail", "key"]},
    {"name": "Context", "key_fields": ["request", "response", "user", "url"]},
    {"name": "Item", "key_fields": ["s", "in", "c", "f", "p", "m", "t"]},
    {"name": "Migration", "key_fields": ["step", "batch"]},
    {"name": "Schema Migration", "key_fields": ["note"]},
]


_SAMPLE_VALUES = {
    "string": "x",
    "text": 'long\ntext "quoted" é',
    "integer": 7,
    "float": 1.5,
    "decimal": 2.25,
    "boolean": True,
    "date": "2026-01-02",
    "datetime": "2026-01-02T03:04:05Z",
    "json": {"a": [1, None]},
}


def _without_table(tables: list[dict], name: str) -> None:
    tables[:] = [t for t in tables if t["name"] != name]
    for other in tables:
        other["foreign_keys"] = [
            fk for fk in other.get("foreign_keys", []) if fk["references_table"] != name
        ]


def _without_field(table: dict, field: str) -> None:
    table["key_fields"] = [f for f in table["key_fields"] if f != field]
    table["foreign_keys"] = [
        fk for fk in table.get("foreign_keys", []) if fk["field"] != field
    ]
    table["field_specs"] = [
        s for s in table.get("field_specs", []) if s["name"] != field
    ]


_REFUSED_TABLE = re.compile(r'The table "(.+?)" ')
_REFUSED_FIELD = re.compile(r'The fields? "(.+?)"(?: and "(.+?)")? in "(.+?)" ')


def awkward_tables(backend_key: str, extra: list[dict] = ()) -> list[dict]:
    """AWKWARD_TABLES (and a backend's own `extra` ones) without what this
    backend refuses — first the schema check every backend shares (a C#
    class can't be called Type), then the generator's own name rules (a
    Ruby class can't be called Data). What's left has to build and run."""
    tables = copy.deepcopy([*AWKWARD_TABLES, *extra])
    for _ in range(80):
        issues = db_schema.validate_tables(tables, backend_key)
        if issues:
            issue = issues[0]
            table = tables[issue.table_index]
            if issue.kind == "field":
                _without_field(table, table["key_fields"][issue.index])
            elif issue.kind == "table":
                _without_table(tables, table["name"])
            else:
                raise AssertionError(f"can't route around: {issue.message}")
            continue
        try:
            dc.build_deterministic_codegen_data(FakeProject(tables), stack(backend_key))
        except dc.DeterministicCodegenError as refused:
            problem = str(refused).split("\n")[-1]
            if match := _REFUSED_FIELD.search(problem):
                table = next(t for t in tables if t["name"] == match.group(3))
                _without_field(table, match.group(2) or match.group(1))
            elif match := _REFUSED_TABLE.search(problem):
                _without_table(tables, match.group(1))
            else:
                raise
            continue
        return tables
    raise AssertionError("the awkward tables never became valid")


def build_awkward_names(backend: Backend, tmp_path, extra: list[dict] = ()) -> str:
    """The generated project still builds, and still round-trips every
    field, when its tables and fields are named like the things its own
    code is made of. Returns the project's folder."""
    tables = awkward_tables(backend.key, extra)
    assert len(tables) >= 8 + len(extra), [t["name"] for t in tables]
    data = dc.build_deterministic_codegen_data(FakeProject(tables), stack(backend.key))
    assert data["validation_warnings"] == []
    folder = write_backend(data, tmp_path, backend.sources)
    backend.build(folder)
    backend.first_build_checks(folder)
    database = str(tmp_path / "app.db")
    env = backend.environment(database)
    backend.prepare(folder, env)
    schema = db_schema.resolve_schema(tables, backend=backend.key)
    with Server(
        backend.command(folder),
        env,
        str(tmp_path / "server.log"),
        backend.cwd(folder, str(tmp_path)),
    ) as app:
        for table in schema.tables:
            url = f"/api/{table.sql_name}"
            assert app.get(url)[:2] == (200, []), url
            sent = {c.column: _SAMPLE_VALUES[c.type] for c in table.columns if not c.fk}
            status, row, _ = app.post(url, sent)
            assert status == 201, (url, row)
            assert {k: row[k] for k in sent} == sent, url
            assert all(row[c.column] is None for c in table.columns if c.fk), url
            assert app.get(f"{url}/{row['id']}")[1] == row, url
            for column in table.columns:
                if column.fk:
                    status, body, _ = app.post(url, {column.column: 999})
                    assert status == 422 and (
                        f"{column.column}: no row in {column.fk.ref_table} has id 999."
                        in json.dumps(body)
                    ), (url, body)
    return folder
