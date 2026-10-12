# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Active Record migrations for the deterministic Rails
#  backend
#  ai/migrations_rails.py — Renders one revision (bookkeeping, history
#  and safety rules are migrations_gen's) as a real Active Record
#  migration, db/migrate/<version>_<name>.rb, in the migration DSL:
#  create_table / add_column / change_column / add_index /
#  add_foreign_key / add_check_constraint and their opposites, with a
#  `down` that is the same rendering of the reverse change.
#
#  Written against the SQLite adapter of the pinned Rails release (its
#  source was read, not assumed):
#    - It changes or removes a column, a foreign key or a check by
#      rebuilding the table, and switches foreign keys off around the
#      rebuild — but SQLite ignores that switch inside a transaction,
#      and Rails runs a SQLite migration inside one. With foreign keys
#      on, dropping the old table deletes the rows that point at it. So
#      every migration here is `disable_ddl_transaction!` and opens its
#      own transaction INSIDE disable_referential_integrity.
#    - ALTER TABLE ADD COLUMN can't take a default that is an expression
#      (now/today): such a column is added bare, filled, then changed to
#      its real definition.
#    - It finds a table's checks again by reading the CREATE TABLE text
#      with a regular expression that counts parentheses, so a check with
#      a parenthesis inside quoted text would be lost at the next rebuild
#      (check_problem — codegen_rails refuses such a check).
#    - remove_foreign_key ignores :name there; it is found by its column.
#
#  Values are stored the way the other SQLite backends store them, so
#  the CHECK literals check_expr writes compare correctly as text:
#  a date-time as UTC text with six fractional digits. Rails itself drops
#  the fraction of a whole-second time, so a date-time default is written
#  as raw SQL here, and the models declare those attributes with a type
#  that always writes six digits (codegen_rails).
#
#  Versions are 20240101000000 + the revision's number: unique, ordered,
#  and the same every time a revision is rendered. Rails also needs every
#  migration CLASS name to be unique, and two revisions can do the same
#  thing ("add books genre") years apart, so the name carries the number.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

from app.ai import db_schema, migrations_sqlite
from app.ai.migrations_sqlite import NOW_SQL, check_sql, default_sql, q

RAILS_MIGRATION_VERSION = "8.1"
_VERSION_EPOCH = 20240101000000

_TYPES = {
    "string": "string",
    "text": "text",
    "integer": "integer",
    "float": "float",
    "decimal": "decimal",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "json": "json",
}
_ON_DELETE = {"cascade": ":cascade", "set_null": ":nullify", "restrict": ":restrict"}
_TIMESTAMPS = ("created_at", "updated_at")


def version(rev_id: str) -> int:
    return _VERSION_EPOCH + int(rev_id)


def name(rev_id: str, slug: str) -> str:
    return "initial_schema" if int(rev_id) == 1 else f"{slug}_{int(rev_id)}"


def filename(rev_id: str, slug: str) -> str:
    return f"backend/db/migrate/{version(rev_id)}_{name(rev_id, slug)}.rb"


def camelize(snake: str) -> str:
    """What Rails (and Zeitwerk) call the constant in a file named `snake`."""
    return "".join(part.capitalize() for part in snake.split("_") if part)


def ruby_str(text: str) -> str:
    """A single-quoted Ruby string: only \\ and ' are special, so nothing
    in user text or SQL can be read as interpolation. "TODO" is split so
    the generated-file check doesn't mistake a table's name for a marker."""
    body = str(text).replace("\\", "\\\\").replace("'", "\\'")
    return "'" + body.replace("TODO", "TO' + 'DO") + "'"


def check_problem(sql: str) -> str | None:
    """Why Rails couldn't carry this check through a table rebuild on
    SQLite, or None."""
    in_text = False
    for ch in sql:
        if ch == "'":
            in_text = not in_text
        elif ch in "()" and in_text:
            return "it has a parenthesis inside quoted text"
    return None


def _base(col: dict, tables: dict) -> dict:
    """A foreign key column has the type of the column it points at."""
    fk = col.get("fk")
    if not fk:
        return col
    if fk["column"] == "id":
        return {"type": "integer", "length": None}
    return _base(tables[fk["table"]]["columns"][fk["column"]], tables)


def _raw(sql: str) -> str:
    """A default written as SQL, exactly as given."""
    return "-> { " + ruby_str(sql) + " }"


