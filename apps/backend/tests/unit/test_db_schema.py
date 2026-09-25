"""
db_schema.py — the single typed-schema source every consumer reads:
Architecture validation/ERD, the deterministic generator's models, the
migrations, and the AI adapters' prompts. The generated apps that are
built from it are exercised for real in test_deterministic_migrations_e2e.py;
this file pins the rules themselves.
"""

import copy

import pytest
import sqlalchemy as sa

from app.ai import db_schema


def issues(tables, backend=None) -> list[str]:
    return [i.message for i in db_schema.validate_tables(tables, backend)]


def one_issue(tables, fragment, backend=None, kind=None):
    found = db_schema.validate_tables(tables, backend)
    matches = [i for i in found if fragment in i.message]
    assert matches, f"no issue containing {fragment!r} in {[i.message for i in found]}"
    if kind:
        assert matches[0].kind == kind
    return matches[0]


def table(name="items", fields=("title",), **extra) -> dict:
    return {"name": name, "purpose": "", "key_fields": list(fields), **extra}


# ─── Table and field names ───
@pytest.mark.parametrize(
    "tables,fragment",
    [
        ([table(name="")], "Every table needs a name"),
        ([table(name="3d things")], "has to start with a letter"),
        ([table(name="x" * 60)], "too long"),
        (
            [table(name="Order Items"), table(name="order_items")],
            'both resolve to "order_items"',
        ),
        (
            [table(name="box"), table(name="boxs")],
            'would both be stored in the table "boxs"',
        ),
        ([table(name="a1b"), table(name="a 1b")], 'would both become the model "A1b"'),
        ([table(fields=("title", ""))], "blank field name"),
        ([table(fields=("title", "Title"))], "more than once"),
        ([table(fields=("id", "ID"))], "more than once"),
        ([table(fields=("2nd",))], "has to start with a letter"),
    ],
)
def test_name_rules(tables, fragment):
    one_issue(tables, fragment)


@pytest.mark.parametrize(
    "backend,field,refused",
    [
        ("fastapi", "class", True),
        ("django", "metadata", True),
        ("fastapi", "sa", True),  # the generated models' name for sqlalchemy
        ("fastapi", "model_dump", True),  # a real Pydantic BaseModel method
        (
            "fastapi",
            "model_year",
            False,
        ),  # a plain field that merely starts with model_
        ("flask", "sa", False),
        ("express", "save", True),
        ("express", "class", False),
        (None, "class", False),
    ],
)
def test_reserved_names_depend_on_the_backend(backend, field, refused):
    found = issues([table(fields=(field,))], backend)
    assert bool(found) == refused, found


# ─── Field specs ───
def test_field_spec_rules():
    t = table(
        fields=("title", "price"),
        field_specs=[
            {"name": "nope", "type": "string"},
            {"name": "id", "type": "string"},
            {"name": "price", "type": "money"},
            {"name": "title", "type": "string", "default": "x"},
            {"name": "title", "nullable": False},
        ],
    )
    msgs = issues([t])
    assert any("isn't one of its fields" in m for m in msgs)
    assert any("created automatically" in m for m in msgs)
    assert any('"money" is not a valid field type' in m for m in msgs)
    assert any("declared twice" in m for m in msgs)


@pytest.mark.parametrize(
    "type_,default,ok",
    [
        ("integer", "12", True),
        ("integer", "1.5", False),
        ("decimal", "9.99", True),
        ("decimal", "9.999", False),
        ("decimal", "1e12", False),
        ("boolean", "yes", True),
        ("boolean", "maybe", False),
        ("date", "today", True),
        ("date", "2024-02-30", False),
        ("datetime", "now", True),
        ("json", '{"a": 1}', True),
        ("json", "{nope", False),
    ],
)
def test_defaults_are_coerced_or_refused(type_, default, ok):
    found = issues(
        [
            table(
                fields=("v",),
                field_specs=[{"name": "v", "type": type_, "default": default}],
            )
        ]
    )
    assert (found == []) == ok, found


