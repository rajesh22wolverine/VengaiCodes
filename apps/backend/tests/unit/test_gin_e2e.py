"""
End-to-end test of the deterministic (no-AI) Gin backend — nothing is
mocked. The generated project is written to a temp folder, tidied, checked
with gofmt and go vet, compiled with the real Go toolchain and run as a
real server on a real SQLite file; the same checks the FastAPI end-to-end
test makes (test_deterministic_migrations_e2e.py — same schema, same
changes) are then made over HTTP: defaults, validation, unique / check /
foreign-key refusals, ON DELETE cascade / set null / restrict. The schema
is then evolved and regenerated against the SAME database file, a column is
dropped, and the whole history is reverted and re-applied.

Needs `go` on PATH (and the network, once, for `go mod tidy`). Without it
the test is skipped — unless VENGAI_REQUIRE_TOOLCHAINS lists "go", which
the backend CI job sets so a missing toolchain can't pass as a skip.
"""

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request

import pytest
from test_deterministic_migrations_e2e import SHOP, FakeProject, evolved

from app.ai import codegen_deterministic as dc
from app.ai import migrations_gen

GIN_STACK = {
    "frontend_framework": "react",
    "backend_framework": "gin",
    "api_style": "rest",
    "codegen_target": "react_gin",
    "source": "selected_stack",
}

GO = shutil.which("go")
REQUIRED = "go" in os.environ.get("VENGAI_REQUIRE_TOOLCHAINS", "").split(",")
EXE = ".exe" if os.name == "nt" else ""
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _run(args: list[str], cwd: str, timeout: int = 900) -> str:
    proc = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    assert proc.returncode == 0, (
        f"`{' '.join(args)}` failed:\n{proc.stdout[-6000:]}\n{proc.stderr[-6000:]}"
    )
    return proc.stdout


def _write_backend(data: dict, root) -> str:
    """Replaces root/backend's sources with this generation's (the way a
    regenerated project replaces the old one), keeping go.sum and builds."""
    backend = root / "backend"
    wanted = {
        f["path"]: f["content"]
        for f in data["codegen"]["files"]
        if f["path"].startswith("backend/")
    }
    if backend.exists():
        for path in backend.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if (
                path.is_file()
                and path.suffix in (".go", ".sql")
                and relative not in wanted
            ):
                path.unlink()
    for path, content in wanted.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    return str(backend)


def _build(backend: str) -> str:
    """What the README says to do after generating or regenerating:
    `go mod tidy` (a regenerated go.mod lists only what the code imports),
    then build."""
    binary = os.path.join(backend, f"app{EXE}")
    _run([GO, "mod", "tidy"], backend)
    _run([GO, "build", "-o", binary, "."], backend)
    return binary


