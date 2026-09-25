"""
migrations_gen.py — the versioned-migration planner. The generated
migrations are run for real (Alembic on SQLite, end to end through the
generated app) in test_deterministic_migrations_e2e.py; this file pins the
planner's state machine and the shape of what it writes.
"""

import ast
import copy
import shutil
import subprocess

import pytest

from app.ai import db_schema, migrations_gen
from app.ai.codegen_shared import validate_generated_content

NOW = "2026-09-25T10:00:00+00:00"

TABLES = [
    {
        "name": "authors",
        "key_fields": ["name", "handle"],
        "field_specs": [{"name": "handle", "nullable": False, "unique": True}],
        "seed_rows": [{"name": "Tricky (value", "handle": "TODO ]x"}],
    },
    {
        "name": "books",
        "key_fields": ["title", "author_id", "published_on", "price"],
        "field_specs": [
            {"name": "published_on", "type": "date", "default": "today"},
            {"name": "price", "type": "decimal", "nullable": False, "default": "0"},
        ],
        "foreign_keys": [
            {
                "field": "author_id",
                "references_table": "authors",
                "on_delete": "set_null",
            }
        ],
        "checks": [{"name": "price ok", "expression": "price >= 0"}],
        "indexes": [{"fields": ["title", "author_id"], "unique": True}],
    },
]


def plan(tables, backend="fastapi", previous=None, allow=False):
    schema = db_schema.resolve_schema(tables, backend=backend)
    files = [f.model_dump() for f in previous.files] if previous else []
    return migrations_gen.plan_migrations(
        backend,
        schema,
        previous.state if previous else None,
        files,
        allow_destructive=allow,
        now_iso=NOW,
    )


def with_extra_column(tables):
    t = copy.deepcopy(tables)
    t[1]["key_fields"].append("pages")
    t[1]["field_specs"].append({"name": "pages", "type": "integer", "default": 1})
    return t


@pytest.mark.parametrize("backend", ["fastapi", "express"])
def test_first_plan_writes_revision_0001_and_the_support_files(backend):
    p = plan(TABLES, backend)
    paths = [f.path for f in p.files]
    if backend == "fastapi":
        assert paths == [
            "backend/alembic.ini",
            "backend/migrations/env.py",
            "backend/migrations/script.py.mako",
            "backend/app/core/migrate.py",
            "backend/migrations/versions/0001_initial.py",
        ]
    else:
        assert paths == [
            "backend/migrate-mongo-config.js",
            "backend/lib/migrate.js",
            "backend/migrations/0001-initial.js",
        ]
    assert p.new_revision["id"] == "0001" and p.state["backend"] == backend
    assert p.new_revision["summary"] == ["create table authors", "create table books"]


@pytest.mark.parametrize("backend", ["fastapi", "express"])
def test_state_machine(backend):
    first = plan(TABLES, backend)
    assert plan(TABLES, backend, first).new_revision is None  # nothing changed

    second = plan(with_extra_column(TABLES), backend, first)
    assert second.new_revision["id"] == "0002"
    assert second.new_revision["summary"] == ["add column books.pages (integer)"]
    assert second.new_revision["slug"] == "add_books_pages"

    dropped = with_extra_column(TABLES)
    dropped[1]["key_fields"].remove("title")
    dropped[1]["indexes"] = []
    with pytest.raises(migrations_gen.DestructiveMigrationError) as e:
        plan(dropped, backend, second)
    assert e.value.changes == ["drop column books.title (deletes its data)"]
    third = plan(dropped, backend, second, allow=True)
    assert third.new_revision["destructive"] == e.value.changes

    blocked = with_extra_column(TABLES)
    blocked[1]["key_fields"].append("isbn")
    blocked[1]["field_specs"].append({"name": "isbn", "nullable": False})
    with pytest.raises(migrations_gen.MigrationError, match="books.isbn"):
        plan(blocked, backend, second)


