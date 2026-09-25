"""
check_expr.py — the parsed check-constraint grammar every generated
CHECK constraint, Mongoose check and seed-row validation comes from.

The differential test at the bottom is the important one: each rendered
expression runs as a REAL SQLite CHECK constraint (values stored through
SQLAlchemy, exactly as a generated app stores them) and must accept or
reject every row exactly as evaluate() predicts.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.ai import check_expr
from app.ai.check_expr import CheckExpressionError, evaluate, parse, render_sql

COLUMNS = {
    "id": "integer",
    "n": "integer",
    "price": "decimal",
    "f": "float",
    "name": "string",
    "bio": "text",
    "flag": "boolean",
    "day": "date",
    "at": "datetime",
    "meta": "json",
    "order": "integer",  # an SQL keyword used as a column name
}


def bound(text: str) -> dict:
    def resolve(name: str) -> str:
        if name.lower() not in COLUMNS:
            raise CheckExpressionError(f'"{name}" isn\'t a field.')
        return name.lower()

    ast = check_expr.bind_fields(parse(text), resolve)
    check_expr.type_check(ast, COLUMNS)
    return check_expr.canonicalize_literals(ast, COLUMNS)


# ─── Grammar ───
@pytest.mark.parametrize(
    "text,expected",
    [
        ("n > 3", {"cmp": ">", "left": {"field": "n"}, "right": {"value": 3}}),
        ("n == 3", {"cmp": "=", "left": {"field": "n"}, "right": {"value": 3}}),
        ("n != 3", {"cmp": "<>", "left": {"field": "n"}, "right": {"value": 3}}),
        ("n >= -2.5", {"cmp": ">=", "left": {"field": "n"}, "right": {"value": -2.5}}),
        ("name IS NULL", {"is_null": {"field": "name"}, "negated": False}),
        ("name is not null", {"is_null": {"field": "name"}, "negated": True}),
        (
            "name IN ('a', 'it''s')",
            {"in": {"field": "name"}, "values": ["a", "it's"], "negated": False},
        ),
        ("n NOT IN (1, 2)", {"in": {"field": "n"}, "values": [1, 2], "negated": True}),
        (
            "n BETWEEN 1 AND f",
            {
                "between": {"field": "n"},
                "low": {"value": 1},
                "high": {"field": "f"},
                "negated": False,
            },
        ),
        (
            "name NOT LIKE 'a%'",
            {"like": {"field": "name"}, "pattern": "a%", "negated": True},
        ),
        (
            "LEN(name) > 0",
            {"cmp": ">", "left": {"length": {"field": "name"}}, "right": {"value": 0}},
        ),
        ("flag", {"cmp": "=", "left": {"field": "flag"}, "right": {"value": True}}),
        (
            "!flag",
            {"not": {"cmp": "=", "left": {"field": "flag"}, "right": {"value": True}}},
        ),
    ],
)
def test_parse_every_construct(text, expected):
    assert parse(text) == expected


def test_and_binds_tighter_than_or_and_aliases_work():
    ast = parse("n > 1 || n < 0 && flag")
    assert "or" in ast and "and" in ast["or"][1]
    assert parse("(n > 1 OR n < 0) AND flag")["and"][0]["or"]


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("", "needs an expression"),
        ("n >", "a field name or a value"),
        ('name = "bob"', "single quotes"),
        ("n > 1 AND", "a field name or a value"),
        ("n IN 1, 2", '"(" after IN'),
        ("n BETWEEN 1 OR 2", "AND inside BETWEEN"),
        ("name LIKE other", "quoted' pattern"),
        ("n NOT 3", "IN, BETWEEN or LIKE after NOT"),
        ("n > 1 n", "AND, OR or the end"),
        ("n ; 1", 'Unexpected ";"'),
        ("0); DROP TABLE users; --", "Unexpected"),
        ("(" * 40 + "flag" + ")" * 40, "at most"),
        ("n > " + "1" * 600, "limited to"),
        ("name = 'a\x00'", "NUL"),
    ],
)
def test_bad_input_is_refused_with_a_readable_message(text, fragment):
    with pytest.raises(CheckExpressionError) as e:
        parse(text)
    assert fragment in str(e.value)


def test_referenced_fields_and_binding_to_column_slugs():
    ast = check_expr.bind_fields(
        parse("N > 1 AND LENGTH(Name) < 5"), lambda n: n.lower()
    )
    assert check_expr.referenced_fields(ast) == ["n", "name"]
    with pytest.raises(CheckExpressionError, match="isn't a field"):
        bound("nope > 1")


# ─── Type checking ───
@pytest.mark.parametrize(
    "text,fragment",
    [
        ("name > 'a'", "text can only be compared with"),
        ("name BETWEEN 'a' AND 'b'", "found BETWEEN"),
        ("flag < TRUE", "TRUE/FALSE values can only be compared"),
        ("n = 'three'", "can't be compared with"),
        ("n = TRUE", "isn't a true/false field"),
        ("n", "isn't a true/false field"),
        ("LENGTH(n) > 1", "LENGTH() only works on text"),
        ("n LIKE '1%'", "LIKE only works on text"),
        ("meta = 'x'", "JSON fields can't be compared"),
        ("day > '2024-01-31T10:00:00'", "is a date (no time of day)"),
        ("at > '2024-01-31T10:00:00Z'", "without a time zone"),
        ("day > 'soon'", "isn't a date"),
        ("day > name", "can't be compared with"),
        ("1 = 1", "has to involve at least one field"),
    ],
)
def test_type_errors(text, fragment):
    with pytest.raises(CheckExpressionError) as e:
        bound(text)
    assert fragment in str(e.value)


def test_date_literals_are_stored_in_one_canonical_form():
    assert bound("at >= '2024-01-31 09:30'")["right"] == {
        "value": "2024-01-31T09:30:00"
    }
    assert bound("day >= '2024-01-31'")["right"] == {"value": "2024-01-31"}
    assert bound("day <> at") == {
        "cmp": "<>",
        "left": {"field": "day"},
        "right": {"field": "at"},
    }


# ─── SQL rendering ───
def test_render_quotes_keywords_escapes_text_and_keeps_grouping():
    assert render_sql(bound("order > 1")) == '"order" > 1'
    assert render_sql(bound("name IN ('it''s')")) == "name IN ('it''s')"
    assert (
        render_sql(bound("(n > 1 OR n < 0) AND flag"))
        == "(n > 1 OR n < 0) AND flag = TRUE"
    )
    assert render_sql(bound("NOT (n > 1 AND n < 5)")) == "NOT (n > 1 AND n < 5)"
    # Letters in a LIKE pattern: LOWER() both sides, so Postgres matches
    # SQLite's case-insensitive LIKE; a backslash is always literal.
    assert render_sql(bound("name LIKE 'A%'")) == "LOWER(name) LIKE LOWER('A%')"
    assert render_sql(bound("name LIKE '1\\%'")) == "name LIKE '1\\\\%' ESCAPE '\\'"


def test_storage_sql_writes_date_times_the_way_sqlite_stores_them():
    ast = bound("at >= '2024-01-01T00:00:00'")
    assert (
        check_expr.render_storage_sql(ast, COLUMNS)
        == "at >= '2024-01-01 00:00:00.000000'"
    )


# ─── Evaluation (SQL three-valued logic) ───
def test_three_valued_logic():
    row = {"n": None, "flag": True}
    assert evaluate(bound("n > 1"), row, COLUMNS) is None
    assert evaluate(bound("n > 1 OR flag"), row, COLUMNS) is True
    assert evaluate(bound("n > 1 AND flag"), row, COLUMNS) is None
    assert evaluate(bound("n > 1 AND NOT flag"), row, COLUMNS) is False
    assert evaluate(bound("NOT (n > 1)"), row, COLUMNS) is None
    assert evaluate(bound("n IS NULL"), row, COLUMNS) is True
    assert evaluate(bound("n IN (1, 2)"), row, COLUMNS) is None
    assert evaluate(bound("n BETWEEN 1 AND 5"), {"n": 9}, COLUMNS) is False
    assert evaluate(bound("name LIKE 'b_b%'"), {"name": "BOBBY"}, COLUMNS) is True
    assert (
        evaluate(bound("name LIKE 'é'"), {"name": "É"}, COLUMNS) is False
    )  # only A-Z fold, as SQLite
    assert (
        evaluate(bound("LENGTH(name) = 2"), {"name": "😀😀"}, COLUMNS) is True
    )  # characters, not bytes
    assert evaluate(bound("price >= 0.1"), {"price": Decimal("0.10")}, COLUMNS) is True
    assert (
        evaluate(
            bound("at < '2024-06-01T12:00:00'"),
            {"at": datetime(2024, 6, 1, 11)},
            COLUMNS,
        )
        is True
    )


# ─── Differential: real SQLite CHECK vs evaluate() ───
EXPRESSIONS = [
    "n > 3",
    "n <> 3 AND f < 7.5",
    "price >= 0 AND price <= 10.5",
    "NOT (n BETWEEN 1 AND 5)",
    "n NOT BETWEEN f AND 10",
    "name IN ('a', 'Bob')",
    "name NOT IN ('a')",
    "name LIKE 'b_b%'",
    "name NOT LIKE '%x%'",
    "bio LIKE '%\\%'",
    "LENGTH(name) >= 3",
    "name IS NULL OR n IS NOT NULL",
    "flag",
    "flag = FALSE OR n < 0",
    "day >= '2024-01-31'",
    "day BETWEEN '2024-01-01' AND '2024-12-31'",
    "at < '2024-06-01T12:00:00'",
    "at >= '2024-06-01'",
    "at IN ('2024-06-01T12:00:00')",
    "(n > 1 AND name = 'Bob') OR NOT flag",
    "order > 0",
]
ROWS = [
    {},
    {
        "n": 3,
        "price": Decimal("1.25"),
        "f": 2.5,
        "name": "Bob",
        "bio": "50\\",
        "flag": True,
        "day": date(2024, 1, 31),
        "at": datetime(2024, 6, 1, 12),
        "order": 1,
    },
    {
        "n": 7,
        "price": Decimal("11"),
        "f": 7.0,
        "name": "bXb",
        "bio": "none",
        "flag": False,
        "day": date(2023, 12, 31),
        "at": datetime(2024, 6, 1, 11, 59, 59),
        "order": 0,
    },
    {
        "n": 0,
        "price": Decimal("0"),
        "name": "ab",
        "day": date(2025, 1, 1),
        "at": datetime(2025, 1, 1),
    },
    {"n": 5, "name": "BOB", "at": datetime(2024, 6, 1, 12), "flag": True},
    {
        "n": -2,
        "name": "a",
        "flag": False,
        "price": Decimal("-1"),
        "at": datetime(2024, 5, 31, 23, 59),
    },
]
SA_TYPES = {
    "n": sa.Integer(),
    "price": sa.Numeric(12, 2),
    "f": sa.Float(),
    "name": sa.String(255),
    "bio": sa.Text(),
    "flag": sa.Boolean(),
    "day": sa.Date(),
    "at": sa.DateTime(timezone=True),
    "order": sa.Integer(),
}


@pytest.mark.filterwarnings("ignore::sqlalchemy.exc.SAWarning")  # Decimal on SQLite
def test_sqlite_check_constraints_agree_with_evaluate_row_by_row():
    engine = sa.create_engine("sqlite://")
    outcomes = set()
    for i, text in enumerate(EXPRESSIONS):
        ast = bound(text)
        md = sa.MetaData()
        table = sa.Table(
            f"t{i}",
            md,
            sa.Column("id", sa.Integer, primary_key=True),
            *(sa.Column(name, type_) for name, type_ in SA_TYPES.items()),
            sa.CheckConstraint(
                check_expr.render_storage_sql(ast, COLUMNS), name=f"ck_{i}"
            ),
        )
        md.create_all(engine)
        for row in ROWS:
            expected = evaluate(ast, row, COLUMNS)
            outcomes.add(expected)
            with engine.connect() as conn:
                try:
                    conn.execute(table.insert().values(**row))
                    conn.commit()
                    accepted = True
                except sa.exc.IntegrityError:
                    conn.rollback()
                    accepted = False
            assert accepted == (expected is not False), (
                f"{text!r} on {row}: evaluate={expected}, sqlite accepted={accepted}"
            )
    assert outcomes == {True, False, None}
