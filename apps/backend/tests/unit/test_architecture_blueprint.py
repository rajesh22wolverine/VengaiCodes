"""Coverage for the Architecture phase's deterministic blueprint output:
Mermaid system/ERD diagrams built straight from the AI-generated
ArchitectureDesign object (no second AI call, so they can't drift from or
contradict what generate_architecture actually decided), the ADR
schema that wires the previously-unused Project.architecture_data.adrs
field to something a generator actually produces, and the typed-schema
layer on top of database_tables: structural validation (every issue
listed at once), canonical storage on save, AI-output sanitizing, the
typed ERD, and the GET/PUT/validate routes through the real app.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai import check_expr, db_schema
from app.api.v1 import architecture as architecture_module
from app.api.v1.architecture import (
    ADR,
    APIEndpoint,
    ArchitectureDesign,
    ArchitectureEditError,
    CheckConstraint,
    DatabaseTable,
    FieldSpec,
    ForeignKey,
    IndexSpec,
    TechStack,
    apply_architecture_edit,
    build_ai_architecture,
    build_architecture_prompt,
    build_erd,
    build_system_diagram,
    resolved_tables_payload,
    sanitize_ai_tables,
    schema_view,
)
from app.api.v1.auth import get_current_active_user
from app.core.database import Base, get_db
from app.main import app
from app.models.project import Project
from app.models.user import User


def _sample_architecture(**overrides) -> ArchitectureDesign:
    defaults = dict(
        architecture_summary="A simple CRUD app.",
        tech_stack=TechStack(
            frontend="React", backend="FastAPI", database="PostgreSQL", hosting="Render"
        ),
        database_tables=[
            DatabaseTable(
                name="products",
                purpose="Store products",
                key_fields=["id", "title", "price"],
            )
        ],
        api_endpoints=[
            APIEndpoint(method="GET", path="/products", purpose="List products")
        ],
        third_party_services=["Stripe (payments)"],
        adrs=[
            ADR(
                title="Use FastAPI",
                decision="Adopt FastAPI for the backend",
                rationale="Detected in the reverse-engineered source",
                alternatives_considered=["Django", "Flask"],
            )
        ],
    )
    defaults.update(overrides)
    return ArchitectureDesign(**defaults)


def test_build_system_diagram_includes_frontend_backend_database():
    diagram = build_system_diagram(_sample_architecture())
    assert diagram.startswith("graph TD")
    assert "React" in diagram
    assert "FastAPI" in diagram
    assert "PostgreSQL" in diagram
    assert "FE --> BE" in diagram
    assert "BE --> DB" in diagram


def test_build_system_diagram_adds_a_node_per_third_party_service():
    diagram = build_system_diagram(
        _sample_architecture(third_party_services=["Stripe", "SendGrid"])
    )
    assert "Stripe" in diagram
    assert "SendGrid" in diagram
    assert diagram.count("BE --> SVC") == 2


def test_build_system_diagram_strips_characters_that_break_mermaid_syntax():
    arch = _sample_architecture(
        tech_stack=TechStack(
            frontend='React ["weird"]',
            backend="FastAPI",
            database="Postgres",
            hosting="Render",
        )
    )
    diagram = build_system_diagram(arch)
    assert (
        "[" not in diagram.split("\n")[1].split("<br/>")[1]
    )  # the injected brackets were stripped from the label
    assert '"weird"' not in diagram


def test_build_erd_renders_one_block_per_table():
    erd = build_erd(
        [
            DatabaseTable(name="users", purpose="", key_fields=["id", "email"]),
            DatabaseTable(name="orders", purpose="", key_fields=["id", "user_id"]),
        ]
    )
    assert erd.startswith("erDiagram")
    assert '"users" {' in erd
    assert '"orders" {' in erd
    assert "email" in erd
    assert "user_id" in erd


def test_build_erd_sanitizes_table_names_into_valid_mermaid_identifiers():
    erd = build_erd(
        [DatabaseTable(name="user-profiles!", purpose="", key_fields=["id"])]
    )
    assert '  "user_profiles"["user-profiles!"] {' in erd


def test_adr_field_round_trips_through_model_dump():
    arch = _sample_architecture()
    dumped = arch.model_dump()
    assert dumped["adrs"][0]["title"] == "Use FastAPI"
    assert dumped["adrs"][0]["alternatives_considered"] == ["Django", "Flask"]


def test_architecture_design_defaults_adrs_to_empty_list_when_omitted():
    # Older stored architecture_data / an AI response that omits "adrs"
    # entirely must not break parsing.
    arch = ArchitectureDesign(
        architecture_summary="x",
        tech_stack=TechStack(
            frontend="React", backend="FastAPI", database="Postgres", hosting="Render"
        ),
        database_tables=[],
        api_endpoints=[],
        third_party_services=[],
    )
    assert arch.adrs == []


# ─── Standing policy: default to open-source/free third-party services,
# only name a paid one the user already said they have credentials for,
# and always attribute it as the user's own account, never VengaiCode's ───
def test_architecture_prompt_defaults_third_party_services_to_open_source():
    prompt = build_architecture_prompt("MyApp", {"overview": "A todo app"}, [])
    assert "open-source" in prompt
    assert "self-host" in prompt.lower()
    assert "user's own" in prompt.lower() or "users own" in prompt.lower()


def test_architecture_prompt_never_implies_vengaicode_pays_for_paid_services():
    prompt = build_architecture_prompt("MyApp", {"overview": "A todo app"}, [])
    assert "never implying vengaicode provisions or pays for it" in prompt.lower()


# ─── Direct architecture editing (PUT /architecture/{id}/edit) ───
def _sample_architecture_data(**overrides) -> dict:
    data = {
        "architecture": _sample_architecture().model_dump(),
        "user_approved": True,
        "approved_at": "2026-01-01T00:00:00+00:00",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "system_diagram": "graph TD\n  FE --> BE",
    }
    data.update(overrides)
    return data


def test_apply_architecture_edit_replaces_tables_and_endpoints():
    new_tables = [
        DatabaseTable(
            name="orders", purpose="Customer orders", key_fields=["id", "total"]
        )
    ]
    new_endpoints = [APIEndpoint(method="get", path="/orders", purpose="List orders")]

    new_data, new_uml = apply_architecture_edit(
        _sample_architecture_data(), {}, new_tables, new_endpoints
    )

    assert new_data["architecture"]["database_tables"][0]["name"] == "orders"
    assert new_data["architecture"]["api_endpoints"][0]["path"] == "/orders"
    assert '"orders" {' in new_uml["erd"]


def test_apply_architecture_edit_preserves_ai_authored_fields():
    original = _sample_architecture_data()
    new_data, _ = apply_architecture_edit(
        original,
        {},
        [DatabaseTable(name="orders", purpose="x", key_fields=["id"])],
        [],
    )
    assert (
        new_data["architecture"]["architecture_summary"]
        == original["architecture"]["architecture_summary"]
    )
    assert (
        new_data["architecture"]["tech_stack"] == original["architecture"]["tech_stack"]
    )
    assert (
        new_data["architecture"]["third_party_services"]
        == original["architecture"]["third_party_services"]
    )
    assert new_data["architecture"]["adrs"] == original["architecture"]["adrs"]


def test_apply_architecture_edit_unapproves_and_clears_approved_at():
    new_data, _ = apply_architecture_edit(
        _sample_architecture_data(),
        {},
        [DatabaseTable(name="orders", purpose="x", key_fields=["id"])],
        [],
    )
    assert new_data["user_approved"] is False
    assert "approved_at" not in new_data
    assert "edited_at" in new_data


def test_apply_architecture_edit_regenerates_diagrams_from_edited_data():
    new_data, new_uml = apply_architecture_edit(
        _sample_architecture_data(),
        {"erd": "erDiagram\n  OLD_TABLE {\n    string id\n  }"},
        [DatabaseTable(name="brand_new_table", purpose="x", key_fields=["id", "note"])],
        [],
    )
    assert '  "brand_new_tables"["brand_new_table"] {' in new_uml["erd"]
    assert "OLD_TABLE" not in new_uml["erd"]
    assert (
        "BRAND_NEW_TABLE" in new_data["system_diagram"]
        or "graph TD" in new_data["system_diagram"]
    )


def test_apply_architecture_edit_normalizes_endpoint_method_case_and_requires_leading_slash():
    new_data, _ = apply_architecture_edit(
        _sample_architecture_data(),
        {},
        [],
        [APIEndpoint(method="get", path="/things", purpose="x")],
    )
    assert new_data["architecture"]["api_endpoints"][0]["method"] == "GET"


def test_apply_architecture_edit_rejects_when_no_architecture_exists_yet():
    with pytest.raises(ArchitectureEditError, match="generate one first"):
        apply_architecture_edit(None, {}, [], [])
    with pytest.raises(ArchitectureEditError):
        apply_architecture_edit({}, {}, [], [])


def test_apply_architecture_edit_rejects_blank_table_name():
    with pytest.raises(ArchitectureEditError, match="needs a name"):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [DatabaseTable(name="  ", purpose="x", key_fields=["id"])],
            [],
        )


def test_apply_architecture_edit_rejects_duplicate_table_names():
    with pytest.raises(ArchitectureEditError, match="distinct"):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [
                DatabaseTable(name="Orders", purpose="x", key_fields=["id"]),
                DatabaseTable(name="orders", purpose="y", key_fields=["id"]),
            ],
            [],
        )


def test_apply_architecture_edit_rejects_duplicate_field_names_within_a_table():
    with pytest.raises(ArchitectureEditError, match="more than once"):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [DatabaseTable(name="orders", purpose="x", key_fields=["total", "Total"])],
            [],
        )


def test_apply_architecture_edit_rejects_blank_field_name():
    with pytest.raises(ArchitectureEditError, match="blank field name"):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [DatabaseTable(name="orders", purpose="x", key_fields=["total", "  "])],
            [],
        )


def test_apply_architecture_edit_rejects_invalid_http_method():
    with pytest.raises(ArchitectureEditError, match="not a valid HTTP method"):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [],
            [APIEndpoint(method="FETCH", path="/things", purpose="x")],
        )


def test_apply_architecture_edit_rejects_path_without_leading_slash():
    with pytest.raises(ArchitectureEditError, match='must start with "/"'):
        apply_architecture_edit(
            _sample_architecture_data(),
            {},
            [],
            [APIEndpoint(method="GET", path="things", purpose="x")],
        )


# ─── Typed ERD: real types, PK/FK/UK, relationship cardinality ───
def _erd_lines(tables) -> list[str]:
    return build_erd(tables).split("\n")


def _shop_tables() -> list[DatabaseTable]:
    return [
        DatabaseTable(
            name="customers",
            purpose="People who order",
            key_fields=["email", "name", "is_active"],
            field_specs=[
                FieldSpec(name="email", type="string", nullable=False, unique=True),
                FieldSpec(name="is_active", type="boolean", default=True),
            ],
        ),
        DatabaseTable(
            name="orders",
            purpose="Orders",
            key_fields=["customer_id", "coupon_id", "total", "placed_at"],
            field_specs=[
                FieldSpec(name="customer_id", nullable=False),
                FieldSpec(name="total", type="decimal", nullable=False, default=0),
                FieldSpec(name="placed_at", type="datetime", default="now"),
            ],
            foreign_keys=[
                ForeignKey(field="customer_id", references_table="customers"),
                ForeignKey(
                    field="coupon_id", references_table="coupons", on_delete="set_null"
                ),
            ],
            checks=[
                CheckConstraint(name="total_not_negative", expression="total >= 0")
            ],
        ),
        DatabaseTable(name="coupons", purpose="Discount codes", key_fields=["code"]),
        DatabaseTable(
            name="profiles",
            purpose="One per customer",
            key_fields=["customer_id", "bio"],
            field_specs=[FieldSpec(name="customer_id", nullable=False, unique=True)],
            foreign_keys=[
                ForeignKey(field="customer_id", references_table="customers")
            ],
        ),
    ]


def test_build_erd_shows_the_implicit_primary_key_and_real_types():
    lines = _erd_lines(_shop_tables())
    assert lines[:2] == ["erDiagram", '  "customers" {']
    assert lines[2] == "    integer id PK"
    assert '    string email UK "required"' in lines
    assert "    string name" in lines  # undeclared: inferred, no comment
    assert '    boolean is_active "default true"' in lines
    assert '    decimal total "required, default 0.00"' in lines
    assert '    datetime placed_at "default now"' in lines
    assert "    text bio" in lines  # "bio" infers text, as codegen does


def test_build_erd_marks_foreign_keys_with_their_target_and_rule():
    lines = _erd_lines(_shop_tables())
    assert (
        '    integer customer_id FK "required, → customers.id (on delete cascade)"'
        in lines
    )
    assert '    integer coupon_id FK "→ coupons.id (on delete set null)"' in lines
    assert (
        '    integer customer_id FK, UK "required, → customers.id (on delete cascade)"'
        in lines
    )


def test_build_erd_draws_one_relationship_per_foreign_key_with_cardinality():
    erd = build_erd(_shop_tables())
    # required FK: every order has exactly one customer
    assert '  "customers" ||--o{ "orders" : "customer_id"' in erd
    # optional FK: an order has zero or one coupon
    assert '  "coupons" |o--o{ "orders" : "coupon_id"' in erd
    # unique FK: one-to-one
    assert '  "customers" ||--o| "profiles" : "customer_id"' in erd
    assert erd.count("--") == 3


def test_build_erd_treats_a_single_column_unique_index_as_one_to_one():
    erd = build_erd(
        [
            DatabaseTable(name="users", purpose="", key_fields=["email"]),
            DatabaseTable(
                name="avatars",
                purpose="",
                key_fields=["user_id"],
                foreign_keys=[ForeignKey(field="user_id", references_table="users")],
                indexes=[IndexSpec(fields=["user_id"], unique=True)],
            ),
        ]
    )
    assert '    integer user_id FK, UK "→ users.id (on delete cascade)"' in erd
    assert '  "users" |o--o| "avatars" : "user_id"' in erd


def test_build_erd_supports_self_references():
    erd = build_erd(
        [
            DatabaseTable(
                name="employees",
                purpose="Staff",
                key_fields=["name", "manager_id"],
                foreign_keys=[
                    ForeignKey(
                        field="manager_id",
                        references_table="employees",
                        on_delete="set_null",
                    )
                ],
            )
        ]
    )
    assert '  "employees" |o--o{ "employees" : "manager_id"' in erd
    assert '    integer manager_id FK "→ employees.id (on delete set null)"' in erd


def test_build_erd_accepts_plain_dicts_including_legacy_tables():
    erd = build_erd(
        [
            {"name": "notes", "key_fields": ["id", "title", "created_at"]},
            {"name": "tags"},  # no key_fields at all
        ]
    )
    assert '  "notes" {' in erd
    assert erd.count("integer id PK") == 2  # a listed "id" isn't shown twice
    assert "    string title" in erd
    assert '    datetime created_at "set automatically"' in erd
    assert '  "tags" {' in erd


def test_build_erd_shows_every_column_without_a_cap():
    fields = [f"field_{i}" for i in range(20)]
    erd = build_erd([DatabaseTable(name="wide", purpose="", key_fields=fields)])
    for field in fields:
        assert f"    string {field}" in erd


def test_build_erd_comments_stay_mermaid_safe():
    erd = build_erd(
        [
            DatabaseTable(
                name="posts",
                purpose="",
                key_fields=["title"],
                field_specs=[FieldSpec(name="title", default='say "hi"\nthere')],
            )
        ]
    )
    line = next(x for x in erd.split("\n") if " title " in x)
    assert line == "    string title \"default 'say hi there'\""
    assert line.count('"') == 2


def test_build_erd_skips_only_what_it_cannot_resolve():
    erd = build_erd(
        [
            DatabaseTable(name="9lives", purpose="", key_fields=["x"]),
            DatabaseTable(name="cats", purpose="", key_fields=["name", "  "]),
            DatabaseTable(
                name="toys",
                purpose="",
                key_fields=["cat_id"],
                foreign_keys=[ForeignKey(field="cat_id", references_table="dogs")],
            ),
        ]
    )
    assert "9LIVES" not in erd
    assert '  "cats" {' in erd and "    string name" in erd
    # The dangling foreign key is dropped; the field itself is kept.
    assert "    string cat_id" in erd
    assert "--" not in erd


# ─── Pydantic models tolerate what an AI leaves out ───
def test_table_models_treat_omitted_keys_and_nulls_as_defaults():
    table = DatabaseTable(
        **{
            "name": "orders",
            "purpose": None,
            "key_fields": ["total"],
            "field_specs": [{"name": "total", "nullable": None, "unique": None}],
            "foreign_keys": [{"field": "customer_id"}],
            "checks": [{}],
            "indexes": [{"fields": "total"}, {"unique": True}],
            "seed_rows": None,
        }
    )
    assert table.purpose == ""
    spec = table.field_specs[0]
    assert (spec.type, spec.nullable, spec.default, spec.unique) == (
        None,
        True,
        None,
        False,
    )
    fk = table.foreign_keys[0]
    assert (fk.references_table, fk.references_field, fk.on_delete) == (
        "",
        "id",
        "cascade",
    )
    assert (table.checks[0].name, table.checks[0].expression) == ("", "")
    assert table.indexes[0].fields == ["total"]
    assert table.indexes[1].fields == []
    assert table.seed_rows == []


def test_field_spec_default_keeps_any_json_value():
    assert FieldSpec(name="a", default=0).default == 0
    assert FieldSpec(name="a", default=False).default is False
    assert FieldSpec(name="a", default={"k": [1]}).default == {"k": [1]}


# ─── Structural validation on edit: every issue listed at once ───
def test_apply_architecture_edit_lists_every_issue_in_one_message():
    tables = [
        DatabaseTable(
            name="orders",
            purpose="x",
            key_fields=["total", "status"],
            field_specs=[FieldSpec(name="total", type="money")],
            foreign_keys=[ForeignKey(field="status", references_table="nowhere")],
            checks=[CheckConstraint(name="c", expression="totl > 0")],
            indexes=[IndexSpec(fields=["missing"])],
        )
    ]
    with pytest.raises(ArchitectureEditError) as exc:
        apply_architecture_edit(_sample_architecture_data(), {}, tables, [])
    message = str(exc.value)
    assert message.startswith("Fix these before saving:\n• ")
    assert message.count("\n• ") == 4
    assert '"money" is not a valid field type' in message
    assert 'references "nowhere", which doesn\'t exist' in message
    assert '"totl" isn\'t a field of "orders"' in message
    assert 'index on "missing"' in message


def test_apply_architecture_edit_never_truncates_the_issue_list():
    tables = [
        DatabaseTable(name=f"t{i}", purpose="x", key_fields=["a", "A"])
        for i in range(15)
    ]
    with pytest.raises(ArchitectureEditError) as exc:
        apply_architecture_edit(_sample_architecture_data(), {}, tables, [])
    message = str(exc.value)
    assert message.count("\n• ") == 15
    assert "more." not in message


def test_apply_architecture_edit_rejects_set_null_on_a_required_field():
    tables = [
        DatabaseTable(name="customers", purpose="x", key_fields=["email"]),
        DatabaseTable(
            name="orders",
            purpose="x",
            key_fields=["customer_id"],
            field_specs=[FieldSpec(name="customer_id", nullable=False)],
            foreign_keys=[
                ForeignKey(
                    field="customer_id",
                    references_table="customers",
                    on_delete="set_null",
                )
            ],
        ),
    ]
    with pytest.raises(ArchitectureEditError, match="SET NULL needs"):
        apply_architecture_edit(_sample_architecture_data(), {}, tables, [])


def test_apply_architecture_edit_rejects_a_check_outside_the_grammar():
    tables = [
        DatabaseTable(
            name="products",
            purpose="x",
            key_fields=["price"],
            checks=[CheckConstraint(name="c", expression="price >= 0); DROP TABLE x")],
        )
    ]
    with pytest.raises(ArchitectureEditError, match='Check "c" on "products"'):
        apply_architecture_edit(_sample_architecture_data(), {}, tables, [])


def test_apply_architecture_edit_reserved_words_depend_on_the_backend():
    tables = [DatabaseTable(name="lessons", purpose="x", key_fields=["class", "save"])]

    with pytest.raises(ArchitectureEditError) as python_exc:
        apply_architecture_edit(
            _sample_architecture_data(), {}, tables, [], backend="fastapi"
        )
    assert '"class" is a reserved word in Python' in str(python_exc.value)
    assert '"save"' not in str(python_exc.value)

    with pytest.raises(ArchitectureEditError) as mongoose_exc:
        apply_architecture_edit(
            _sample_architecture_data(), {}, tables, [], backend="express"
        )
    assert '"save" is a reserved name in Mongoose' in str(mongoose_exc.value)
    assert '"class"' not in str(mongoose_exc.value)

    # No backend known: nothing is reserved.
    new_data, _ = apply_architecture_edit(_sample_architecture_data(), {}, tables, [])
    assert new_data["architecture"]["database_tables"][0]["key_fields"] == [
        "class",
        "save",
    ]


# ─── Canonical storage on save ───
def _messy_but_valid_tables() -> list[DatabaseTable]:
    return [
        DatabaseTable(
            name=" customers ",
            purpose=" People ",
            key_fields=[" email ", "notes"],
            field_specs=[
                FieldSpec(name="email", type="STRING", nullable=False, unique=True),
                FieldSpec(name="notes"),  # says nothing beyond the defaults
            ],
        ),
        DatabaseTable(
            name="orders",
            purpose="x",
            key_fields=["customer_id", "total", "status", "placed_on"],
            field_specs=[
                FieldSpec(name="total", type="Decimal", default=5),
                FieldSpec(name="placed_on", type="date", default="TODAY"),
            ],
            foreign_keys=[
                ForeignKey(
                    field="customer_id",
                    references_table="Customers",
                    on_delete="SET NULL",
                )
            ],
            checks=[
                CheckConstraint(
                    name=" valid_status ", expression=" status IN ('new', 'paid') "
                )
            ],
            indexes=[IndexSpec(fields=["status", "placed_on"], unique=True)],
        ),
        DatabaseTable(
            name="statuses",
            purpose="Lookup",
            key_fields=["label", "sort_order"],
            field_specs=[
                FieldSpec(name="label", nullable=False, unique=True),
                FieldSpec(name="sort_order", type="integer"),
            ],
            seed_rows=[
                {"label": "New", "sort_order": "1"},
                {"Label": "Paid", "sort_order": 2.0},
            ],
        ),
    ]


def test_apply_architecture_edit_stores_canonical_tables():
    new_data, new_uml = apply_architecture_edit(
        _sample_architecture_data(), {}, _messy_but_valid_tables(), []
    )
    customers, orders, statuses = new_data["architecture"]["database_tables"]

    assert customers["name"] == "customers"
    assert customers["purpose"] == "People"
    assert customers["key_fields"] == ["email", "notes"]
    assert customers["field_specs"] == [
        {
            "name": "email",
            "type": "string",
            "nullable": False,
            "default": None,
            "unique": True,
        }
    ]
    assert orders["field_specs"] == [
        {
            "name": "total",
            "type": "decimal",
            "nullable": True,
            "default": "5.00",
            "unique": False,
        },
        {
            "name": "placed_on",
            "type": "date",
            "nullable": True,
            "default": "today",
            "unique": False,
        },
    ]
    assert orders["foreign_keys"] == [
        {
            "field": "customer_id",
            "references_table": "customers",
            "references_field": "id",
            "on_delete": "set_null",
        }
    ]
    assert orders["checks"] == [
        {"name": "valid_status", "expression": "status IN ('new', 'paid')"}
    ]
    assert orders["indexes"] == [{"fields": ["status", "placed_on"], "unique": True}]
    assert statuses["seed_rows"] == [
        {"label": "New", "sort_order": 1},
        {"label": "Paid", "sort_order": 2},
    ]
    assert '  "customers" |o--o{ "orders" : "customer_id"' in new_uml["erd"]


def test_canonical_tables_revalidate_cleanly_and_are_stable():
    new_data, _ = apply_architecture_edit(
        _sample_architecture_data(), {}, _messy_but_valid_tables(), []
    )
    stored = new_data["architecture"]["database_tables"]
    assert db_schema.validate_tables(stored, "fastapi") == []
    assert db_schema.normalize_tables(stored, "fastapi") == stored
    # Saving the stored form again changes nothing.
    again, _ = apply_architecture_edit(
        new_data, {}, [DatabaseTable(**t) for t in stored], []
    )
    assert again["architecture"]["database_tables"] == stored


# ─── Sanitizing the AI's proposal before it's stored ───
def test_sanitize_ai_tables_drops_invalid_details_with_notes_and_normalizes():
    raw = [
        {
            "name": "customers",
            "purpose": "People",
            "key_fields": ["email"],
            "field_specs": [
                {"name": "email", "type": "String", "nullable": None, "unique": True}
            ],
        },
        {
            "name": "orders",
            "purpose": "Orders",
            "key_fields": ["total"],  # the AI forgot the FK field
            "field_specs": [{"name": "total", "type": "decimal", "default": 5}],
            "foreign_keys": [{"field": "customer_id", "references_table": "customers"}],
            "checks": [
                {"name": "positive", "expression": "total >= 0"},
                {"name": "bogus", "expression": "totl > 0"},
                {"expression": "total < 100"},
            ],
            "indexes": [{"fields": "total"}],
            "seed_rows": None,
        },
    ]
    tables, notes = sanitize_ai_tables(raw, "fastapi")
    customers, orders = tables

    assert db_schema.validate_tables(tables, "fastapi") == []
    assert customers["field_specs"][0]["type"] == "string"
    assert customers["field_specs"][0]["nullable"] is True
    assert orders["key_fields"] == ["total", "customer_id"]
    assert orders["field_specs"][0]["default"] == "5.00"
    assert [c["name"] for c in orders["checks"]] == ["positive"]
    assert orders["indexes"] == [{"fields": ["total"], "unique": False}]
    assert any('Added the field "customer_id"' in n for n in notes)
    assert any("Dropped a check constraint" in n and "totl" in n for n in notes)
    assert any("blank name or expression" in n for n in notes)


def test_sanitize_ai_tables_keeps_name_problems_for_the_user_to_fix():
    raw = [{"name": "lessons", "purpose": "x", "key_fields": ["class", "title"]}]

    tables, notes = sanitize_ai_tables(raw, "fastapi")
    assert tables[0]["key_fields"] == ["class", "title"]  # not renamed, not dropped
    assert notes == []
    issues = db_schema.validate_tables(tables, "fastapi")
    assert len(issues) == 1 and "reserved word" in issues[0].message

    # The same design is fully valid for a backend where "class" is fine.
    tables, _ = sanitize_ai_tables(raw, "express")
    assert db_schema.validate_tables(tables, "express") == []


def test_sanitize_ai_tables_handles_missing_and_malformed_input():
    assert sanitize_ai_tables(None, "fastapi") == ([], [])
    with pytest.raises(ValueError):
        sanitize_ai_tables({"name": "not a list"}, "fastapi")
    with pytest.raises(ValueError):
        sanitize_ai_tables([{"name": "x", "key_fields": "a, b"}], "fastapi")
    with pytest.raises(ValueError):
        sanitize_ai_tables(["just a string"], "fastapi")


def _ai_response(**overrides) -> dict:
    data = {
        "architecture_summary": "A shop.",
        "tech_stack": {
            "frontend": "React",
            "backend": "FastAPI",
            "database": "SQLite",
            "hosting": "Self-hosted",
        },
        "database_tables": [
            {
                "name": "products",
                "purpose": "Things for sale",
                "key_fields": ["title", "price"],
                "field_specs": [{"name": "price", "type": "decimal"}],
                "foreign_keys": [{"field": "price"}],  # no references_table
                "checks": [{"name": "price_ok", "expression": "price >= 0"}],
            }
        ],
        "api_endpoints": [{"method": "GET", "path": "/products", "purpose": "List"}],
        "third_party_services": [],
    }
    data.update(overrides)
    return data


def test_build_ai_architecture_sanitizes_tables_before_building_the_design():
    architecture, notes = build_ai_architecture(_ai_response(), "fastapi")
    (products,) = architecture.database_tables
    assert products.foreign_keys == []
    assert [c.name for c in products.checks] == ["price_ok"]
    assert products.field_specs[0].type == "decimal"
    assert any("doesn't exist" in n for n in notes)


def test_build_ai_architecture_tolerates_omitted_tables_and_rejects_non_objects():
    without_tables = {k: v for k, v in _ai_response().items() if k != "database_tables"}
    architecture, notes = build_ai_architecture(without_tables, None)
    assert architecture.database_tables == [] and notes == []
    with pytest.raises(TypeError):
        build_ai_architecture(["not", "an", "object"], None)


# ─── Resolved tables / schema view ───
def test_resolved_tables_payload_shape():
    schema = db_schema.resolve_schema(
        [t.model_dump() for t in _shop_tables()], "fastapi"
    )
    payload = resolved_tables_payload(schema)
    assert [t["name"] for t in payload] == [
        "customers",
        "orders",
        "coupons",
        "profiles",
    ]
    orders = payload[1]
    assert set(orders) == {
        "name",
        "sql_name",
        "columns",
        "checks",
        "indexes",
        "seed_row_count",
    }
    assert orders["sql_name"] == "orders"
    assert orders["columns"][0] == {
        "name": "customer_id",
        "column": "customer_id",
        "type": "integer",
        "declared": False,
        "nullable": False,
        "unique": False,
        "default": None,
        "fk": {
            "table": "customers",
            "table_sql": "customers",
            "column": "id",
            "on_delete": "cascade",
        },
    }
    total = next(c for c in orders["columns"] if c["column"] == "total")
    assert (total["type"], total["declared"], total["default"]) == (
        "decimal",
        True,
        "0.00",
    )
    placed_at = next(c for c in orders["columns"] if c["column"] == "placed_at")
    assert placed_at["default"] == "now"
    assert orders["checks"] == [{"name": "total_not_negative", "sql": "total >= 0"}]
    assert orders["indexes"] == []
    assert orders["seed_row_count"] == 0
    statuses = resolved_tables_payload(
        db_schema.resolve_schema(
            [t.model_dump() for t in _messy_but_valid_tables()], "fastapi"
        )
    )[2]
    assert statuses["seed_row_count"] == 2
    assert statuses["indexes"] == []


def test_schema_view_reports_a_failed_analysis_as_an_issue(monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(db_schema, "validate_tables", explode)
    view = schema_view([{"name": "x", "key_fields": ["a"]}], "fastapi")
    assert view["resolved_tables"] == [] and view["erd"] is None
    assert len(view["schema_issues"]) == 1
    assert view["schema_issues"][0]["table"] is None


# ─── Prompt: the richer schema is asked for in a form we can use ───
def test_architecture_prompt_describes_the_typed_schema_contract():
    prompt = build_architecture_prompt("MyApp", {"overview": "A shop"}, [])
    for field_type in db_schema.FIELD_TYPES:
        assert f'"{field_type}"' in prompt
    assert 'omit "type" (or set it to null)' in prompt
    assert check_expr.GRAMMAR_HELP in prompt
    assert "status IN ('draft', 'published', 'archived')" in prompt
    assert "rating BETWEEN 1 AND 5" in prompt
    assert 'EXACT "name" of another table' in prompt
    assert '"set_null" is only\nallowed on a field that is nullable' in prompt
    assert "lookup/reference data" in prompt


def test_architecture_prompt_examples_are_valid_check_expressions():
    prompt = build_architecture_prompt("MyApp", {"overview": "A shop"}, [])
    block = prompt.split("Valid examples:\n", 1)[1].split("\n\n", 1)[0]
    examples = [line.strip() for line in block.split("\n") if line.strip()]
    assert len(examples) == 4
    for example in examples:
        check_expr.parse(example)  # raises if the prompt teaches bad syntax


# ─── Routes through the real app, backed by a real SQLite database ───
_EXPRESS_STACK = {
    "frontend_framework": "html_css_js",
    "frontend_language": "javascript",
    "backend_framework": "express",
    "backend_language": "javascript",
    "api_style": "rest",
}


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
        f"sqlite+aiosqlite:///{tmp_path / 'architecture.db'}", poolclass=NullPool
    )
    sessions = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    owner, stranger = _user(), _user()
    legacy_architecture = _sample_architecture(
        database_tables=[
            DatabaseTable(name="lessons", purpose="x", key_fields=["class", "title"])
        ]
    ).model_dump()
    projects = {
        # No selected_stack: codegen falls back to FastAPI for this one.
        "fastapi": Project(
            id=str(uuid.uuid4()),
            user_id=owner.id,
            name="Python App",
            architecture_data={
                "architecture": legacy_architecture,
                "user_approved": True,
                "schema_notes": ["Dropped a check constraint: example"],
            },
            uml_diagrams={"erd": "erDiagram\n  STALE {\n    string title\n  }"},
        ),
        "express": Project(
            id=str(uuid.uuid4()),
            user_id=owner.id,
            name="Node App",
            selected_stack=_EXPRESS_STACK,
            architecture_data={"architecture": legacy_architecture},
        ),
        "bare": Project(id=str(uuid.uuid4()), user_id=owner.id, name="No Arch Yet"),
        "strangers": Project(id=str(uuid.uuid4()), user_id=stranger.id, name="Theirs"),
    }

    async def setup():
        # Tables only, no indexes — several app models declare the same
        # index twice, which SQLite rejects (same workaround as
        # tests/integration/conftest.py and app/main.py's init_db()).
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
            db.add_all([owner, stranger, *projects.values()])
            await db.commit()

    asyncio.run(setup())

    async def override_get_db():
        async with sessions() as session:
            yield session

    async def load(project_id: str) -> Project:
        async with sessions() as db:
            return await db.get(Project, project_id)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: owner
    # Deliberately NOT `with TestClient(app)`: the context-manager form
    # runs the app's lifespan, whose init_db() connects to the real
    # DATABASE_URL (a Postgres that doesn't exist in Backend CI). These
    # tests bring their own database and need nothing from startup.
    yield SimpleNamespace(
        client=TestClient(app),
        ids={key: p.id for key, p in projects.items()},
        load=lambda project_id: asyncio.run(load(project_id)),
    )
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def _body(tables: list[DatabaseTable]) -> dict:
    return {
        "database_tables": [t.model_dump() for t in tables],
        "api_endpoints": [{"method": "GET", "path": "/orders", "purpose": "List"}],
    }


def test_validate_endpoint_returns_erd_and_resolved_tables_for_a_valid_schema(api):
    # "bare" has no architecture yet — validating doesn't need one.
    response = api.client.post(
        f"/api/v1/architecture/{api.ids['bare']}/validate", json=_body(_shop_tables())
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["valid"] is True
    assert body["issues"] == []
    assert '  "customers" ||--o{ "orders" : "customer_id"' in body["erd"]
    assert [t["name"] for t in body["resolved_tables"]] == [
        "customers",
        "orders",
        "coupons",
        "profiles",
    ]


def test_validate_endpoint_lists_every_issue_without_failing_the_request(api):
    tables = [
        DatabaseTable(
            name="orders",
            purpose="x",
            key_fields=["total", "total"],
            checks=[CheckConstraint(name="c", expression="nope > 1")],
        ),
        DatabaseTable(name="", purpose="x", key_fields=[]),
    ]
    response = api.client.post(
        f"/api/v1/architecture/{api.ids['bare']}/validate", json=_body(tables)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert {(i["table"], i["kind"]) for i in body["issues"]} == {
        ("orders", "field"),
        ("orders", "check"),
        (None, "table"),
    }
    assert all(set(i) == {"table", "kind", "index", "message"} for i in body["issues"])
    # The valid part is still resolved and drawn.
    assert body["resolved_tables"][0]["name"] == "orders"
    assert '  "orders" {' in body["erd"]


def test_validate_endpoint_tolerates_a_half_typed_table(api):
    response = api.client.post(
        f"/api/v1/architecture/{api.ids['bare']}/validate",
        json={"database_tables": [{"key_fields": ["a"]}]},
    )
    assert response.status_code == 200
    assert response.json()["issues"][0]["message"] == "Every table needs a name."


def test_validate_endpoint_checks_reserved_words_for_the_projects_own_backend(api):
    tables = [DatabaseTable(name="lessons", purpose="x", key_fields=["class", "save"])]

    python = api.client.post(
        f"/api/v1/architecture/{api.ids['fastapi']}/validate", json=_body(tables)
    ).json()
    assert [i["message"].split('"')[1] for i in python["issues"]] == ["class"]

    node = api.client.post(
        f"/api/v1/architecture/{api.ids['express']}/validate", json=_body(tables)
    ).json()
    assert [i["message"].split('"')[1] for i in node["issues"]] == ["save"]


def test_validate_endpoint_404s_for_someone_elses_project(api):
    response = api.client.post(
        f"/api/v1/architecture/{api.ids['strangers']}/validate",
        json=_body(_shop_tables()),
    )
    assert response.status_code == 404


def test_validate_endpoint_saves_nothing(api):
    response = api.client.post(
        f"/api/v1/architecture/{api.ids['fastapi']}/validate",
        json=_body(_shop_tables()),
    )
    assert response.status_code == 200
    project = api.load(api.ids["fastapi"])
    tables = project.architecture_data["architecture"]["database_tables"]
    assert [t["name"] for t in tables] == ["lessons"]
    assert project.architecture_data["user_approved"] is True


def test_get_architecture_adds_live_schema_analysis(api):
    response = api.client.get(f"/api/v1/architecture/{api.ids['fastapi']}")
    assert response.status_code == 200
    body = response.json()
    # Legacy data with a Python-reserved field: reported, not hidden.
    assert len(body["schema_issues"]) == 1
    assert body["schema_issues"][0]["kind"] == "field"
    assert "reserved word" in body["schema_issues"][0]["message"]
    assert body["schema_notes"] == ["Dropped a check constraint: example"]
    # The ERD is rebuilt from the saved tables, not the stale stored copy.
    assert "STALE" not in body["erd"]
    assert '  "lessons" {\n    integer id PK' in body["erd"]
    assert body["resolved_tables"][0]["name"] == "lessons"
    # The express project has the same tables, and "class" is fine there.
    express = api.client.get(f"/api/v1/architecture/{api.ids['express']}").json()
    assert express["schema_issues"] == []
    assert express["schema_notes"] == []


def test_edit_endpoint_refuses_with_every_issue_listed(api):
    tables = [
        DatabaseTable(
            name="orders",
            purpose="x",
            key_fields=["total"],
            field_specs=[FieldSpec(name="total", type="money")],
            indexes=[IndexSpec(fields=["nope"])],
        )
    ]
    response = api.client.put(
        f"/api/v1/architecture/{api.ids['fastapi']}/edit", json=_body(tables)
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith("Fix these before saving:\n• ")
    assert detail.count("\n• ") == 2


def test_edit_endpoint_saves_canonical_tables_and_returns_resolved_ones(api):
    response = api.client.put(
        f"/api/v1/architecture/{api.ids['fastapi']}/edit",
        json=_body(_messy_but_valid_tables()),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["schema_issues"] == []
    assert body["schema_notes"] == ["Dropped a check constraint: example"]
    assert [t["name"] for t in body["resolved_tables"]] == [
        "customers",
        "orders",
        "statuses",
    ]
    assert body["resolved_tables"][2]["seed_row_count"] == 2
    assert '  "customers" |o--o{ "orders" : "customer_id"' in body["erd"]

    saved = api.load(api.ids["fastapi"])
    stored = saved.architecture_data["architecture"]["database_tables"]
    assert stored[0]["name"] == "customers"  # trimmed
    assert stored[1]["foreign_keys"][0]["on_delete"] == "set_null"
    assert saved.architecture_data["user_approved"] is False
    assert saved.uml_diagrams["erd"] == body["erd"]


def test_edit_endpoint_uses_the_projects_backend(api):
    tables = [DatabaseTable(name="lessons", purpose="x", key_fields=["save"])]
    response = api.client.put(
        f"/api/v1/architecture/{api.ids['express']}/edit", json=_body(tables)
    )
    assert response.status_code == 400
    assert "Mongoose" in response.json()["detail"]
    # ...while the Python project accepts the very same name.
    response = api.client.put(
        f"/api/v1/architecture/{api.ids['fastapi']}/edit", json=_body(tables)
    )
    assert response.status_code == 200


def test_project_backend_never_fails_a_request(monkeypatch):
    def explode(_project):
        raise RuntimeError("stack matrix unavailable")

    monkeypatch.setattr(architecture_module, "get_project_stack", explode)
    assert architecture_module._project_backend(SimpleNamespace(id="p")) is None
