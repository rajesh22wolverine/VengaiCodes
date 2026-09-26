"""
TypeORM rendering (ai/typeorm_render.py + migrations_typeorm.py) for the
deterministic NestJS backend. The end-to-end proof — `typeorm schema:log`
finding nothing to change at every stage, the API behaving like the other
backends, migration:revert walking back — was run against TypeORM 0.3 on
SQLite when this was written; these tests pin the rendering it relies on.
"""

from app.ai import check_expr, db_schema, migrations_gen
from app.ai import typeorm_render as tr


def test_defaults_are_js_values_in_entities_and_sql_in_migrations():
    string = {
        "type": "string",
        "length": 255,
        "nullable": False,
        "default": {"kind": "literal", "value": "draft"},
    }
    boolean = {
        "type": "boolean",
        "nullable": True,
        "default": {"kind": "literal", "value": True},
    }
    now = {"type": "datetime", "nullable": True, "default": {"kind": "now"}}
    assert tr.entity_default(string) == '"draft"'
    assert tr.migration_default(string) == "\"'draft'\""
    assert (tr.entity_default(boolean), tr.migration_default(boolean)) == ("true", "1")
    assert tr.entity_default(now) == '() => "CURRENT_TIMESTAMP"'


def test_datetime_literals_use_typeorms_sqlite_storage_format():
    types = {"placed_at": "datetime"}
    ast = check_expr.canonicalize_literals(
        check_expr.parse("placed_at >= '2024-01-31T09:30'"), types
    )
    assert (
        check_expr.render_storage_sql(ast, types, fractional_digits=3)
        == "placed_at >= '2024-01-31 09:30:00.000'"
    )
    assert (
        check_expr.render_storage_sql(ast, types)
        == "placed_at >= '2024-01-31 09:30:00.000000'"
    )


def test_js_strings_hide_todo_from_the_generated_file_check():
    assert "TODO" not in tr.ts("TODO list")
    assert tr.comment("TODO */ later") == "to-do * / later"


def test_relation_property_names():
    table = {"columns": {"customer_id": {}, "customer": {}, "owner_id": {}}}
    assert tr.relation_name("owner_id", table) == "owner"
    assert (
        tr.relation_name("customer_id", table) == "customer_id_ref"
    )  # "customer" is a column
    assert tr.relation_name("manager", table) == "manager_ref"


TABLES = [
    {"name": "authors", "key_fields": ["name"]},
    {
        "name": "books",
        "key_fields": ["title", "author_id"],
        "foreign_keys": [{"field": "author_id", "references_table": "authors"}],
        "seed_rows": [{"title": "Dune"}],
    },
]


def test_migrations_have_up_and_down_and_timestamped_class_names():
    schema = db_schema.resolve_schema(TABLES, backend="nestjs", strict=True)
    first = migrations_gen.plan_migrations("nestjs", schema, None, [])
    files = {f.path: f.content for f in first.files}
    initial = files["backend/src/migrations/0001-initial.ts"]
    assert "export class Initial1000000000001 implements MigrationInterface" in initial
    assert (
        'referencedTableName: "authors"' in initial and 'onDelete: "CASCADE"' in initial
    )
    assert "INSERT INTO" in initial and '["Dune"]' in initial
    assert (
        'await queryRunner.dropTable("books");' in initial.split("public async down")[1]
    )

    changed = [TABLES[0], dict(TABLES[1], key_fields=["title", "author_id", "pages"])]
    second = migrations_gen.plan_migrations(
        "nestjs",
        db_schema.resolve_schema(changed, backend="nestjs", strict=True),
        first.state,
        [f.model_dump() for f in first.files],
    )
    content = {f.path: f.content for f in second.files}[second.new_revision["filename"]]
    assert "export class AddBooksPages1000000000002" in content
    up, down = content.split("public async down")
    assert 'addColumn("books", new TableColumn({ name: "pages"' in up
    assert 'dropColumn("books", "pages")' in down
