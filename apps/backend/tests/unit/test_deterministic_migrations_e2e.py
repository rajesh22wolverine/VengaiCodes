"""
End-to-end tests for the deterministic (no-AI) generator's typed schema
and versioned migrations — nothing about the SQL is mocked.

The generated React + FastAPI backend is written to a temp folder and run
in a SUBPROCESS whose import path is that folder plus the installed
packages only, never VengaiCode's own apps/backend (whose `app` package
would shadow the generated one). Its real startup hook applies the Alembic
migrations to a real SQLite file, and the CRUD routes are exercised over
TestClient: defaults, unique/check/foreign-key refusals, ON DELETE
cascade / set null / restrict. The schema is then evolved and regenerated
against the SAME database file, the way a user's app would be upgraded.

The Vue + Express side needs a MongoDB server, so here it is checked
with `node --check` on every generated backend file plus a differential
test of lib/checks.js against check_expr.evaluate() (skipped without
node). The full Express app was also run against a real mongod while
this was written — see migrations_gen.py's notes.
"""

import asyncio
import copy
import json
import os
import shutil
import subprocess
import sys
import textwrap
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai import check_expr, codegen_deterministic as dc, db_schema, migrations_gen
from app.api.v1.auth import get_current_active_user
from app.core.database import Base, get_db
from app.main import app
from app.models.project import Project
from app.models.user import User

FASTAPI_STACK = {
    "frontend_framework": "react",
    "backend_framework": "fastapi",
    "api_style": "rest",
    "codegen_target": "react_fastapi",
    "source": "selected_stack",
}
EXPRESS_STACK = {
    "frontend_framework": "vue",
    "backend_framework": "express",
    "api_style": "rest",
    "codegen_target": "vue_express",
    "source": "selected_stack",
}

SHOP = [
    {
        "name": "customers",
        "purpose": 'People """ who \\ order',
        "key_fields": ["email", "name", "is_active", "profile"],
        "field_specs": [
            {"name": "email", "type": "string", "nullable": False, "unique": True},
            {"name": "is_active", "type": "boolean", "default": True},
            {"name": "profile", "type": "json", "default": {"tier": "basic"}},
        ],
        "checks": [{"name": "email has at", "expression": "email LIKE '%@%'"}],
        "seed_rows": [
            {"email": "a@x.io", "name": "Ann"},
            {"email": "b@x.io", "name": "Bob", "is_active": False},
        ],
    },
    {
        "name": "coupons",
        "key_fields": ["code", "percent_off"],
        "field_specs": [
            {"name": "code", "type": "string", "nullable": False, "unique": True},
            {
                "name": "percent_off",
                "type": "integer",
                "nullable": False,
                "default": 10,
            },
        ],
        "checks": [
            {"name": "percent range", "expression": "percent_off BETWEEN 1 AND 100"}
        ],
        "seed_rows": [{"code": "WELCOME", "percent_off": 15}],
    },
    {
        "name": "orders",
        "key_fields": [
            "customer_id",
            "coupon_id",
            "total",
            "status",
            "placed_at",
            "ship_date",
        ],
        "field_specs": [
            {"name": "customer_id", "nullable": False},
            {"name": "total", "type": "decimal", "nullable": False, "default": "0.00"},
            {"name": "status", "type": "string", "nullable": False, "default": "draft"},
            {"name": "placed_at", "type": "datetime", "default": "now"},
            {"name": "ship_date", "type": "date"},
        ],
        "foreign_keys": [
            {
                "field": "customer_id",
                "references_table": "customers",
                "on_delete": "cascade",
            },
            {
                "field": "coupon_id",
                "references_table": "coupons",
                "on_delete": "set_null",
            },
        ],
        "checks": [
            {"name": "total non negative", "expression": "total >= 0"},
            {
                "name": "status known",
                "expression": "status IN ('draft', 'paid', 'shipped')",
            },
        ],
        "indexes": [{"fields": ["status", "placed_at"]}],
    },
    {
        "name": "products",
        "key_fields": ["sku", "title", "price", "stock_count"],
        "field_specs": [{"name": "sku", "type": "string", "nullable": False}],
        "indexes": [{"fields": ["sku"], "unique": True}],
    },
    {
        "name": "order items",
        "key_fields": ["order_id", "product_id", "quantity"],
        "field_specs": [
            {"name": "quantity", "type": "integer", "nullable": False, "default": 1}
        ],
        "foreign_keys": [
            {"field": "order_id", "references_table": "orders", "on_delete": "cascade"},
            {
                "field": "product_id",
                "references_table": "products",
                "on_delete": "restrict",
            },
        ],
        "checks": [{"name": "qty positive", "expression": "quantity > 0"}],
        "indexes": [{"fields": ["order_id", "product_id"], "unique": True}],
    },
    {
        "name": "employees",
        "key_fields": ["name", "manager_id"],
        "foreign_keys": [
            {
                "field": "manager_id",
                "references_table": "employees",
                "on_delete": "set_null",
            }
        ],
    },
    {
        # A field called "date" followed by another date field: the second
        # annotation must still mean the date type (see _PyTypes).
        "name": "Notes :)",
        "key_fields": ["date", "due", "title", "copy"],
        "field_specs": [
            {"name": "date", "type": "date"},
            {"name": "due", "type": "date"},
        ],
    },
]