def test_json_fields_cannot_be_unique_or_indexed():
    one_issue(
        [
            table(
                fields=("meta",),
                field_specs=[{"name": "meta", "type": "json", "unique": True}],
            )
        ],
        "can't be marked unique",
    )
    one_issue(
        [
            table(
                fields=("meta",),
                field_specs=[{"name": "meta", "type": "json"}],
                indexes=[{"fields": ["meta"]}],
            )
        ],
        "can't be indexed",
    )


# ─── Foreign keys ───
def fk_tables(**fk) -> list[dict]:
    return [
        table(
            name="authors",
            fields=("name", "handle"),
            field_specs=[{"name": "handle", "unique": True}],
        ),
        table(
            name="books",
            fields=("title", "author_id"),
            foreign_keys=[{"field": "author_id", **fk}],
        ),
    ]


@pytest.mark.parametrize("ref", ["authors", "Authors", "author"])
def test_foreign_keys_resolve_by_name_slug_or_singular(ref):
    schema = db_schema.resolve_schema(fk_tables(references_table=ref))
    col = schema.table("books").column("author_id")
    assert (
        col.fk.ref_table_sql == "authors"
        and col.type == "integer"
        and col.fk.on_delete == "cascade"
    )
    assert col.fk.constraint_name == "fk_books_author_id"


@pytest.mark.parametrize(
    "fk,fragment",
    [
        ({"references_table": "nobody"}, "doesn't exist"),
        (
            {"references_table": "authors", "references_field": "name"},
            "can only point at",
        ),
        (
            {"references_table": "authors", "references_field": "ghost"},
            "isn't a field of",
        ),
        (
            {"references_table": "authors", "on_delete": "explode"},
            "not a valid on-delete rule",
        ),
    ],
)
def test_foreign_key_rules(fk, fragment):
    one_issue(fk_tables(**fk), fragment, kind="foreign_key")


def test_foreign_key_to_a_unique_field_takes_its_type():
    schema = db_schema.resolve_schema(
        fk_tables(references_table="authors", references_field="handle")
    )
    assert schema.table("books").column("author_id").type == "string"
    t = fk_tables(references_table="authors")
    t[1]["field_specs"] = [{"name": "author_id", "type": "string"}]
    one_issue(t, "they have to match")


def test_set_null_needs_an_optional_field():
    t = fk_tables(references_table="authors", on_delete="set_null")
    t[1]["field_specs"] = [{"name": "author_id", "nullable": False}]
    one_issue(t, 'needs "books.author_id" to be optional')


def test_cycles_are_refused_but_self_references_are_fine():
    two = [
        table(
            name="a",
            fields=("b_id",),
            foreign_keys=[{"field": "b_id", "references_table": "b"}],
        ),
        table(
            name="b",
            fields=("a_id",),
            foreign_keys=[{"field": "a_id", "references_table": "a"}],
        ),
    ]
    one_issue(two, "form a loop")
    three = [
        table(
            name="a",
            fields=("c_id",),
            foreign_keys=[{"field": "c_id", "references_table": "c"}],
        ),
        table(
            name="b",
            fields=("a_id",),
            foreign_keys=[{"field": "a_id", "references_table": "a"}],
        ),
        table(
            name="c",
            fields=("b_id",),
            foreign_keys=[{"field": "b_id", "references_table": "b"}],
        ),
    ]
    assert len([m for m in issues(three) if "form a loop" in m]) == 1
    selfish = [
        table(
            name="staff",
            fields=("boss_id",),
            foreign_keys=[
                {
                    "field": "boss_id",
                    "references_table": "staff",
                    "on_delete": "set_null",
                }
            ],
        )
    ]
    assert issues(selfish) == []


def test_creation_order_puts_parents_first():
    tables = [
        table(
            name="lines",
            fields=("order_id",),
            foreign_keys=[{"field": "order_id", "references_table": "orders"}],
        ),
        table(
            name="orders",
            fields=("customer_id",),
            foreign_keys=[{"field": "customer_id", "references_table": "customers"}],
        ),
        table(name="customers"),
    ]
    assert db_schema.resolve_schema(tables).creation_order == (
        "customers",
        "orders",
        "lines",
    )


