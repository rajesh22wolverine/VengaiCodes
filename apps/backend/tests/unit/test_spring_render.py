"""
Spring Boot / Flyway rendering (ai/spring_render.py, migrations_flyway.py)
and the SQL file check. The end-to-end proof — Flyway migrating an H2
database and Hibernate's ddl-auto=validate accepting the entities at
every stage, the API behaving like the other backends — was run with
Spring Boot 3.2 when this was written; these tests pin what it relies on.
"""

from app.ai import check_expr, db_schema, migrations_gen
from app.ai import spring_render as sr
from app.ai.codegen_shared import validate_generated_content


def test_check_sql_quotes_every_identifier_and_pins_utc():
    types = {"placed_at": "datetime", "rank": "integer"}
    ast = check_expr.canonicalize_literals(
        check_expr.parse("placed_at >= '2024-01-31T09:30' AND rank > 0"), types
    )
    sql = check_expr.render_storage_sql(ast, types, utc_offset=True, quote_all=True)
    assert sql == """"placed_at" >= '2024-01-31 09:30:00.000000+00:00' AND "rank" > 0"""


def test_sql_and_java_literals():
    assert sr.sql_literal(True, "boolean") == "TRUE"
    assert sr.sql_literal("2024-01-31", "date") == "DATE '2024-01-31'"
    assert sr.sql_literal("O'Brien", "string") == "'O''Brien'"
    assert sr.sql_literal({"a": 1}, "json") == """'{"a":1}'"""
    assert "TODO" not in sr.java_string("TODO list")
    now = {"type": "datetime", "default": {"kind": "now"}}
    assert sr.java_default(now) == "Instant.now()"


def test_generated_sql_is_checked_outside_strings():
    ok = """INSERT INTO "notes" ("title") VALUES ('Notes :)');\n-- a comment (\n"""
    assert validate_generated_content("sql", ok, "V1__x.sql") is None
    assert (
        validate_generated_content("sql", "INSERT INTO t VALUES ('TODO');", "V1__x.sql")
        is None
    )
    assert (
        validate_generated_content("sql", "CREATE TABLE t (a INT;", "V1__x.sql")
        is not None
    )
    assert validate_generated_content("sql", "SELECT 'open", "V1__x.sql") is not None


TABLES = [
    {"name": "authors", "key_fields": ["name"]},
    {
        "name": "books",
        "key_fields": ["title", "author_id"],
        "field_specs": [{"name": "author_id", "type": "integer"}],
    },
]


def _plan(tables, previous=None):
    schema = db_schema.resolve_schema(tables, backend="spring_boot", strict=True)
    return migrations_gen.plan_migrations(
        "spring_boot",
        schema,
        previous.state if previous else None,
        [f.model_dump() for f in previous.files] if previous else [],
    )


def test_flyway_versions_and_a_column_becoming_a_foreign_key():
    first = _plan(TABLES)
    files = {f.path: f.content for f in first.files}
    initial = files["backend/src/main/resources/db/migration/V1__initial.sql"]
    assert 'CREATE TABLE "books" (' in initial and '"author_id" INTEGER' in initial
    with_fk = [
        TABLES[0],
        dict(
            TABLES[1],
            foreign_keys=[{"field": "author_id", "references_table": "authors"}],
        ),
    ]
    second = _plan(with_fk, first)
    content = {f.path: f.content for f in second.files}[second.new_revision["filename"]]
    assert second.new_revision["filename"].endswith("/V2__add_fk_books_author_id.sql")
    # The column takes the id's type (BIGINT) before the constraint — found by
    # Hibernate's validation refusing to start the app otherwise.
    retype = content.index('ALTER COLUMN "author_id" SET DATA TYPE BIGINT;')
    constraint = content.index('ADD CONSTRAINT "fk_books_author_id" FOREIGN KEY')
    assert retype < constraint
    third = _plan(TABLES, second)
    back = {f.path: f.content for f in third.files}[third.new_revision["filename"]]
    assert back.index("DROP CONSTRAINT") < back.index("SET DATA TYPE INTEGER;")