def evolved(tables: list[dict]) -> list[dict]:
    """Additive changes: a required column with a default, an index, a
    check, a NOT NULL-with-default on a nullable column, a new table with
    a foreign key to an existing one."""
    t = copy.deepcopy(tables)
    products = t[3]
    products["key_fields"].append("is_featured")
    products["field_specs"].append(
        {"name": "is_featured", "type": "boolean", "nullable": False, "default": False}
    )
    products["indexes"].append({"fields": ["title"]})
    products["checks"] = [
        {"name": "price positive", "expression": "price IS NULL OR price > 0"}
    ]
    t[0]["field_specs"].append({"name": "name", "nullable": False, "default": "anon"})
    t.append(
        {
            "name": "reviews",
            "key_fields": ["product_id", "rating", "body"],
            "field_specs": [
                {"name": "rating", "type": "integer", "nullable": False, "default": 5}
            ],
            "foreign_keys": [{"field": "product_id", "references_table": "products"}],
            "checks": [
                {"name": "rating range", "expression": "rating BETWEEN 1 AND 5"}
            ],
        }
    )
    return t


class FakeProject:
    def __init__(self, tables, codegen_data=None):
        self.name = "Shop's (Demo"
        self.architecture_data = {
            "architecture": {"database_tables": tables, "api_endpoints": []}
        }
        self.requirements_data = {"frd": {"key_features": [], "user_stories": []}}
        self.codegen_data = codegen_data


def _files(data: dict) -> dict[str, str]:
    return {f["path"]: f["content"] for f in data["codegen"]["files"]}


def _write_backend(data: dict, root) -> str:
    """Writes backend/ files under root (keeping anything else there, e.g.
    the SQLite database of an earlier run) and returns backend's path."""
    for path, content in _files(data).items():
        if not path.startswith("backend/"):
            continue
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    return str(root / "backend")