# ─── Checks, indexes, seed rows ───
def test_check_and_index_rules():
    t = table(
        fields=("title", "price"),
        checks=[
            {"name": "", "expression": "price > 0"},
            {"name": "positive", "expression": "price > 0"},
            {"name": "Positive", "expression": "price > 1"},
            {"name": "ghost", "expression": "ghost > 0"},
        ],
        indexes=[
            {"fields": []},
            {"fields": ["ghost"]},
            {"fields": ["title", "title"]},
            {"fields": ["title", "created_at"]},
            {"fields": ["title", "created_at"]},
        ],
    )
    msgs = issues([t])
    for fragment in (
        "blank name or expression",
        'two check constraints named "Positive"',
        "isn't a field of",
        "an index with no fields",
        'an index on "ghost"',
        "lists the same field twice",
        "the same index on (title, created_at) twice",
    ):
        assert any(fragment in m for m in msgs), (fragment, msgs)


def test_index_names_and_check_sql():
    t = table(
        fields=("title", "price"),
        checks=[{"name": "Price positive", "expression": "price > 0"}],
        indexes=[
            {"fields": ["title"], "unique": True},
            {"fields": ["price", "created_at"]},
        ],
    )
    rt = db_schema.resolve_schema([t]).tables[0]
    assert [(i.name, i.columns, i.unique) for i in rt.indexes] == [
        ("uq_items_title", ("title",), True),
        ("ix_items_price_created_at", ("price", "created_at"), False),
    ]
    assert (rt.checks[0].constraint_name, rt.checks[0].sql) == (
        "ck_items_price_positive",
        "price > 0",
    )


@pytest.mark.parametrize(
    "row,fragment",
    [
        ({"id": 3}, "filled in automatically"),
        ({"ghost": 1}, "isn't one of its fields"),
        ({"qty": "lots"}, "expected a whole number"),
        ({"code": "x" * 300}, "longer than 255"),
        ({"qty": 1}, 'missing required field "code"'),
        ({"code": "A", "qty": -1}, 'breaks the check "qty positive"'),
        ({"code": "A", "author_id": 1}, "ids are assigned by the database"),
    ],
)
def test_seed_row_rules(row, fragment):
    t = [
        table(name="authors"),
        table(
            name="parts",
            fields=("code", "qty", "author_id"),
            field_specs=[
                {"name": "code", "nullable": False},
                {"name": "qty", "type": "integer"},
            ],
            foreign_keys=[{"field": "author_id", "references_table": "authors"}],
            checks=[{"name": "qty positive", "expression": "qty > 0"}],
            seed_rows=[row],
        ),
    ]
    one_issue(t, fragment, kind="seed_row")


def test_seed_rows_are_coerced_and_unique_values_checked():
    t = table(
        fields=("code", "qty"),
        field_specs=[
            {"name": "code", "unique": True},
            {"name": "qty", "type": "integer"},
        ],
        seed_rows=[
            {"code": "A", "qty": "2"},
            {"code": None},
            {"code": None},
            {"code": "A"},
        ],
    )
    one_issue([t], "repeats a value in unique (code)")
    ok = copy.deepcopy(t)
    ok["seed_rows"] = ok["seed_rows"][:3]  # NULLs never collide
    assert db_schema.resolve_schema([ok]).tables[0].seed_rows == (
        {"code": "A", "qty": 2},
        {},
        {},
    )


# ─── Strict vs lenient, sanitize, normalize ───
def test_strict_resolve_lists_every_issue():
    with pytest.raises(db_schema.SchemaValidationError) as e:
        db_schema.resolve_schema([table(name=""), table(fields=("",))])
    assert len(e.value.issues) == 2 and str(e.value).count("•") == 2


