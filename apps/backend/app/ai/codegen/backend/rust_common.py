# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Shared Rust Helpers
#  ai/codegen/backend/rust_common.py — NOT an adapter itself. A plain
#  serde/sqlx data struct doesn't care which web framework will use it,
#  so actix.py and axum.py share this one model-generation prompt
#  instead of duplicating it — their routes/wiring genuinely differ
#  (different web-framework APIs) and stay in their own files.
#
#  2026-09-24: typed columns. The CREATE TABLE both frameworks run at
#  startup honors a table's declared types, NOT NULL, defaults, unique
#  columns, foreign keys (ON DELETE rules — sqlx turns SQLite's
#  foreign_keys pragma on by default, so they're enforced) and checks,
#  and its indexes become CREATE INDEX statements run right after it.
#  A table that declares nothing produces exactly the SQL it always
#  did — see typed_schema.py. The struct, handler and GraphQL prompts
#  all quote that exact SQL (schema_sql_for_prompt), because sqlx
#  decodes strictly by column type and a mismatch only fails at runtime.
# ═══════════════════════════════════════════════════════════════

import json
import re

from app.ai import check_expr, db_schema
from app.ai.codegen.backend import typed_schema
from app.ai.codegen.types import FileResult, ModelCtx
from app.ai.codegen_shared import (
    GROQ_FILE_MAX_TOKENS,
    GeneratedFile,
    _pascal,
    _slug,
    generate_text_validated,
)


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")
    struct_name = _pascal(table_name)
    all_tables = ctx.all_tables or [ctx.table]

    prompt = f"""Write ONE complete, real Rust struct for the "{table_name}" table of this app.

Table purpose: {ctx.table.get("purpose", "")}
{db_schema.describe_table_for_prompt(ctx.table, all_tables)}

The app creates this table at startup with exactly this SQL (SQLite):
{schema_sql_for_prompt(all_tables, only=ctx.table)}

Requirements:
- Struct name: `pub struct {struct_name}`, with `pub id: i64` plus real `pub` fields (correct
  Rust types) matching the fields above — every field MUST be `pub`, since handler code in a
  different module constructs and reads these fields directly. An optional field is an
  `Option<...>`. Each field's type must decode its SQL column's type exactly (TEXT -> String,
  INTEGER -> i64, REAL -> f64, BOOLEAN -> bool) — where the field list and the SQL disagree, the
  SQL is what the database really has. Only columns in the SQL exist.
- Derive exactly: `#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, sqlx::FromRow)]`.
- Add a second `pub struct {struct_name}Input` (same derives minus `sqlx::FromRow`, same `pub`
  fields) with the same fields EXCEPT `id`, for use when creating/updating a record from a
  request body.
- Implement any validation logic implied by the key features / user stories above (and every
  check constraint listed above) as a real method on {struct_name}Input (e.g.
  `pub fn validate(&self) -> Result<(), String>`), not a placeholder.
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw Rust code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(
        prompt,
        "rust",
        GROQ_FILE_MAX_TOKENS,
        user=ctx.user,
        db=ctx.db,
        context=ctx.shared_context(),
    )
    return GeneratedFile(
        path=f"backend/src/models/{_slug(table_name)}.rs",
        language="rust",
        content=content,
        description=f"Data struct for {table_name}",
    ), issue


def models_mod_rs(model_files: list[GeneratedFile]) -> str:
    lines = "\n".join(
        f"pub mod {f.path.split('/')[-1].removesuffix('.rs')};" for f in model_files
    )
    return lines + "\n" if lines else "// no models generated\n"


def _infer_sql_type(field_name: str) -> str:
    lowered = field_name.lower()
    if any(
        k in lowered for k in ("done", "active", "enabled", "completed", "is_", "has_")
    ):
        return "BOOLEAN"
    if any(k in lowered for k in ("count", "quantity", "number", "age")):
        return "INTEGER"
    if any(k in lowered for k in ("price", "amount", "total", "cost")):
        return "REAL"
    return "TEXT"


def _table_name(display_name: str) -> str:
    # The name these apps have always used (and the handler prompts tell
    # the AI): slug + "s", unconditionally.
    return f"{_slug(display_name)}s"


# SQLite column type (really: affinity) per db_schema type. SQLite has no
# exact decimal, so decimal is REAL — the same storage the name-based
# guess gives a price. Dates, datetimes and JSON are TEXT affinity so a
# value is stored exactly as written (ISO-8601 is SQLite's own date
# convention); a DATE/JSON type name would get NUMERIC affinity, which
# silently turns text like "2024" or a JSON number into an integer that
# sqlx can then no longer decode as a String.
_SQLITE_TYPES = {
    "string": "TEXT",
    "text": "TEXT",
    "integer": "INTEGER",
    "float": "REAL",
    "decimal": "REAL",
    "boolean": "BOOLEAN",
    "date": "TEXT",
    "datetime": "TEXT",
    "json": "TEXT",
}

_SQL_ON_DELETE = {"cascade": "CASCADE", "set_null": "SET NULL", "restrict": "RESTRICT"}

# The db_schema type each of _infer_sql_type()'s guesses amounts to.
_GUESSED_FIELD_TYPES = {
    "BOOLEAN": "boolean",
    "INTEGER": "integer",
    "REAL": "float",
    "TEXT": "string",
}

_DECIMAL_LITERAL_RE = re.compile(r"-?\d+(\.\d+)?")


def _sql_column(
    col: db_schema.ResolvedColumn, schema: db_schema.ResolvedSchema
) -> tuple[str, str]:
    """(SQLite column type, the db_schema type that amounts to) — the
    latter is what the column's DEFAULT is rendered as, so the two can't
    disagree."""
    ref_col = typed_schema.referenced_column(schema, col)
    if ref_col is not None:
        # Same type as the column it points at.
        return _sql_column(ref_col, schema)
    if col.fk is not None:
        return "INTEGER", "integer"  # references an INTEGER PRIMARY KEY id
    guessed = _infer_sql_type(col.name)
    field_type = _GUESSED_FIELD_TYPES[guessed]
    if typed_schema.keeps_guess(col, field_type, schema):
        return guessed, field_type
    return _SQLITE_TYPES[col.type], col.type


def _sql_default(default: dict, field_type: str) -> str:
    kind = default["kind"]
    if kind == "now":
        return "CURRENT_TIMESTAMP"
    if kind == "today":
        return "CURRENT_DATE"
    value = default["value"]
    if field_type == "json":
        return check_expr.sql_literal(json.dumps(value, sort_keys=True))
    if (
        field_type == "decimal"
        and isinstance(value, str)
        and _DECIMAL_LITERAL_RE.fullmatch(value)
    ):
        return value  # db_schema's exact decimal string, e.g. "9.99"
    return check_expr.sql_literal(value)


def _typed_create_table_sql(
    rt: db_schema.ResolvedTable, plural: str, schema: db_schema.ResolvedSchema
) -> str:
    ident = check_expr.sql_identifier
    columns = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
    constraints: list[str] = []
    for col in rt.columns:
        sql_type, field_type = _sql_column(col, schema)
        definition = f"{ident(col.column)} {sql_type}"
        if not col.nullable:
            definition += " NOT NULL"
        default = typed_schema.rendered_default(col, field_type)
        if default is not None:
            definition += f" DEFAULT {_sql_default(default, field_type)}"
        columns.append(definition)
        if col.unique:
            constraints.append(
                f"CONSTRAINT {col.unique_constraint_name} UNIQUE ({ident(col.column)})"
            )
        if col.fk is not None:
            constraints.append(
                f"CONSTRAINT {col.fk.constraint_name} FOREIGN KEY ({ident(col.column)}) "
                f"REFERENCES {_table_name(col.fk.ref_table)}({ident(col.fk.ref_column)}) "
                f"ON DELETE {_SQL_ON_DELETE[col.fk.on_delete]}"
            )
    # These tables never had timestamp columns; one only appears when a
    # check or index actually names it, since it can't refer to a column
    # that doesn't exist.
    for implicit in typed_schema.referenced_implicit_columns(rt):
        columns.append(f"{implicit} TEXT DEFAULT CURRENT_TIMESTAMP")
    for chk in rt.checks:
        # chk.sql is rendered from db_schema's parsed expression (never the
        # raw text), so it's portable SQL with every identifier validated.
        constraints.append(f"CONSTRAINT {chk.constraint_name} CHECK ({chk.sql})")
    body = ",\n    ".join(columns + constraints)
    return f"CREATE TABLE IF NOT EXISTS {plural} (\n    {body}\n)"


def build_create_table_sql(table: dict, all_tables: list[dict] | None = None) -> str:
    """One CREATE TABLE statement. `all_tables` (the whole architecture)
    lets a foreign key be typed after the column it references; without
    it the table is resolved on its own."""
    schema = typed_schema.resolve_if_typed(
        all_tables if all_tables is not None else [table]
    )
    return _create_table_sql(table, schema)


def _create_table_sql(table: dict, schema: db_schema.ResolvedSchema | None) -> str:
    plural = f"{_slug(table.get('name', 'item'))}s"
    rt = typed_schema.typed_table(schema, table)
    if rt is not None:
        return _typed_create_table_sql(rt, plural, schema)

    fields = [
        f
        for f in (table.get("key_fields", []) or [])
        if _slug(f) not in ("created_at", "updated_at")
    ]
    columns = ",\n    ".join(f"{_slug(f)} {_infer_sql_type(f)}" for f in fields)
    columns_clause = f",\n    {columns}" if columns else ""
    return (
        f"CREATE TABLE IF NOT EXISTS {plural} (\n"
        f"    id INTEGER PRIMARY KEY AUTOINCREMENT{columns_clause}\n"
        f")"
    )


def build_create_index_sql(
    table: dict, all_tables: list[dict] | None = None
) -> list[str]:
    """The table's declared indexes as CREATE INDEX statements, each run
    as its own query right after the CREATE TABLE (kept separate from it
    rather than packing several statements into one sqlx query). Empty
    for a table that declares none."""
    schema = typed_schema.resolve_if_typed(
        all_tables if all_tables is not None else [table]
    )
    return _create_index_sql(table, schema)


def _create_index_sql(
    table: dict, schema: db_schema.ResolvedSchema | None
) -> list[str]:
    rt = typed_schema.typed_table(schema, table)
    if rt is None:
        return []
    plural = f"{_slug(table.get('name', 'item'))}s"
    return [
        f"CREATE {'UNIQUE ' if idx.unique else ''}INDEX IF NOT EXISTS {idx.name} "
        f"ON {plural} ({', '.join(check_expr.sql_identifier(c) for c in idx.columns)})"
        for idx in rt.indexes
    ]


def rust_raw_string(text: str) -> str:
    """`r#"..."#`, with as many #s as it takes for `text` not to close
    it early — SQL with a quoted identifier or a user-written string
    default could otherwise contain the `"#` terminator."""
    hashes = "#"
    while f'"{hashes}' in text:
        hashes += "#"
    return f'r{hashes}"{text}"{hashes}'


def create_tables_block(tables: list[dict]) -> str:
    """The startup statements main.rs runs, one sqlx query each: every
    table's CREATE TABLE followed by its CREATE INDEXes. Shared by the
    actix and axum entry points (REST and GraphQL alike)."""
    schema = typed_schema.resolve_if_typed(tables)
    lines = []
    for t in tables:
        lines.append(
            f"    sqlx::query({rust_raw_string(_create_table_sql(t, schema))})"
            '.execute(&pool).await.expect("failed to create table");'
        )
        for statement in _create_index_sql(t, schema):
            lines.append(
                f"    sqlx::query({rust_raw_string(statement)})"
                '.execute(&pool).await.expect("failed to create index");'
            )
    return "\n".join(lines)


def schema_sql_for_prompt(tables: list[dict], only: dict | None = None) -> str:
    """The exact startup SQL (every table's, or just `only`'s), indented,
    for a prompt. sqlx decodes strictly by column type — a struct field
    that's f64 over a TEXT column fails at runtime, not compile time — so
    the AI has to see the real DDL, not just a field list."""
    schema = typed_schema.resolve_if_typed(tables)
    statements = []
    for t in [only] if only is not None else tables:
        statements.append(_create_table_sql(t, schema) + ";")
        statements += [s + ";" for s in _create_index_sql(t, schema)]
    return "\n".join(f"    {line}" for s in statements for line in s.splitlines())


def view_name(method: str, path: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path.strip("/")).strip("_").lower() or "root"
    return f"{method.lower()}_{slug}"