def _default(col: dict, kind: str) -> str | None:
    default = col.get("default")
    if not default:
        return None
    if default["kind"] in ("now", "today"):
        return _raw(default_sql(col))
    value = default["value"]
    if kind in ("string", "text"):
        return ruby_str(value)
    if kind == "integer":
        return repr(int(value))
    if kind == "float":
        return repr(float(value))
    if kind == "boolean":
        return "true" if value else "false"
    if kind in ("decimal", "date"):
        return ruby_str(str(value))
    # A date-time or JSON literal: the exact text to store.
    return _raw(migrations_sqlite.literal(value, kind))


def column_args(col: dict, tables: dict, bare: bool = False) -> tuple[str, str]:
    """(the column's Active Record type, its options with a leading ", "
    — or ""). bare: the type alone, nullable and without a default."""
    base = _base(col, tables)
    kind = base["type"]
    options = []
    if kind == "string":
        options.append(f"limit: {base.get('length') or db_schema.STRING_LENGTH}")
    elif kind == "decimal":
        options += [
            f"precision: {db_schema.DECIMAL_PRECISION}",
            f"scale: {db_schema.DECIMAL_SCALE}",
        ]
    elif kind == "datetime":
        options.append("precision: 6")
    if not bare:
        if not col["nullable"]:
            options.append("null: false")
        default = _default(col, kind)
        if default is not None:
            options.append(f"default: {default}")
    return _TYPES[kind], "".join(f", {o}" for o in options)


def _foreign_key(column: str, fk: dict) -> str:
    return (
        f":{fk['table']}, column: :{column}, primary_key: :{fk['column']}, "
        f"on_delete: {_ON_DELETE[fk['on_delete']]}, name: {ruby_str(fk['name'])}"
    )


def _index(columns: list[str], name_: str, unique: bool) -> str:
    cols = ", ".join(f":{c}" for c in columns)
    return f"[{cols}], name: {ruby_str(name_)}" + (", unique: true" if unique else "")


def _seed(statements: list[str]) -> list[str]:
    return [
        f"execute {ruby_str(s.rstrip(';'))}"
        for s in statements
        if not s.startswith("--")
    ]


def _create_table(t: str, table: dict, tables: dict) -> list[str]:
    lines = [f"create_table :{t} do |t|"]
    for c in table["column_order"]:
        col = table["columns"][c]
        kind, options = column_args(col, tables)
        lines.append(f"  t.{kind} :{c}{options}")
    lines += [
        f"  t.datetime :{c}, precision: 6, null: false, default: {_raw(NOW_SQL)}"
        for c in _TIMESTAMPS
    ]
    for c in table["column_order"]:
        col = table["columns"][c]
        if col["unique"]:
            lines.append(f"  t.index {_index([c], col['unique'], True)}")
    for index_name, idx in table["indexes"].items():
        lines.append(f"  t.index {_index(idx['columns'], index_name, idx['unique'])}")
    for c in table["column_order"]:
        fk = table["columns"][c]["fk"]
        if fk:
            lines.append(f"  t.foreign_key {_foreign_key(c, fk)}")
    for check_name in table["checks"]:
        lines.append(
            f"  t.check_constraint {ruby_str(check_sql(table, check_name))}, name: {ruby_str(check_name)}"
        )
    lines.append("end")
    return lines + _seed(
        [migrations_sqlite.insert_sql(t, table, row) for row in table["seed_rows"]]
    )