class Server:
    """The compiled app, serving on a free port."""

    def __init__(self, binary: str, database: str, log_path: str):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.log_path = log_path
        self.log = open(log_path, "ab")
        self.proc = subprocess.Popen(
            [binary],
            cwd=os.path.dirname(database),
            env={
                **os.environ,
                "PORT": str(self.port),
                "DATABASE_PATH": database,
                "GIN_MODE": "release",
            },
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

    def output(self) -> str:
        self.log.flush()
        with open(self.log_path, encoding="utf-8", errors="replace") as f:
            return f.read()[-6000:]

    def __enter__(self):
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"the app exited at startup:\n{self.output()}")
            try:
                status, body, _ = self.call("GET", "/")
                if status == 200:
                    return self
            except OSError:
                time.sleep(0.2)
        raise AssertionError(f"the app never answered:\n{self.output()}")

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=20)
        self.log.close()

    def call(self, method: str, path: str, body=None, raw: bytes | None = None):
        data = (
            raw
            if raw is not None
            else (None if body is None else json.dumps(body).encode("utf-8"))
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Origin": "tauri://localhost"},
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


def _migration_files(data: dict) -> dict[str, str]:
    return {
        f["path"]: f["content"]
        for f in data["codegen"]["files"]
        if f["path"].startswith("backend/migrations/") and f["path"].endswith(".sql")
    }


def _versions(database: str) -> list[tuple[int, str]]:
    db = sqlite3.connect(database)
    try:
        return db.execute(
            "select version, name from _migrations order by version"
        ).fetchall()
    finally:
        db.close()


def _initial_checks(app: Server, database: str) -> None:
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
    assert _versions(database) == [(1, "initial")]

    status, root, headers = app.get("/")
    assert root == {"message": "Shop's (Demo API is running"}
    assert headers["Access-Control-Allow-Origin"] == "*"
    status, _, headers = app.call("OPTIONS", "/api/customers")
    assert status == 204 and "PUT" in headers["Access-Control-Allow-Methods"]

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
    status, body, _ = app.post("/api/customers", {"email": "c@x.io"})
    assert status == 409 and "already has this email" in body["error"], body
    status, body, _ = app.post("/api/customers", {"email": "no-at-sign"})
    assert status == 422 and "email has at" in body["error"], body
    status, body, _ = app.post("/api/customers", {"name": "x"})
    assert (status, body) == (422, {"error": "email: is required"})
    # Every problem at once: the wrong kind, then what's missing.
    status, body, _ = app.post("/api/customers", {"is_active": "yes", "name": 5})
    assert (status, body["error"].split("\n")) == (
        422,
        [
            "name: expected text",
            "is_active: expected true or false",
            "email: is required",
        ],
    )
    assert app.post("/api/customers", [1])[0] == 400, "a body that isn't an object"
    status, body, _ = app.call("POST", "/api/customers", raw=b"{nope")
    assert (status, body) == (400, {"error": "Send the record as a JSON object."})
    assert app.get("/api/customers/abc")[:2] == (
        400,
        {"error": "id: not a valid id"},
    )
    assert app.get("/api/customers/999")[:2] == (
        404,
        {"error": "customers 999 not found."},
    )

    status, body, _ = app.put(
        f"/api/customers/{cust['id']}", {"profile": {"a": [1, 2]}, "name": "Cy"}
    )
    assert status == 200 and body["profile"] == {"a": [1, 2]} and body["name"] == "Cy"
    assert body["email"] == "c@x.io", "a field the request left out is kept"
    status, body, _ = app.put(f"/api/customers/{cust['id']}", {"profile": None})
    assert status == 200 and body["profile"] is None and body["name"] == "Cy"

    status, body, _ = app.post("/api/orders", {"customer_id": "abc"})
    assert (status, body) == (
        422,
        {"error": "customer_id: expected a whole number"},
    )
    status, body, _ = app.post("/api/orders", {"customer_id": 9999})
    assert (status, body) == (
        422,
        {"error": "customer_id: no row in customers has id 9999."},
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
        status, body, _ = app.post("/api/orders", {"customer_id": cust["id"], **bad})
        assert status == 422 and why in body["error"], body
    status, body, _ = app.post(
        "/api/orders", {"customer_id": cust["id"], "total": "1.234"}
    )
    assert (status, body) == (
        422,
        {"error": "total: only 2 decimal places are stored"},
    )
    status, body, _ = app.put(orders, {"status": None})
    assert (status, body) == (422, {"error": "status: may not be null"})
    status, body, _ = app.put(
        orders,
        {"status": "paid", "total": "12.50", "placed_at": "2024-01-31T09:30:00+02:00"},
    )
    assert status == 200 and body["status"] == "paid" and body["total"] == 12.5
    assert body["placed_at"] == "2024-01-31T07:30:00Z", "stored and answered in UTC"
    assert body["customer_id"] == cust["id"], "partial update"
    assert app.put(orders, {"total": 3})[1]["total"] == 3
    assert app.put("/api/orders/999", {"total": 3})[0] == 404

    status, product, _ = app.post(
        "/api/products", {"sku": "SKU1", "title": "Widget", "price": 9.5}
    )
    assert status == 201 and product["price"] == 9.5
    status, body, _ = app.post("/api/products", {"sku": "SKU1"})
    assert status == 409 and "already has this sku" in body["error"], body
    items = {"order_id": order["id"], "product_id": product["id"]}
    status, item, _ = app.post("/api/order_items", {**items, "quantity": 2})
    assert status == 201 and item["quantity"] == 2
    status, body, _ = app.post("/api/order_items", items)
    assert status == 409 and "order_id, product_id" in body["error"], body
    status, body, _ = app.post(
        "/api/order_items", {"order_id": order["id"], "quantity": 0}
    )
    assert status == 422 and "qty positive" in body["error"], body

    status, body, _ = app.delete(f"/api/products/{product['id']}")
    assert status == 409 and "order items" in body["error"], "ON DELETE RESTRICT"
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
    status, body, _ = app.post("/api/notes", {"due": "not a date"})
    assert (status, body) == (
        422,
        {"error": "due: expected a date like 2024-01-31"},
    )

    # Rows the next migration must carry forward.
    app.post("/api/products", {"sku": "KEEP", "title": "Kept", "stock_count": 4})


def _evolved_checks(app: Server, database: str) -> None:
    assert _versions(database) == [(1, "initial"), (2, "create_reviews_and_more")]
    rows = app.get("/api/customers")[1]
    assert next(r for r in rows if r["email"] == "pre@x.io")["name"] == "anon", (
        "NULL backfilled before NOT NULL"
    )
    kept = next(p for p in app.get("/api/products")[1] if p["sku"] == "KEEP")
    assert kept["is_featured"] is False and kept["stock_count"] == 4
    status, body, _ = app.post("/api/products", {"sku": "N2", "price": -3})
    assert status == 422 and "price positive" in body["error"], body
    status, review, _ = app.post("/api/reviews", {"product_id": kept["id"]})
    assert status == 201 and review["rating"] == 5, "new table with a foreign key"
    status, body, _ = app.post("/api/reviews", {"product_id": kept["id"], "rating": 9})
    assert status == 422 and "rating range" in body["error"], body
    db = sqlite3.connect(database)
    assert "ix_products_title" in [
        r[1] for r in db.execute("pragma index_list('products')")
    ]
    db.close()


def _destroyed_checks(app: Server, database: str) -> None:
    assert [v for v, _ in _versions(database)] == [1, 2, 3]
    db = sqlite3.connect(database)
    columns = [r[1] for r in db.execute("pragma table_info('products')")]
    assert "stock_count" not in columns and "sku" in columns
    # products was rebuilt; with foreign keys on, dropping the old table
    # would have cascaded into reviews.
    assert db.execute("pragma foreign_key_check").fetchall() == []
    db.close()
    assert any(p["sku"] == "KEEP" for p in app.get("/api/products")[1])
    assert len(app.get("/api/reviews")[1]) == 1, "child rows survive the rebuild"


def test_generated_gin_app_builds_runs_and_migrates_a_real_database(tmp_path):
    if GO is None:
        if REQUIRED:
            pytest.fail("VENGAI_REQUIRE_TOOLCHAINS lists go, but `go` isn't on PATH")
        pytest.skip("needs the Go toolchain (the backend CI job installs it)")

    database = str(tmp_path / "app.db")
    log_path = str(tmp_path / "server.log")
    first = dc.build_deterministic_codegen_data(FakeProject(SHOP), GIN_STACK)
    assert first["validation_warnings"] == []
    assert first["migrations"]["tool"] == "sqlite-go"
    backend = _write_backend(first, tmp_path)

    unformatted = _run(["gofmt", "-l", "."], backend).strip()
    assert not unformatted, "gofmt would change:\n" + _run(
        ["gofmt", "-d", "."], backend
    )
    binary = _build(backend)
    _run([GO, "vet", "./..."], backend)
    # The exact command the installer workflows build the desktop sidecar with.
    _run([GO, "build", "-o", f"dist_go/backend{EXE}", "main.go"], backend)

    with Server(binary, database, log_path) as app:
        _initial_checks(app, database)
    db = sqlite3.connect(database)
    db.execute("insert into customers (email) values ('pre@x.io')")
    db.commit()
    db.close()

    # Regenerating an unchanged schema adds nothing.
    same = dc.build_deterministic_codegen_data(FakeProject(SHOP, first), GIN_STACK)
    assert _migration_files(same) == _migration_files(first)

    second = dc.build_deterministic_codegen_data(
        FakeProject(evolved(SHOP), first), GIN_STACK
    )
    assert set(_migration_files(second)) - set(_migration_files(first)) == {
        "backend/migrations/0002_create_reviews_and_more.sql"
    }
    backend = _write_backend(second, tmp_path)
    assert not _run(["gofmt", "-l", "."], backend).strip()
    binary = _build(backend)
    with Server(binary, database, log_path) as app:
        _evolved_checks(app, database)

    # A column drop is refused until the user confirms it.
    dropped = evolved(SHOP)
    dropped[3]["key_fields"].remove("stock_count")
    with pytest.raises(migrations_gen.DestructiveMigrationError):
        dc.build_deterministic_codegen_data(FakeProject(dropped, second), GIN_STACK)
    third = dc.build_deterministic_codegen_data(
        FakeProject(dropped, second), GIN_STACK, allow_destructive_migration=True
    )
    backend = _write_backend(third, tmp_path)
    binary = _build(backend)
    with Server(binary, database, log_path) as app:
        _destroyed_checks(app, database)

    # `revert` undoes the newest migration: the dropped column is back.
    env = {**os.environ, "DATABASE_PATH": database}
    reverted = subprocess.run(
        [binary, "revert"], capture_output=True, text=True, env=env, timeout=120
    )
    assert reverted.returncode == 0, reverted.stderr
    assert [v for v, _ in _versions(database)] == [1, 2]
    db = sqlite3.connect(database)
    assert "stock_count" in [r[1] for r in db.execute("pragma table_info('products')")]
    assert db.execute("select count(*) from reviews").fetchone()[0] == 1
    db.close()

    # The whole history goes down to nothing and back up again.
    for _ in range(2):
        subprocess.run([binary, "revert"], check=True, env=env, timeout=120)
    db = sqlite3.connect(database)
    left = {
        r[0]
        for r in db.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
        )
    }
    db.close()
    assert left == {"_migrations"} and _versions(database) == []
    with Server(binary, database, log_path) as app:
        assert [v for v, _ in _versions(database)] == [1, 2, 3]
        assert [r["email"] for r in app.get("/api/customers")[1]] == [
            "a@x.io",
            "b@x.io",
        ], "seed rows again"
