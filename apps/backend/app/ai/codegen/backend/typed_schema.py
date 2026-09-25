# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Typed Schema Support for the AI Backend Adapters
#  ai/codegen/backend/typed_schema.py — NOT an adapter itself (same as
#  rust_common.py). The small amount of glue every adapter with a
#  deterministic schema piece (Rails/Laravel migrations, Rust CREATE
#  TABLE SQL, GraphQL SDL type blocks) needs to honor an Architecture
#  table's DECLARED column types, foreign keys, uniques, checks and
#  indexes from ai/db_schema.py.
#
#  The one rule all of them follow: a table that declares nothing
#  (every project saved before typed columns existed) takes the
#  adapter's original code path, untouched, so its output stays byte-
#  for-byte what it always was. Only a table carrying field_specs /
#  foreign_keys / checks / indexes goes through the typed path — and
#  even there, a column with no declared type keeps the adapter's own
#  by-name inference, so the only thing that changes is what the user
#  actually declared.
# ═══════════════════════════════════════════════════════════════

from app.ai import db_schema

# Keys whose presence (non-empty) marks a table as carrying typed info.
# seed_rows deliberately isn't one: seed data changes no column, key or
# constraint, so it never alters a migration / CREATE TABLE here.
_TYPED_KEYS = ("field_specs", "foreign_keys", "checks", "indexes")


def has_typed_info(table: dict) -> bool:
    return any(table.get(key) for key in _TYPED_KEYS)


def resolve(tables: list[dict]) -> db_schema.ResolvedSchema:
    """The lenient resolve — never raises. Anything invalid (a foreign
    key to a missing table, a check naming an unknown field) has already
    been refused by the Architecture editor's own validation; for an
    AI-authored or legacy row, strict=False drops just the broken entry
    instead of failing the whole code generation over it."""
    return db_schema.resolve_schema(tables or [], strict=False)


def resolve_if_typed(tables: list[dict]) -> db_schema.ResolvedSchema | None:
    """resolve() — but None when no table declares anything, so a legacy
    project never even enters db_schema on its way to the old output."""
    if not any(has_typed_info(t) for t in tables or []):
        return None
    return resolve(tables)


def typed_table(
    schema: db_schema.ResolvedSchema | None, table: dict
) -> db_schema.ResolvedTable | None:
    """The resolved table to render typed output from, or None when the
    adapter must take its legacy path (the table declares nothing, or
    its own name is unusable so it didn't resolve at all)."""
    if schema is None or not has_typed_info(table):
        return None
    return schema.table(str(table.get("name") or "").strip())


def uses_resolved_type(col: db_schema.ResolvedColumn | None) -> bool:
    """A declared type always wins; a foreign key column's type is fixed
    by what it references. Everything else keeps the adapter's own
    by-name guess so undeclared output doesn't change."""
    return col is not None and (col.declared or col.fk is not None)


def default_as(col: db_schema.ResolvedColumn, field_type: str) -> dict | None:
    """col.default re-expressed for `field_type` — the type the adapter
    really gives the column. For an undeclared column that's the
    adapter's own by-name guess, which can differ from db_schema's
    (Rails calls "active" a boolean, db_schema a string), and the
    default was only validated against db_schema's. Raises ValueError
    when the value has no faithful form in that type."""
    default = col.default
    if default is None or field_type == col.type:
        # Already canonical for this type — and re-coercing could change
        # it (a JSON default that is the string "123" would parse to 123).
        return default
    kind = default["kind"]
    if kind == "now":
        if field_type != "datetime":
            raise ValueError("a current-time default needs a datetime column")
        return default
    if kind == "today":
        if field_type != "date":
            raise ValueError("a current-date default needs a date column")
        return default
    return {
        "kind": "literal",
        "value": db_schema.coerce_value(default["value"], field_type),
    }