def test_lenient_resolve_and_sanitize_drop_only_what_is_broken():
    t = [
        table(
            fields=("title",),
            field_specs=[{"name": "title", "type": "money"}],
            foreign_keys=[{"field": "owner_id", "references_table": "people"}],
            checks=[{"name": "bad", "expression": "title >"}],
        ),
        table(name="people"),
    ]
    cleaned, notes = db_schema.sanitize_tables(t)
    assert cleaned[0]["key_fields"] == ["title", "owner_id"]  # the FK's field was added
    assert cleaned[0]["field_specs"] == [] and cleaned[0]["checks"] == []
    assert any("Added the field" in n for n in notes) and any(
        "Dropped a check constraint" in n for n in notes
    )
    rt = db_schema.resolve_schema(t, strict=False).table("items")
    assert rt.column("owner_id").fk.ref_table_sql == "peoples"


def test_normalize_is_canonical_and_stable():
    raw = [
        table(
            name=" orders ",
            fields=(" total ", "status", "placed_at"),
            field_specs=[
                {"name": "total", "type": "DECIMAL", "default": 5},
                {"name": "status", "type": None},  # no-op spec: dropped
                {"name": "placed_at", "type": "datetime", "default": "NOW()"},
            ],
            indexes=[{"fields": ["Status"]}],
            seed_rows=[{"total": "1.5"}],
        )
    ]
    once = db_schema.normalize_tables(raw)
    assert db_schema.normalize_tables(once) == once
    assert db_schema.validate_tables(once) == []
    spec = {s["name"]: s for s in once[0]["field_specs"]}
    assert set(spec) == {"total", "placed_at"}
    assert spec["total"]["default"] == "5.00" and spec["placed_at"]["default"] == "now"
    assert once[0]["seed_rows"] == [{"total": "1.50"}]


def test_legacy_tables_resolve_to_the_legacy_by_name_types():
    names = [
        "email",
        "website",
        "price",
        "count",
        "is_done",
        "created_on_date",
        "bio",
        "title",
    ]
    rt = db_schema.resolve_schema([table(fields=names)]).tables[0]
    assert {c.column: (c.type, c.length) for c in rt.columns} == {
        "email": ("string", 255),
        "website": ("string", 500),
        "price": ("float", None),
        "count": ("integer", None),
        "is_done": ("boolean", None),
        "created_on_date": ("datetime", None),
        "bio": ("text", None),
        "title": ("string", 255),
    }
    assert all(c.nullable and not c.declared for c in rt.columns)


def test_constraint_names_stay_within_postgres_limits():
    long = db_schema.constraint_name("uq", "t" * 50, "c" * 50)
    assert len(long) == 63 and long != db_schema.constraint_name(
        "uq", "t" * 50, "c" * 49 + "d"
    )


# ─── Snapshots and diffs ───
def shop(**changes) -> list[dict]:
    base = [
        table(
            name="customers",
            fields=("email", "name"),
            field_specs=[{"name": "email", "nullable": False, "unique": True}],
        ),
        table(
            name="orders",
            fields=("customer_id", "total"),
            field_specs=[{"name": "total", "type": "decimal", "default": "0"}],
            foreign_keys=[{"field": "customer_id", "references_table": "customers"}],
            checks=[{"name": "total ok", "expression": "total >= 0"}],
        ),
    ]
    for key, fn in changes.items():
        fn(base)
    return base


def snap(tables):
    return db_schema.snapshot(db_schema.resolve_schema(tables))


def test_identical_schemas_snapshot_identically_and_diff_to_nothing():
    a = snap(shop())
    reordered = shop()
    reordered[0]["key_fields"] = ["email", "name"]
    assert snap(reordered) == a
    assert db_schema.diff_snapshots(a, snap(shop())) == []
    relabelled = shop()
    relabelled[1]["checks"][0]["expression"] = (
        "total>=0"  # same meaning, different wording
    )
    assert db_schema.diff_snapshots(a, snap(relabelled)) == []


