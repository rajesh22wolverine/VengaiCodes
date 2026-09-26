# ═══════════════════════════════════════════════════════════════
#  VengaiCode — TypeORM source rendering shared by entities and migrations
#  ai/typeorm_render.py — The deterministic NestJS backend describes each
#  table twice: as a TypeORM entity (src/<table>/<table>.entity.ts) and
#  as migration steps (src/migrations/NNNN-*.ts). TypeORM compares the
#  two (`typeorm schema:log`), so every column, default, constraint and
#  index is rendered HERE, from the db_schema snapshot, for both.
#
#  SQLite only (like the NestJS adapter's AI path): TypeORM migrations
#  are written per database — "datetime", booleans stored as 1/0 and
#  table rebuilds are SQLite's — so a Postgres build would need its own
#  rendering, not a DATABASE_URL.
#
#  How TypeORM spells the same value in the two places (checked against
#  `schema:log` with TypeORM 0.3): an entity default is the JS value
#  (default: 'draft', default: true), a migration column's default is
#  the SQL text ("'draft'", 1). Check constraints are compared BY NAME
#  only, so both come from check_sql() and can't differ.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import json

from app.ai import check_expr, db_schema
from app.ai.codegen_shared import _pascal, _slug, js_string_literal

_COLUMN_TYPE = {
    "string": "varchar",
    "text": "text",
    "integer": "integer",
    "float": "float",
    "decimal": "decimal",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "json": "simple-json",
}
_TS_TYPE = {
    "string": "string",
    "text": "string",
    "integer": "number",
    "float": "number",
    "decimal": "number | string",
    "boolean": "boolean",
    "date": "string",
    "datetime": "Date",
    "json": "any",
}
_ON_DELETE = {"cascade": "CASCADE", "set_null": "SET NULL", "restrict": "RESTRICT"}
_MIGRATION_EPOCH = 1_000_000_000_000  # TypeORM wants a 13-digit timestamp


def ts(value) -> str:
    """A JS literal. Strings go through js_string_literal (same value at
    run time, but user text like "TODO" can't trip the generated-file
    check); JSON is valid JS for everything else we emit."""
    if isinstance(value, str):
        return js_string_literal(value)
    return json.dumps(value, ensure_ascii=False)


def comment(text: str) -> str:
    """User text (a table's name or purpose) inside a // or /* comment."""
    return " ".join(str(text).split()).replace("TODO", "to-do").replace("*/", "* /")


def entity_name(table: dict) -> str:
    return _pascal(table["label"])


def file_slug(table: dict) -> str:
    return _slug(table["label"])


def relation_name(column: str, table: dict) -> str:
    """The relation property beside a foreign key column: customer_id ->
    customer, unless that name is taken (then customer_id_ref)."""
    base = column[:-3] if column.endswith("_id") and len(column) > 3 else column
    if (
        base == column
        or base in table["columns"]
        or base in ("id", "created_at", "updated_at")
    ):
        return f"{column}_ref"
    return base


def migration_class(rev: dict) -> str:
    return f"{_pascal(rev['slug'])}{_MIGRATION_EPOCH + int(rev['id'])}"


def column_type(col: dict, *, migration: bool) -> str:
    if col["type"] == "json" and migration:
        return "text"  # what simple-json is stored as
    return _COLUMN_TYPE[col["type"]]


def fk_column_type(col: dict, tables: dict) -> dict:
    """A foreign key column takes the type of the column it points at."""
    target = tables[col["fk"]["table"]]
    ref = col["fk"]["column"]
    if ref == "id":
        return {"type": "integer"}
    return dict(target["columns"][ref])


def _storage_datetime(value: str) -> str:
    stamp = check_expr._parse_temporal_literal(value)[0]
    return stamp.strftime("%Y-%m-%d %H:%M:%S.") + f"{stamp.microsecond // 1000:03d}"


def _literal_value(value, field_type: str):
    """A canonical (snapshot) value as it is stored in the SQLite column."""
    if value is None:
        return None
    if field_type == "datetime":
        return _storage_datetime(str(value))
    if field_type == "json":
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if field_type == "decimal":
        return str(value)
    return value


def entity_default(col: dict) -> str | None:
    default = col.get("default")
    if not default:
        return None
    if default["kind"] == "now":
        return '() => "CURRENT_TIMESTAMP"'
    if default["kind"] == "today":
        return '() => "CURRENT_DATE"'
    return ts(_literal_value(default["value"], col["type"]))


def sql_literal(value, field_type: str) -> str:
    stored = _literal_value(value, field_type)
    if stored is None:
        return "NULL"
    if isinstance(stored, bool):
        return "1" if stored else "0"
    if isinstance(stored, (int, float)):
        return repr(stored)
    return "'" + str(stored).replace("'", "''") + "'"


def migration_default(col: dict) -> str | None:
    """The column default as TypeORM's migration API wants it: SQL text."""
    default = col.get("default")
    if not default:
        return None
    if default["kind"] == "now":
        return ts("CURRENT_TIMESTAMP")
    if default["kind"] == "today":
        return ts("CURRENT_DATE")
    literal = sql_literal(default["value"], col["type"])
    if col["type"] in ("integer", "float", "boolean"):
        return literal
    return ts(literal)


def check_sql(table: dict, name: str) -> str:
    types = {c: table["columns"][c]["type"] for c in table["columns"]}
    return check_expr.render_storage_sql(
        table["checks"][name]["ast"], types, fractional_digits=3
    )


# ─── migration column definitions ───
def migration_column(
    column: str, col: dict, tables: dict, *, nullable: bool | None = None
) -> str:
    base = fk_column_type(col, tables) if col.get("fk") else col
    parts = [f"name: {ts(column)}", f"type: {ts(column_type(base, migration=True))}"]
    if base["type"] == "string":
        parts.append(f"length: {ts(str(base['length']))}")
    if base["type"] == "decimal":
        parts += [
            f"precision: {db_schema.DECIMAL_PRECISION}",
            f"scale: {db_schema.DECIMAL_SCALE}",
        ]
    if col["nullable"] if nullable is None else nullable:
        parts.append("isNullable: true")
    default = migration_default(col)
    if default is not None:
        parts.append(f"default: {default}")
    return "{ " + ", ".join(parts) + " }"


ID_COLUMN = "{ name: 'id', type: 'integer', isPrimary: true, isGenerated: true, generationStrategy: 'increment' }"
CREATED_AT_COLUMN = (
    "{ name: 'created_at', type: 'datetime', default: \"datetime('now')\" }"
)
UPDATED_AT_COLUMN = (
    "{ name: 'updated_at', type: 'datetime', default: \"datetime('now')\" }"
)


def foreign_key(column: str, col: dict) -> str:
    fk = col["fk"]
    return (
        f"{{ name: {ts(fk['name'])}, columnNames: [{ts(column)}], referencedTableName: {ts(fk['table'])}, "
        f"referencedColumnNames: [{ts(fk['column'])}], onDelete: {ts(_ON_DELETE[fk['on_delete']])} }}"
    )


def uniques(table: dict) -> list[tuple[str, list[str]]]:
    out = [
        (col["unique"], [c])
        for c in table["column_order"]
        if (col := table["columns"][c])["unique"]
    ]
    out += [
        (name, list(idx["columns"]))
        for name, idx in table["indexes"].items()
        if idx["unique"]
    ]
    return out


def indexes(table: dict) -> list[tuple[str, list[str]]]:
    return [
        (name, list(idx["columns"]))
        for name, idx in table["indexes"].items()
        if not idx["unique"]
    ]