def _op_lines(op: dict, old: dict, new: dict) -> list[str]:
    kind = op["op"]
    t = op.get("table")
    old_t, new_t = old["tables"], new["tables"]
    if kind == "create_table":
        return _create_table(t, new_t[t], new_t)
    if kind == "drop_table":
        return [f"drop_table :{t}"]
    if kind == "add_column":
        c = op["column"]
        col = new_t[t]["columns"][c]
        type_, options = column_args(col, new_t)
        default = col.get("default")
        if default and default["kind"] in ("now", "today"):
            # SQLite can't add a column whose default is an expression.
            bare_type, bare_options = column_args(col, new_t, bare=True)
            return [
                f"add_column :{t}, :{c}, :{bare_type}{bare_options}",
                f"execute {ruby_str(f'UPDATE {q(t)} SET {q(c)} = {default_sql(col)}')}",
                f"change_column :{t}, :{c}, :{type_}{options}",
            ]
        return [f"add_column :{t}, :{c}, :{type_}{options}"]
    if kind == "drop_column":
        return [f"remove_column :{t}, :{op['column']}"]
    if kind == "alter_column":
        c = op["column"]
        col = new_t[t]["columns"][c]
        type_, options = column_args(col, new_t)
        lines = []
        if not col["nullable"] and old_t[t]["columns"][c]["nullable"]:
            # Rows that have it empty get the default before it is required.
            fill = f"UPDATE {q(t)} SET {q(c)} = {default_sql(col)} WHERE {q(c)} IS NULL"
            lines.append(f"execute {ruby_str(fill)}")
        return lines + [f"change_column :{t}, :{c}, :{type_}{options}"]
    if kind == "add_unique":
        return [f"add_index :{t}, {_index([op['column']], op['name'], True)}"]
    if kind in ("drop_unique", "drop_index"):
        return [f"remove_index :{t}, name: {ruby_str(op['name'])}"]
    if kind == "add_fk":
        c = op["column"]
        return [
            f"add_foreign_key :{t}, {_foreign_key(c, new_t[t]['columns'][c]['fk'])}"
        ]
    if kind == "drop_fk":
        return [f"remove_foreign_key :{t}, column: :{op['column']}"]
    if kind == "add_check":
        expression = check_sql(new_t[t], op["name"])
        return [
            f"add_check_constraint :{t}, {ruby_str(expression)}, name: {ruby_str(op['name'])}"
        ]
    if kind == "drop_check":
        return [f"remove_check_constraint :{t}, name: {ruby_str(op['name'])}"]
    if kind == "add_index":
        idx = new_t[t]["indexes"][op["name"]]
        return [f"add_index :{t}, {_index(idx['columns'], op['name'], idx['unique'])}"]
    if kind == "insert_seed":
        return _seed(
            [migrations_sqlite.insert_sql(t, new_t[t], row) for row in op["rows"]]
        )
    if kind == "delete_seed":
        return _seed(
            [migrations_sqlite.delete_sql(t, old_t[t], row) for row in op["rows"]]
        )
    raise ValueError(f"unknown migration operation {kind!r}")


def _direction(old: dict, new: dict) -> list[str]:
    lines = [
        line
        for op in db_schema.diff_snapshots(old, new)
        for line in _op_lines(op, old, new)
    ]
    return lines or ["# (no schema changes)"]


def _comment(text: str) -> str:
    return " ".join(str(text).split()).replace("TODO", "to-do")


def render_revision(rev: dict, down_id: str | None, previous_snapshot: dict) -> str:
    snap = rev["snapshot"]
    title = (
        "Initial schema"
        if rev["id"] == "0001"
        else (rev.get("summary") or ["No schema changes"])[0]
    )
    header = [_comment(title[:1].upper() + title[1:]), ""]
    header += [f"- {_comment(line)}" for line in rev.get("summary") or []] or [
        "- (no schema changes)"
    ]
    if rev.get("destructive"):
        header += [
            "",
            "Permanently changes existing data (confirmed when it was generated):",
        ]
        header += [f"- {_comment(line)}" for line in rev["destructive"]]
    header += [
        "",
        f"Migration {rev['id']}"
        + (f" (after {down_id})" if down_id else "")
        + f", created {_comment(rev.get('created_at') or '')}.",
        "Written by VengaiCode from this project's Architecture tables. `bin/rails db:migrate`",
        "applies it (`bin/rails db:rollback` undoes the newest). VengaiCode never rewrites a",
        "migration once generated, so it is safe to edit this file by hand.",
    ]
    class_name = camelize(name(rev["id"], rev["slug"]))

    def body(lines: list[str]) -> list[str]:
        return [f"      {line}" for line in lines]

    lines = [
        *[f"# {line}".rstrip() for line in header],
        f"class {class_name} < ActiveRecord::Migration[{RAILS_MIGRATION_VERSION}]",
        "  # SQLite changes a column by rebuilding its table, and with foreign keys on,",
        "  # dropping the old table deletes the rows that point at it. Foreign keys can",
        "  # only be switched off outside a transaction, so this migration opens its own",
        "  # one inside the switch instead of running in Rails' usual one.",
        "  disable_ddl_transaction!",
        "",
        "  def up",
        "    without_foreign_keys do",
        *body(_direction(previous_snapshot, snap)),
        "    end",
        "  end",
        "",
        "  def down",
        "    without_foreign_keys do",
        *body(_direction(snap, previous_snapshot)),
        "    end",
        "  end",
        "",
        "  private",
        "",
        "  def without_foreign_keys(&block)",
        "    connection.disable_referential_integrity { connection.transaction(&block) }",
        "  end",
        "end",
    ]
    return "\n".join(lines) + "\n"