def _run_app_script(backend_dir: str, body: str) -> str:
    """Runs `body` inside the generated backend (cwd = backend, import path
    = backend + installed packages only). Fails the test on a non-zero
    exit, showing the script's output."""
    site_packages = [p for p in sys.path if p.rstrip("\\/").endswith("site-packages")]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([backend_dir, *site_packages]),
        "PYTHONIOENCODING": "utf-8",
    }
    env.pop("DATABASE_URL", None)
    script = os.path.join(backend_dir, "_e2e_check.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(
            "import sqlite3, sys\n"
            "from fastapi.testclient import TestClient\n"
            "import main\n\n"
            "def check(cond, msg):\n"
            "    if not cond:\n"
            "        print('FAILED: ' + msg)\n"
            "        sys.exit(1)\n\n" + textwrap.dedent(body)
        )
    proc = subprocess.run(
        [sys.executable, script],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert proc.returncode == 0, (
        f"generated app check failed:\n{proc.stdout}\n{proc.stderr[-4000:]}"
    )
    return proc.stdout


INITIAL_CHECKS = """
with TestClient(main.app) as c:  # the context manager runs startup -> migrations
    db = sqlite3.connect("app.db")
    tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
    check({"customers", "orders", "order_items", "products", "coupons", "employees", "notes"} <= tables, str(tables))
    check(db.execute("select version_num from alembic_version").fetchone()[0] == "0001", "at revision 0001")

    rows = c.get("/api/customers").json()
    check([r["email"] for r in rows] == ["a@x.io", "b@x.io"], "seed rows")
    check(rows[0]["is_active"] is True and rows[1]["is_active"] is False, "seed value + server default")
    check(rows[0]["profile"] == {"tier": "basic"}, "json server default")
    coupon_id = c.get("/api/coupons").json()[0]["id"]

    r = c.post("/api/customers", json={"email": "c@x.io"})
    check(r.status_code == 201 and r.json()["is_active"] is True, "create applies defaults")
    cust = r.json()
    r = c.post("/api/customers", json={"email": "c@x.io"})
    check(r.status_code == 409 and "already has this email" in r.json()["detail"], "unique -> 409")
    r = c.post("/api/customers", json={"email": "no-at-sign"})
    check(r.status_code == 422 and "email has at" in r.json()["detail"], "check -> 422")
    check(c.post("/api/customers", json={"name": "x"}).status_code == 422, "missing required -> 422")
    check(c.post("/api/orders", json={"customer_id": "abc"}).status_code == 422, "bad type -> 422")
    r = c.post("/api/orders", json={"customer_id": 9999})
    check(r.status_code == 422 and "customer_id" in r.json()["detail"], "missing parent -> 422")

    r = c.post("/api/orders", json={"customer_id": cust["id"], "coupon_id": coupon_id, "ship_date": "2026-10-01"})
    order = r.json()
    check(r.status_code == 201 and order["status"] == "draft" and order["total"] == 0 and order["placed_at"], "order defaults")
    check(c.post("/api/orders", json={"customer_id": cust["id"], "total": "-1.00"}).status_code == 422, "decimal check")
    check(c.post("/api/orders", json={"customer_id": cust["id"], "total": "1.234"}).status_code == 422, "decimal places")
    check(c.post("/api/orders", json={"customer_id": cust["id"], "status": "bogus"}).status_code == 422, "IN check")
    check(c.put(f"/api/orders/{order['id']}", json={"status": None}).status_code == 422, "null on a required field")
    r = c.put(f"/api/orders/{order['id']}", json={"status": "paid"})
    check(r.json()["status"] == "paid" and r.json()["customer_id"] == cust["id"], "partial update")

    p = c.post("/api/products", json={"sku": "SKU1", "title": "Widget", "price": 9.5}).json()
    check(c.post("/api/products", json={"sku": "SKU1"}).status_code == 409, "unique index -> 409")
    item = c.post("/api/order_items", json={"order_id": order["id"], "product_id": p["id"], "quantity": 2}).json()
    check(c.post("/api/order_items", json={"order_id": order["id"], "product_id": p["id"]}).status_code == 409, "composite unique")
    r = c.delete(f"/api/products/{p['id']}")
    check(r.status_code == 409 and "order items" in r.json()["detail"], "ON DELETE RESTRICT -> 409")
    check(c.delete(f"/api/coupons/{coupon_id}").status_code == 204, "delete coupon")
    check(c.get(f"/api/orders/{order['id']}").json()["coupon_id"] is None, "ON DELETE SET NULL")
    check(c.delete(f"/api/customers/{cust['id']}").status_code == 204, "delete customer")
    check(c.get(f"/api/orders/{order['id']}").status_code == 404, "cascade to orders")
    check(c.get(f"/api/order_items/{item['id']}").status_code == 404, "cascade two levels")
    check(c.delete(f"/api/products/{p['id']}").status_code == 204, "deletable once nothing refers to it")

    boss = c.post("/api/employees", json={"name": "Boss"}).json()
    worker = c.post("/api/employees", json={"name": "W", "manager_id": boss["id"]}).json()
    c.delete(f"/api/employees/{boss['id']}")
    check(c.get(f"/api/employees/{worker['id']}").json()["manager_id"] is None, "self-reference set null")

    r = c.post("/api/notes", json={"date": "2026-01-02", "due": "2026-02-03", "copy": "c"})
    check(r.status_code == 201 and r.json()["due"] == "2026-02-03", "a field named date doesn't break later ones")
    check(c.post("/api/notes", json={"due": "not a date"}).status_code == 422, "due is still a date")

    # Rows the next migration must carry forward.
    c.post("/api/products", json={"sku": "KEEP", "title": "Kept", "stock_count": 4})
db.execute("insert into customers (email) values ('pre@x.io')")
db.commit()
print("INITIAL OK")
"""

EVOLVED_CHECKS = """
with TestClient(main.app) as c:
    db = sqlite3.connect("app.db")
    check(db.execute("select version_num from alembic_version").fetchone()[0] == "0002", "upgraded to 0002")
    rows = c.get("/api/customers").json()
    check(next(r for r in rows if r["email"] == "pre@x.io")["name"] == "anon", "NULL backfilled before NOT NULL")
    kept = next(p for p in c.get("/api/products").json() if p["sku"] == "KEEP")
    check(kept["is_featured"] is False and kept["stock_count"] == 4, "old row kept, new column filled")
    check(c.post("/api/products", json={"sku": "N2", "price": -3}).status_code == 422, "new check")
    r = c.post("/api/reviews", json={"product_id": kept["id"]})
    check(r.status_code == 201 and r.json()["rating"] == 5, "new table with a foreign key")
    check(c.post("/api/reviews", json={"product_id": kept["id"], "rating": 9}).status_code == 422, "new table check")
    check("ix_products_title" in [r[1] for r in db.execute("pragma index_list('products')")], "new index")
print("EVOLVED OK")
"""

DESTROYED_CHECKS = """
with TestClient(main.app) as c:
    db = sqlite3.connect("app.db")
    check(db.execute("select version_num from alembic_version").fetchone()[0] == "0003", "upgraded to 0003")
    cols = [r[1] for r in db.execute("pragma table_info('products')")]
    check("stock_count" not in cols and "sku" in cols, "only the dropped column is gone")
    check(any(p["sku"] == "KEEP" for p in c.get("/api/products").json()), "product rows survive")
    # Batch mode rebuilt products; with foreign keys on, that DROP would
    # have cascaded into reviews.
    check(len(c.get("/api/reviews").json()) == 1, "child rows survive the parent's rebuild")
    check(db.execute("pragma foreign_key_check").fetchall() == [], "no dangling foreign keys")
print("DESTROYED OK")
"""


def _revision_files(data: dict) -> dict[str, str]:
    return {
        p: c
        for p, c in _files(data).items()
        if p.startswith("backend/migrations/versions/")
    }


def test_generated_fastapi_app_migrates_and_evolves_a_real_database(tmp_path):
    first = dc.build_deterministic_codegen_data(FakeProject(SHOP), FASTAPI_STACK)
    assert first["validation_warnings"] == []
    assert [r["id"] for r in first["migrations"]["revisions"]] == ["0001"]
    backend = _write_backend(first, tmp_path)
    assert "INITIAL OK" in _run_app_script(backend, INITIAL_CHECKS)

    # Regenerating an unchanged schema adds nothing.
    same = dc.build_deterministic_codegen_data(FakeProject(SHOP, first), FASTAPI_STACK)
    assert _revision_files(same) == _revision_files(first)

    second = dc.build_deterministic_codegen_data(
        FakeProject(evolved(SHOP), first), FASTAPI_STACK
    )
    new = set(_revision_files(second)) - set(_revision_files(first))
    assert new == {"backend/migrations/versions/0002_create_reviews_and_more.py"}
    for path, content in _revision_files(first).items():
        assert _revision_files(second)[path] == content, (
            "an earlier revision was rewritten"
        )
    _write_backend(second, tmp_path)
    assert "EVOLVED OK" in _run_app_script(backend, EVOLVED_CHECKS)

    # A column drop is refused until the user confirms it.
    dropped = evolved(SHOP)
    dropped[3]["key_fields"].remove("stock_count")
    with pytest.raises(migrations_gen.DestructiveMigrationError) as refused:
        dc.build_deterministic_codegen_data(FakeProject(dropped, second), FASTAPI_STACK)
    assert refused.value.changes == [
        "drop column products.stock_count (deletes its data)"
    ]
    third = dc.build_deterministic_codegen_data(
        FakeProject(dropped, second), FASTAPI_STACK, allow_destructive_migration=True
    )
    assert third["migrations"]["revisions"][-1]["destructive"] == refused.value.changes
    _write_backend(third, tmp_path)
    assert "DESTROYED OK" in _run_app_script(backend, DESTROYED_CHECKS)

    # The whole history goes down to nothing and back up again.
    out = _run_app_script(
        backend,
        """
        import os
        from alembic import command
        from alembic.config import Config
        cfg = Config("alembic.ini")
        command.downgrade(cfg, "base")
        db = sqlite3.connect("app.db")
        left = [r[0] for r in db.execute("select name from sqlite_master where type='table'")]
        check(left == ["alembic_version"], f"downgrade base left {left}")
        command.upgrade(cfg, "head")
        check(db.execute("select version_num from alembic_version").fetchone()[0] == "0003", "back at head")
        print("ROUND TRIP OK")
        """,
    )
    assert "ROUND TRIP OK" in out


def test_models_and_migrations_describe_the_same_database(tmp_path):
    """`alembic check` compares the model classes with the migrated
    database and fails on any difference — the proof that models/<t>.py
    and the migrations agree (both are rendered from db_schema)."""
    data = dc.build_deterministic_codegen_data(
        FakeProject(evolved(SHOP)), FASTAPI_STACK
    )
    backend = _write_backend(data, tmp_path)
    out = _run_app_script(
        backend,
        """
        from alembic import command
        from alembic.config import Config
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")
        command.check(cfg)  # raises if autogenerate would emit anything
        print("CHECK OK")
        """,
    )
    assert "CHECK OK" in out


def test_a_change_no_migration_can_apply_is_refused_with_the_fix():
    first = dc.build_deterministic_codegen_data(FakeProject(SHOP), FASTAPI_STACK)
    blocked = copy.deepcopy(SHOP)
    blocked[3]["key_fields"].append("brand")
    blocked[3]["field_specs"].append({"name": "brand", "nullable": False})
    with pytest.raises(migrations_gen.MigrationError) as e:
        dc.build_deterministic_codegen_data(FakeProject(blocked, first), FASTAPI_STACK)
    assert not isinstance(e.value, migrations_gen.DestructiveMigrationError)
    assert "products.brand" in str(e.value) and "Give it a default" in str(e.value)


def test_colliding_class_names_are_refused_for_fastapi_only():
    tables = [
        {"name": "order", "key_fields": ["total"]},
        {
            "name": "order update",
            "key_fields": ["note"],
        },  # model OrderUpdate = order's update schema
    ]
    with pytest.raises(dc.DeterministicCodegenError, match="OrderUpdate"):
        dc.build_deterministic_codegen_data(FakeProject(tables), FASTAPI_STACK)
    assert (
        dc.build_deterministic_codegen_data(FakeProject(tables), EXPRESS_STACK)[
            "validation_warnings"
        ]
        == []
    )


def test_history_only_continues_from_a_deterministic_run():
    first = dc.build_deterministic_codegen_data(FakeProject(SHOP), FASTAPI_STACK)
    ai_run = {**first, "generation_mode": "ai"}
    again = dc.build_deterministic_codegen_data(
        FakeProject(evolved(SHOP), ai_run), FASTAPI_STACK
    )
    assert [r["id"] for r in again["migrations"]["revisions"]] == ["0001"]


# ─── Vue + Express ───
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_generated_express_backend_is_valid_javascript(tmp_path):
    data = dc.build_deterministic_codegen_data(
        FakeProject(evolved(SHOP)), EXPRESS_STACK
    )
    assert data["validation_warnings"] == []
    backend = _write_backend(data, tmp_path)
    checked = 0
    for root, _dirs, names in os.walk(backend):
        for name in names:
            if name.endswith(".js"):
                proc = subprocess.run(
                    [NODE, "--check", os.path.join(root, name)],
                    capture_output=True,
                    text=True,
                )
                assert proc.returncode == 0, f"{name}: {proc.stderr}"
                checked += 1
    assert checked >= 10
    pkg = json.loads(_files(data)["backend/package.json"])
    assert (
        pkg["dependencies"]["migrate-mongo"]
        == migrations_gen.MIGRATION_NPM_DEPENDENCIES["migrate-mongo"]
    )
    assert pkg["scripts"]["migrate"] == "migrate-mongo up"
    server = _files(data)["backend/server.js"]
    assert (
        server.index("await mongoose.connect")
        < server.index("await runMigrations()")
        < server.index("app.listen")
    )


CHECK_COLUMNS = {
    "n": "integer",
    "price": "decimal",
    "f": "float",
    "name": "string",
    "flag": "boolean",
    "day": "date",
    "at": "datetime",
}
CHECK_EXPRESSIONS = [
    "n > 3",
    "n <> 3",
    "price >= 0 AND price <= 10.5",
    "NOT (n BETWEEN 1 AND 5)",
    "n NOT BETWEEN f AND 10",
    "name IN ('a', 'Bob')",
    "name NOT IN ('a')",
    "name LIKE 'b_b%'",
    "name NOT LIKE '%x%'",
    "LENGTH(name) >= 3",
    "name IS NULL OR n IS NOT NULL",
    "flag",
    "flag = FALSE OR n < 0",
    "day >= '2024-01-31'",
    "day BETWEEN '2024-01-01' AND '2024-12-31'",
    "at < '2024-06-01T12:00:00'",
    "at IN ('2024-06-01T12:00:00')",
    "day <> at",
    "(n > 1 AND name = 'Bob') OR NOT flag",
]
CHECK_ROWS = [
    {},
    {
        "n": 3,
        "price": 1.25,
        "f": 2.5,
        "name": "Bob",
        "flag": True,
        "day": "2024-01-31",
        "at": "2024-06-01T12:00:00",
    },
    {
        "n": 7,
        "price": 11,
        "f": 7.0,
        "name": "bXb",
        "flag": False,
        "day": "2023-12-31",
        "at": "2024-06-01T11:59:59",
    },
    {
        "n": 0,
        "price": 0,
        "name": "ab",
        "flag": None,
        "day": "2025-01-01",
        "at": "2025-01-01T00:00:00",
    },
    {"n": 5, "name": "BOB", "at": "2024-06-01T12:00:00"},
    {"n": -2, "name": "a", "flag": False, "price": -1},
]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_mongoose_checks_mean_exactly_what_the_sql_checks_mean(tmp_path):
    """lib/checks.js (which enforces checks on MongoDB) against
    check_expr.evaluate (which agrees with the SQL CHECK — see its own
    differential test) on every expression x row, three-valued."""

    def resolve(name: str) -> str:
        if name not in CHECK_COLUMNS:
            raise check_expr.CheckExpressionError(name)
        return name

    cases = []
    for text in CHECK_EXPRESSIONS:
        ast = check_expr.bind_fields(check_expr.parse(text), resolve)
        check_expr.type_check(ast, CHECK_COLUMNS)
        ast = check_expr.canonicalize_literals(ast, CHECK_COLUMNS)
        for row in CHECK_ROWS:
            cases.append(
                {
                    "ast": ast,
                    "row": row,
                    "expected": check_expr.evaluate(ast, row, CHECK_COLUMNS),
                }
            )

    (tmp_path / "checks.js").write_text(dc._CHECKS_JS, encoding="utf-8")
    (tmp_path / "cases.json").write_text(
        json.dumps({"types": CHECK_COLUMNS, "cases": cases}), encoding="utf-8"
    )
    (tmp_path / "run.js").write_text(
        textwrap.dedent(
            """
            const { evaluateCheck } = require('./checks');
            const { types, cases } = require('./cases.json');
            // Dates arrive from MongoDB as Date objects (UTC), not strings.
            const asDoc = (row) => {
              const doc = {};
              for (const [k, v] of Object.entries(row)) {
                if (v !== null && (types[k] === 'date' || types[k] === 'datetime')) {
                  doc[k] = new Date(types[k] === 'date' ? `${v}T00:00:00Z` : `${v}Z`);
                } else doc[k] = v;
              }
              return doc;
            };
            console.log(JSON.stringify(cases.map((c) => evaluateCheck(c.ast, asDoc(c.row), types))));
            """
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [NODE, "run.js"], cwd=tmp_path, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    mismatches = [
        (CHECK_EXPRESSIONS[i // len(CHECK_ROWS)], c["row"], c["expected"], got[i])
        for i, c in enumerate(cases)
        if c["expected"] != got[i]
    ]
    assert mismatches == []
    assert {c["expected"] for c in cases} == {
        True,
        False,
        None,
    }  # all three outcomes exercised


# ─── The HTTP endpoint ───
def _user() -> User:
    return User(
        id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex}@example.com",
        username=uuid.uuid4().hex[:12],
        hashed_password="x",
        full_name="Test",
    )


@pytest.fixture
def api(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'codegen.db'}", poolclass=NullPool
    )
    sessions = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    owner = _user()
    project = Project(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        name="Shop",
        selected_stack={
            "frontend_framework": "react",
            "frontend_language": "javascript",
            "backend_framework": "fastapi",
            "backend_language": "python",
            "api_style": "rest",
        },
        architecture_data={
            "architecture": {"database_tables": SHOP, "api_endpoints": []},
            "user_approved": True,
        },
    )

    async def setup():
        # Tables only, no indexes — the same workaround as
        # test_architecture_blueprint.py (duplicate index names on SQLite).
        stashed = {t.name: list(t.indexes) for t in Base.metadata.tables.values()}
        for table in Base.metadata.tables.values():
            table.indexes.clear()
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            for table in Base.metadata.tables.values():
                table.indexes.update(stashed.get(table.name, []))
        async with sessions() as db:
            db.add_all([owner, project])
            await db.commit()

    asyncio.run(setup())

    async def override_get_db():
        async with sessions() as session:
            yield session

    async def set_tables(tables):
        async with sessions() as db:
            p = await db.get(Project, project.id)
            p.architecture_data = {
                **p.architecture_data,
                "architecture": {"database_tables": tables, "api_endpoints": []},
            }
            await db.commit()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: owner
    # Not `with TestClient(app)`: the lifespan would connect to the real
    # DATABASE_URL. This test brings its own database.
    yield SimpleNamespace(
        client=TestClient(app),
        id=project.id,
        set_tables=lambda t: asyncio.run(set_tables(t)),
    )
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def test_endpoint_writes_migrations_and_asks_before_losing_data(api):
    c = api.client
    r = c.post("/api/v1/codegen/generate-deterministic", json={"project_id": api.id})
    assert r.status_code == 200, r.text
    info = r.json()["migrations"]
    assert info["tool"] == "alembic" and [rev["id"] for rev in info["revisions"]] == [
        "0001"
    ]
    assert (
        "snapshot" not in info["revisions"][0]
        and "alembic upgrade head" in info["run_hint"]
    )

    dropped = copy.deepcopy(SHOP)
    dropped[3]["key_fields"].remove("stock_count")
    api.set_tables(dropped)
    r = c.post("/api/v1/codegen/generate-deterministic", json={"project_id": api.id})
    assert r.status_code == 409
    assert "drop column products.stock_count" in r.json()["detail"]
    assert "Confirm" in r.json()["detail"]
    # Nothing was saved by the refused run.
    assert (
        len(c.get(f"/api/v1/codegen/{api.id}").json()["migrations"]["revisions"]) == 1
    )

    r = c.post(
        "/api/v1/codegen/generate-deterministic",
        json={"project_id": api.id, "allow_destructive_migration": True},
    )
    assert r.status_code == 200, r.text
    revisions = c.get(f"/api/v1/codegen/{api.id}").json()["migrations"]["revisions"]
    assert [rev["id"] for rev in revisions] == ["0001", "0002"]
    assert revisions[1]["destructive"] == [
        "drop column products.stock_count (deletes its data)"
    ]

    blocked = copy.deepcopy(dropped)
    blocked[3]["key_fields"].append("brand")
    blocked[3]["field_specs"].append({"name": "brand", "nullable": False})
    api.set_tables(blocked)
    r = c.post("/api/v1/codegen/generate-deterministic", json={"project_id": api.id})
    assert r.status_code == 400 and "products.brand" in r.json()["detail"]

    broken = copy.deepcopy(SHOP)
    broken[2]["foreign_keys"][0]["references_table"] = "nowhere"
    api.set_tables(broken)
    r = c.post("/api/v1/codegen/generate-deterministic", json={"project_id": api.id})
    assert r.status_code == 400 and r.json()["detail"].startswith(
        "Fix these in Architecture before generating:"
    )


def test_resolved_schema_of_the_fixture_is_valid_for_both_backends():
    # Guards the fixture itself: every test above assumes a valid schema.
    for backend in ("fastapi", "express"):
        assert db_schema.validate_tables(SHOP, backend) == []
        assert db_schema.validate_tables(evolved(SHOP), backend) == []
