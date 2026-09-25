"""
The AI codegen adapters and the typed schema (codegen/backend/typed_schema.py).

Two guarantees:
  - A table that declares nothing — every project saved before typed
    columns existed — produces EXACTLY the output it always did. The golden
    file was captured from the adapters as they were before this change
    (git HEAD at the time) and must never need updating for a legacy table.
  - A table that declares types, keys, checks and indexes gets them in the
    deterministic schema pieces (Rails/Laravel migrations, Rust CREATE TABLE
    SQL, GraphQL types) and in every model prompt.
"""

import asyncio
import json
import pathlib

import pytest

from app.ai import db_schema
from app.ai.codegen.backend import (
    BACKEND_ADAPTERS,
    axum,
    laravel,
    rails,
    rust_common,
    spring_boot,
    typed_schema,
)
from app.ai.codegen.types import ModelCtx, WiringCtx

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "legacy_adapter_output.json"

LEGACY = [
    {
        "name": "Task",
        "purpose": "A to-do",
        "key_fields": [
            "title",
            "is_done",
            "due_date",
            "price",
            "item_count",
            "notes",
            "created_at",
        ],
    },
    # What the Architecture editor saves for a table with nothing typed:
    # every typed key present, all empty (seed rows change no column).
    {
        "name": "Order Item",
        "purpose": "A line",
        "key_fields": ["quantity", "unit_price", "active"],
        "field_specs": [],
        "foreign_keys": [],
        "checks": [],
        "indexes": [],
        "seed_rows": [{"quantity": 2}],
    },
]

TYPED = [
    {
        "name": "User",
        "purpose": "u",
        "key_fields": ["email", "rating", "order"],
        "field_specs": [
            {"name": "email", "type": "string", "unique": True, "nullable": False},
            {"name": "rating", "default": 4.5},
            {"name": "order", "type": "integer", "default": -3},
        ],
        "checks": [{"name": "rating range", "expression": "rating BETWEEN 0 AND 5"}],
    },
    {
        "name": "Post",
        "purpose": "p",
        "key_fields": ["author_id", "owner", "editor_id", "title", "published_at"],
        "field_specs": [
            {"name": "author_id", "nullable": False, "unique": True},
            {"name": "published_at", "default": "now"},
        ],
        "foreign_keys": [
            {"field": "author_id", "references_table": "User", "on_delete": "cascade"},
            {"field": "owner", "references_table": "User", "on_delete": "restrict"},
            {"field": "editor_id", "references_table": "User", "on_delete": "set_null"},
        ],
        "indexes": [{"fields": ["title", "owner"]}],
    },
]


def _wiring(tables) -> WiringCtx:
    return WiringCtx(
        project_name="Shop",
        model_files=[],
        routes_files=[],
        screen_files=[],
        endpoints=[],
        tables=tables,
    )


def test_legacy_tables_produce_exactly_the_output_they_always_did():
    w = _wiring(LEGACY)
    now = {
        "rails_migrations": [
            [f.path, f.content]
            for f in rails.entry_point_files(w)
            if "db/migrate" in f.path
        ],
        "laravel_migrations": [
            [f.path, f.content]
            for f in laravel.entry_point_files(w)
            if "database/migrations" in f.path
        ],
        "laravel_database_php": [
            f.content
            for f in laravel.manifest_files(w)
            if f.path.endswith("database.php")
        ][0],
        "rust_sql": [rust_common.build_create_table_sql(t) for t in LEGACY],
        "rails_type": rails._table_type_rb(LEGACY[0]),
        "laravel_graphql": laravel._graphql_schema(LEGACY),
        "spring_graphql": spring_boot._graphql_schema(LEGACY),
        "axum_main": axum._build_main_rs([], LEGACY),
    }
    assert json.loads(json.dumps(now)) == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_legacy_tables_never_enter_the_typed_path():
    assert typed_schema.resolve_if_typed(LEGACY) is None
    assert typed_schema.resolve_if_typed(TYPED) is not None