def test_diff_orders_operations_so_each_one_can_run():
    empty = db_schema.empty_snapshot()
    full = snap(shop())
    assert [op["op"] for op in db_schema.diff_snapshots(empty, full)] == [
        "create_table",
        "create_table",
    ]
    assert [op["table"] for op in db_schema.diff_snapshots(empty, full)] == [
        "customers",
        "orders",
    ]
    # Dropping both: the child goes first.
    assert [op["table"] for op in db_schema.diff_snapshots(full, empty)] == [
        "orders",
        "customers",
    ]


def test_diff_and_its_reverse_mirror_each_other():
    old = snap(shop())

    def change(t):
        t[0]["key_fields"].append("phone")
        t[1]["key_fields"].remove("total")
        t[1]["field_specs"] = []
        t[1]["checks"] = []
        t[1]["indexes"] = [{"fields": ["customer_id"]}]
        t[1]["foreign_keys"][0]["on_delete"] = "restrict"

    new = snap(shop(x=change))
    forward = db_schema.diff_snapshots(old, new)
    backward = db_schema.diff_snapshots(new, old)
    kinds = [op["op"] for op in forward]
    assert kinds.index("drop_fk") < kinds.index("drop_column") < kinds.index("add_fk")
    mirror = {
        "add_column": "drop_column",
        "drop_column": "add_column",
        "add_index": "drop_index",
        "drop_check": "add_check",
    }
    for op in forward:
        if op["op"] in mirror:
            assert any(
                b["op"] == mirror[op["op"]] and b["table"] == op["table"]
                for b in backward
            ), op
    assert db_schema.destructive_changes(forward, old, new) == [
        "drop column orders.total (deletes its data)"
    ]


def test_blockers_and_type_changes():
    old = snap(shop())

    def needs_value(t):
        t[0]["key_fields"].append("phone")
        t[0]["field_specs"].append({"name": "phone", "nullable": False})
        t[0]["field_specs"].append({"name": "name", "nullable": False})

    new = snap(shop(x=needs_value))
    blockers = db_schema.migration_blockers(
        db_schema.diff_snapshots(old, new), old, new
    )
    assert (
        len(blockers) == 2
        and "customers.phone" in blockers[0]
        and "customers.name" in blockers[1]
    )

    def retype(t):
        t[1]["field_specs"][0]["type"] = "integer"
        t[1]["field_specs"][0]["default"] = None

    new = snap(shop(x=retype))
    ops = db_schema.diff_snapshots(old, new)
    assert db_schema.destructive_changes(ops, old, new) == [
        "change orders.total: type decimal → integer, default removed (existing values may not convert)"
    ]


# ─── Rendering helpers shared by models and migrations ───
@pytest.mark.parametrize(
    "type_,default,expected",
    [
        ("boolean", True, sa.sql.elements.True_),
        ("integer", 3, sa.sql.elements.TextClause),
        ("decimal", "1.50", sa.sql.elements.TextClause),
        ("datetime", "now", sa.sql.functions.now),
        ("date", "today", sa.sql.elements.TextClause),
        ("string", "it's", str),
        ("json", {"a": [1]}, str),
    ],
)
def test_server_default_code_is_a_real_sqlalchemy_default(type_, default, expected):
    col = {
        "type": type_,
        "length": 255,
        "default": db_schema.normalize_default(default, type_),
    }
    code = db_schema.sa_server_default_code(col)
    value = eval(code, {"sa": sa})  # noqa: S307 — our own generated code
    assert isinstance(value, expected)
    sa.Column("c", eval(db_schema.sa_type_code(col), {"sa": sa}), server_default=value)  # noqa: S307


def test_prompt_description_is_typed_and_never_raises():
    text = db_schema.describe_table_for_prompt(shop()[1], shop())
    assert (
        "- customer_id: integer, optional, foreign key → customers.id (ON DELETE CASCADE)"
        in text
    )
    assert '- total: decimal, optional, default "0.00"' in text
    assert "ck_orders_total_ok: total >= 0" in text
    for garbage in (
        {},
        {"name": ""},
        {"name": "x", "key_fields": [None, 3]},
        {"name": "x", "checks": "nope"},
    ):
        assert db_schema.describe_table_for_prompt(garbage).startswith("Fields")
