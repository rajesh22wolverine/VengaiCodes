"""
Django rendering (ai/django_render.py + migrations_django.py): the same
source for the model classes and the migrations. The end-to-end proof —
`manage.py makemigrations --check` finding nothing, the API behaving like
the other backends, the migration history walking back and forward — was
run against a real Django 5.0 when this was written; these tests pin the
rendering it relies on.
"""

import pytest

from app.ai import check_expr, db_schema, django_render, migrations_gen

COLUMNS = {
    "a": {"type": "integer"},
    "b": {"type": "integer"},
    "name": {"type": "string"},
    "starts_on": {"type": "date"},
    "total": {"type": "decimal"},
}
TYPES = {k: v["type"] for k, v in COLUMNS.items()}


def q(expression: str) -> str:
    ast = check_expr.canonicalize_literals(check_expr.parse(expression), TYPES)
    return django_render.q_code(ast, COLUMNS, django_render.Imports())


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("a >= 0", "models.Q(a__gte=0)"),
        ("5 < a", "models.Q(a__gt=5)"),  # flipped to put the field first
        ("a <> 1", "~models.Q(a=1)"),
        # NOT is pushed down to the leaves, so Django never adds its
        # "IS NOT NULL" under a second negation.
        ("NOT (a < 1)", "models.Q(a__gte=1)"),
        ("NOT (a > 1 OR b < 2)", "models.Q(a__lte=1) & models.Q(b__gte=2)"),
        ("NOT (NOT (a = 1))", "models.Q(a=1)"),
        ("NOT (a <> 1)", "models.Q(a=1)"),
        ("a BETWEEN 1 AND 5", "models.Q(a__range=(1, 5))"),
        ("a NOT BETWEEN 1 AND 5", "(models.Q(a__lt=1) | models.Q(a__gt=5))"),
        ("a >= b", 'models.Q(a__gte=models.F("b"))'),
        ("name IN ('x', 'y')", "models.Q(name__in=['x', 'y'])"),
        ("name NOT LIKE 'ab%'", "~models.Q(name__like='ab%')"),
        ("name IS NOT NULL", "models.Q(name__isnull=False)"),
        ("LENGTH(name) > 3", 'models.Q(GreaterThan(Length("name"), 3))'),
        ("LENGTH(name) <> 3", '~models.Q(Exact(Length("name"), 3))'),
        (
            "starts_on >= '2024-01-31'",
            "models.Q(starts_on__gte=_datetime.date(2024, 1, 31))",
        ),
        ("total > 0", 'models.Q(total__gt=_decimal.Decimal("0"))'),
    ],
)
def test_check_rules_become_q_objects(expression, expected):
    assert q(expression) == expected


def test_imports_follow_what_was_rendered():
    imports = django_render.Imports()
    ast = check_expr.parse("LENGTH(name) > 3 AND starts_on >= '2024-01-31'")
    django_render.q_code(check_expr.canonicalize_literals(ast, TYPES), COLUMNS, imports)
    lines = imports.lines(migrations=True)
    assert "import datetime as _datetime" in lines
    assert "from django.db.models.functions import Length" in lines
    assert "from django.db.models.lookups import GreaterThan" in lines
    assert "from django.db import migrations, models" in lines


def test_index_names_fit_djangos_30_characters():
    long = "ix_order_items_order_id_product_id_status"
    short = django_render.index_name(long)
    assert len(short) <= 30 and short == django_render.index_name(long)
    assert django_render.index_name("ix_orders_status") == "ix_orders_status"


def test_foreign_key_field_names_and_their_problems():
    fk = {"table": "customers", "column": "id", "on_delete": "cascade", "name": "fk"}
    assert django_render.field_name("customer_id", {"fk": fk}) == "customer"
    assert django_render.field_name("manager", {"fk": fk}) == "manager"
    assert django_render.field_name("customer_id", {"fk": None}) == "customer_id"
    columns = {"customer_id": {"fk": fk}, "customer": {"fk": None}}
    assert "already" in django_render.field_name_problem(
        "customer_id", {"fk": fk}, columns
    )
    assert django_render.field_name_problem("bad__name", {"fk": None}, {}) is not None


def _schema(tables):
    return db_schema.resolve_schema(tables, backend="django", strict=True)


TABLES = [
    {"name": "authors", "key_fields": ["name"]},
    {
        "name": "books",
        "key_fields": ["title", "author_id", "price"],
        "field_specs": [{"name": "price", "type": "decimal", "default": "0.00"}],
        "foreign_keys": [{"field": "author_id", "references_table": "authors"}],
        "checks": [{"name": "price ok", "expression": "price >= 0"}],
        "seed_rows": [{"title": "Dune"}],
    },
]


def test_migrations_chain_and_render_the_model_state():
    first = migrations_gen.plan_migrations("django", _schema(TABLES), None, [])
    files = {f.path: f.content for f in first.files}
    initial = files["backend/api/migrations/0001_initial.py"]
    assert "initial = True" in initial and "dependencies = []" in initial
    assert 'options={"db_table": "books"}' in initial
    assert (
        '("author", models.ForeignKey("api.Authors", on_delete=models.CASCADE, db_column="author_id"'
        in initial
    )
    assert "models.CheckConstraint(check=models.Q(price__gte=" in initial
    assert (
        "migrations.RunPython(_seed_0001_1_forward, _seed_0001_1_backward)" in initial
    )
    assert files["backend/api/migrations/__init__.py"].strip()  # not an empty file

    changed = [
        TABLES[0],
        dict(TABLES[1], key_fields=TABLES[1]["key_fields"] + ["pages"]),
    ]
    second = migrations_gen.plan_migrations(
        "django", _schema(changed), first.state, [f.model_dump() for f in first.files]
    )
    name = second.new_revision["filename"]
    assert name == "backend/api/migrations/0002_add_books_pages.py"
    content = {f.path: f.content for f in second.files}[name]
    assert 'dependencies = [("api", "0001_initial")]' in content
    assert (
        'migrations.AddField(model_name="books", name="pages", field=models.IntegerField('
        in content
    )


def test_a_column_becoming_a_foreign_key_keeps_its_data():
    as_integer = TABLES[1]["field_specs"] + [{"name": "author_id", "type": "integer"}]
    plain = [TABLES[0], dict(TABLES[1], foreign_keys=[], field_specs=as_integer)]
    first = migrations_gen.plan_migrations("django", _schema(plain), None, [])
    second = migrations_gen.plan_migrations(
        "django", _schema(TABLES), first.state, [f.model_dump() for f in first.files]
    )
    content = {f.path: f.content for f in second.files}[second.new_revision["filename"]]
    # Pin the column, rename the field in Django's state only, then change its type.
    pin = content.index(
        'name="author_id", field=models.IntegerField(db_column="author_id", null=True, blank=True)'
    )
    rename = content.index('old_name="author_id", new_name="author"')
    retype = content.index('name="author", field=models.ForeignKey(')
    assert pin < rename < retype
    assert "RemoveField" not in content