def test_rails_migration_honors_declared_types_keys_checks_and_indexes():
    files = {
        f.path: f.content
        for f in rails.entry_point_files(_wiring(TYPED))
        if "db/migrate" in f.path
    }
    users, posts = files.values()
    assert "t.string :email, limit: 255, null: false" in users
    assert 't.index [:email], name: "uq_users_email", unique: true' in users
    assert (
        "t.check_constraint 'rating BETWEEN 0 AND 5', name: \"ck_users_rating_range\""
        in users
    )
    assert (
        't.references :author, null: false, foreign_key: { to_table: :users, on_delete: :cascade, name: "fk_posts_author_id" }'
        in posts
    )
    assert (
        't.references :editor, foreign_key: { to_table: :users, on_delete: :nullify, name: "fk_posts_editor_id" }'
        in posts
    )
    # "owner" doesn't follow the <table>_id convention: a plain column plus a foreign key.
    assert (
        't.foreign_key :users, column: :owner, on_delete: :restrict, name: "fk_posts_owner"'
        in posts
    )
    assert 't.datetime :published_at, default: -> { "CURRENT_TIMESTAMP" }' in posts
    assert 't.index [:title, :owner], name: "ix_posts_title_owner"' in posts


def test_laravel_migration_honors_declarations_and_is_honest_about_checks():
    files = [
        f.content
        for f in laravel.entry_point_files(_wiring(TYPED))
        if "database/migrations" in f.path
    ]
    users, posts = files
    assert "$table->string('email', 255)->unique('uq_users_email');" in users
    assert "$table->integer('order')->nullable()->default(-3);" in users
    # No portable CHECK in Laravel's schema builder: said so, not faked.
    assert (
        'CHECK "rating range" (ck_users_rating_range): rating BETWEEN 0 AND 5' in users
    )
    assert "->check(" not in users
    assert (
        "$table->foreignId('author_id')->unique('uq_posts_author_id')->constrained('users', 'id', 'fk_posts_author_id')"
        "->cascadeOnDelete();" in posts
    )
    assert (
        "->constrained('users', 'id', 'fk_posts_editor_id')->nullOnDelete();" in posts
    )
    assert "$table->index(['title', 'owner'], 'ix_posts_title_owner');" in posts


def test_rust_sql_is_typed_and_constrained():
    users, posts = (rust_common.build_create_table_sql(t, TYPED) for t in TYPED)
    assert "email TEXT NOT NULL" in users and '"order" INTEGER DEFAULT -3' in users
    assert "CONSTRAINT ck_users_rating_range CHECK (rating BETWEEN 0 AND 5)" in users
    assert (
        "CONSTRAINT fk_posts_owner FOREIGN KEY (owner) REFERENCES users(id) ON DELETE RESTRICT"
        in posts
    )
    assert "published_at TEXT DEFAULT CURRENT_TIMESTAMP" in posts


def test_graphql_types_use_declared_nullability():
    schema = laravel._graphql_schema(TYPED)
    assert "createUser(email: String!, rating: Float, order: Int)" in schema
    assert (
        "createPost(author_id: Int!, owner: Int, editor_id: Int, title: String, published_at: DateTime)"
        in schema
    )
    assert "email: String!" in spring_boot._graphql_schema(TYPED)


@pytest.mark.parametrize(
    "key", sorted(k for k in BACKEND_ADAPTERS if k not in ("express",))
)
def test_every_model_prompt_describes_the_typed_schema(key, monkeypatch):
    """The AI model prompt carries the resolved schema — FK targets and
    ON DELETE rules included — instead of a bare field list."""
    adapter = BACKEND_ADAPTERS[key]
    module = __import__(adapter.generate_model.__module__, fromlist=["x"])
    prompts: list[str] = []

    async def capture(prompt, *args, **kwargs):
        prompts.append(prompt)
        return "// generated\n", None

    monkeypatch.setattr(module, "generate_text_validated", capture)
    ctx = ModelCtx(
        project_name="Blog",
        table=TYPED[1],
        requirements_text="",
        language=adapter.supported_languages[0],
        all_tables=TYPED,
    )
    asyncio.run(adapter.generate_model(ctx))
    text = "\n".join(prompts)
    assert db_schema.describe_table_for_prompt(TYPED[1], TYPED) in text
    assert "foreign key → users.id (ON DELETE SET NULL)" in text


def test_express_model_prompt_is_typed_too(monkeypatch):
    from app.ai.codegen.backend import express

    prompts: list[str] = []

    async def capture(prompt, *args, **kwargs):
        prompts.append(prompt)
        return "// generated\n", None

    monkeypatch.setattr(express, "generate_text_validated", capture)
    asyncio.run(
        express.generate_model(
            ModelCtx(
                project_name="Blog",
                table=TYPED[0],
                requirements_text="",
                language="javascript",
                all_tables=TYPED,
            )
        )
    )
    assert "- email: string (max 255), required (NOT NULL), unique" in prompts[0]
    assert "ck_users_rating_range: rating BETWEEN 0 AND 5" in prompts[0]