def test_an_existing_revision_is_carried_over_byte_for_byte():
    first = plan(TABLES)
    rev_path = first.new_revision["filename"]
    edited = copy.deepcopy(first)
    for f in edited.files:
        if f.path == rev_path:
            f.content += "# my own hand edit\n"
    second = plan(with_extra_column(TABLES), previous=edited)
    kept = next(f for f in second.files if f.path == rev_path)
    assert kept.content.endswith("# my own hand edit\n")

    # A revision missing from the previous files is rendered again from its
    # stored snapshots — identical to the original.
    lost = copy.deepcopy(first)
    lost.files = [f for f in lost.files if f.path != rev_path]
    again = plan(with_extra_column(TABLES), previous=lost)
    original = next(f for f in first.files if f.path == rev_path)
    assert (
        next(f for f in again.files if f.path == rev_path).content == original.content
    )


def test_history_restarts_on_a_backend_switch_or_an_unusable_state():
    first = plan(TABLES, "fastapi")
    assert plan(TABLES, "express", first).new_revision["id"] == "0001"
    broken = copy.deepcopy(first)
    broken.state["revisions"][0]["id"] = "7"
    assert plan(with_extra_column(TABLES), previous=broken).new_revision["id"] == "0001"
    with pytest.raises(ValueError, match="No migration support"):
        plan(TABLES, "django")


def test_public_info_hides_the_snapshots():
    info = migrations_gen.public_migration_info(plan(TABLES).state)
    assert info["tool"] == "alembic" and "alembic upgrade head" in info["run_hint"]
    assert set(info["revisions"][0]) == {
        "id",
        "filename",
        "summary",
        "destructive",
        "created_at",
    }
    assert migrations_gen.public_migration_info(None) is None
    assert migrations_gen.public_migration_info({"revisions": []}) is None


def test_every_file_passes_the_generated_file_check():
    for backend in ("fastapi", "express"):
        first = plan(TABLES, backend)
        for p in (first, plan(with_extra_column(TABLES), backend, first)):
            for f in p.files:
                assert validate_generated_content(f.language, f.content) is None, f.path
                if f.path.endswith(".py"):
                    ast.parse(f.content)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_mongo_migrations_are_valid_javascript(tmp_path):
    first = plan(TABLES, "express")
    for p in (first, plan(with_extra_column(TABLES), "express", first)):
        for f in p.files:
            target = tmp_path / f.path.replace("/", "_")
            target.write_text(f.content, encoding="utf-8")
            proc = subprocess.run(
                ["node", "--check", str(target)], capture_output=True, text=True
            )
            assert proc.returncode == 0, (f.path, proc.stderr)


def test_alembic_revision_content():
    text = plan(TABLES).files[-1].content
    assert 'revision = "0001"' in text and "down_revision = None" in text
    assert (
        'sa.ForeignKeyConstraint(["author_id"], ["authors.id"], name="fk_books_author_id", ondelete="SET NULL")'
        in text
    )
    assert (
        'sa.CheckConstraint("price >= 0", name="ck_books_price_ok")' in text
        or "sa.CheckConstraint('price >= 0'" in text
    )
    assert (
        'op.create_index("uq_books_title_author_id", "books", ["title", "author_id"], unique=True)'
        in text
    )
    assert 'server_default=sa.text("CURRENT_DATE")' in text
    assert 'op.drop_table("books")' in text.split("def downgrade")[1]


def test_mongo_revision_content():
    text = plan(TABLES, "express").files[-1].content
    assert 'await applyValidator(db, "books"' in text
    assert '"additionalProperties": false' in text
    # A unique index only covers documents that hold a value, like SQL's UNIQUE.
    assert '"partialFilterExpression": {"handle": {"$type": "string"}}' in text
    # User text with an unpaired bracket or "TODO" is escaped, not dropped.
    assert "Tricky \\u0028value" in text and "TOD\\u004f \\u005dx" in text


def test_shared_mongo_helpers_match_the_migration():
    ts = db_schema.snapshot(db_schema.resolve_schema(TABLES))["tables"]["books"]
    names = [options["name"] for _keys, options in migrations_gen.mongo_index_specs(ts)]
    assert names == ["uq_books_title_author_id"]
    assert (
        migrations_gen.js_value_literal("2024-01-02", "date")
        == 'new Date("2024-01-02")'
    )
    assert migrations_gen.js_value_literal("9.50", "decimal") == "9.5"