# Types that compare, order and store alike in SQL. A guess within the
# same family as db_schema's type is interchangeable for a check.
_TYPE_FAMILIES = {
    "string": "text",
    "text": "text",
    "integer": "number",
    "float": "number",
    "decimal": "number",
    "boolean": "boolean",
    "date": "temporal",
    "datetime": "temporal",
    "json": "json",
}


def _is_checked(
    schema: db_schema.ResolvedSchema, col: db_schema.ResolvedColumn
) -> bool:
    for table in schema.tables:
        if any(c is col for c in table.columns):
            return any(col.column in chk.fields for chk in table.checks)
    return False


def keeps_guess(
    col: db_schema.ResolvedColumn, guessed_type: str, schema: db_schema.ResolvedSchema
) -> bool:
    """Whether an adapter renders `col` with its own by-name guess
    (`guessed_type`, expressed as a db_schema type). True for every
    undeclared, non-foreign-key column, except where the guess would
    break something the user wrote against db_schema's type instead:
      - a check naming the column, when the guess is a different kind
        of type ("rating BETWEEN 0 AND 5" was type-checked as a number;
        on a column Rails guesses is a string, Postgres rejects the
        migration and SQLite silently compares text);
      - a default the guessed type can't hold (a default of "maybe" on
        a column the adapter guesses is boolean)."""
    if uses_resolved_type(col):
        return False
    if _TYPE_FAMILIES[guessed_type] != _TYPE_FAMILIES[col.type] and _is_checked(
        schema, col
    ):
        return False
    try:
        default_as(col, guessed_type)
    except ValueError:
        return False
    return True


def rendered_default(col: db_schema.ResolvedColumn, field_type: str) -> dict | None:
    """col.default in the form a column rendered as `field_type` needs.
    keeps_guess() already guarantees this converts for a guessed type;
    the fallback (the value as db_schema stored it) only matters for a
    foreign key onto a non-id column whose type came from the column it
    references, where the database itself does the final conversion."""
    try:
        return default_as(col, field_type)
    except ValueError:
        return col.default


def referenced_column(
    schema: db_schema.ResolvedSchema, col: db_schema.ResolvedColumn
) -> db_schema.ResolvedColumn | None:
    """For a foreign key onto a unique NON-id column, that column — so
    the adapter can give the FK column the exact type it gives the
    column it points at (a type mismatch there is a broken FK on some
    databases). None for a plain column or a reference to "id"."""
    if col.fk is None or col.fk.ref_column == "id":
        return None
    ref = schema.table(col.fk.ref_table_sql)
    return ref.column(col.fk.ref_column) if ref else None


def migration_order(tables: list[dict], schema: db_schema.ResolvedSchema) -> list[int]:
    """Indexes into `tables`, in the order their migrations must run so a
    referenced table always exists before the table pointing at it.

    Tables that resolved are placed in db_schema's creation order, but
    only into the slots resolved tables already occupied — anything that
    didn't resolve keeps its position. With no foreign keys the creation
    order IS the list order, so this returns range(len(tables)) and
    every migration keeps the filename it always had."""
    slots: list[int] = []
    index_by_sql: dict[str, int] = {}
    for i, table in enumerate(tables):
        rt = schema.table(str(table.get("name") or "").strip())
        if rt is not None and rt.sql_name not in index_by_sql:
            index_by_sql[rt.sql_name] = i
            slots.append(i)
    ordered = [index_by_sql[s] for s in schema.creation_order if s in index_by_sql]
    order = list(range(len(tables)))
    for slot, original in zip(slots, ordered):
        order[slot] = original
    return order


def referenced_implicit_columns(rt: db_schema.ResolvedTable) -> list[str]:
    """created_at / updated_at named by a check or an index. Every
    generated table has them per db_schema's contract, but an adapter
    whose DDL never created them (the Rust CREATE TABLE) has to add them
    before a constraint can refer to them."""
    used: set[str] = set()
    for chk in rt.checks:
        used.update(chk.fields)
    for idx in rt.indexes:
        used.update(idx.columns)
    return [c for c in ("created_at", "updated_at") if c in used]
