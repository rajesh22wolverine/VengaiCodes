# ═══════════════════════════════════════════════════════════════
#  VengaiCode — SQLite migrations for the deterministic Rust backends
#  ai/migrations_sqlite.py — Renders one revision (bookkeeping, history
#  and safety rules are migrations_gen's) as migrations/NNNN_slug.sql
#  with a `-- migrate:up` and a `-- migrate:down` section, which the
#  generated app's own runner (src/migrate.rs, also written here) embeds
#  and applies at startup.
#
#  Why the app carries its own runner instead of sqlx::migrate!: SQLite
#  can change a column only by rebuilding its table (create the new
#  shape, copy the rows, drop the old table, rename), and with foreign
#  keys ON, dropping a parent table cascade-deletes its children. The
#  switch that prevents that (PRAGMA foreign_keys=OFF) is ignored inside
#  a transaction, and sqlx 0.8's SQLite migrator always opens one (its
#  "-- no-transaction" directive is not honored for SQLite — checked
#  against sqlx-sqlite 0.8.6). The runner switches foreign keys off,
#  applies each migration in its own transaction, runs
#  PRAGMA foreign_key_check, and switches them back on.
#
#  Rendering: a table whose definition changed is rebuilt to its new
#  shape in one step (rows copied; a column that becomes required gets
#  its default where it was NULL); unique constraints are unique
#  indexes, so adding or dropping one never needs a rebuild. down is the
#  same rendering from the new snapshot back to the old one.
#
#  Column types are chosen by the storage class they give a value, since
#  sqlx decodes by the class a value is actually stored as (an f64 can't
#  be read from an INTEGER): decimal is REAL (a NUMERIC column stores
#  12.00 as the integer 12), and dates, date-times and JSON are TEXT, so
#  a value stays exactly as written (a DATE column has NUMERIC affinity).
#  Date-times are UTC text with six fractional digits — the form
#  check_expr writes their CHECK literals in, and the one "now" defaults
#  produce too, so every stored date-time compares correctly as text.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from datetime import date, datetime

from app.ai import check_expr

_SQL_TYPE = {
    "string": lambda col: f"VARCHAR({col['length']})",
    "text": lambda col: "TEXT",
    "integer": lambda col: "INTEGER",
    "float": lambda col: "REAL",
    "decimal": lambda col: "REAL",
    "boolean": lambda col: "BOOLEAN",
    "date": lambda col: "TEXT",
    "datetime": lambda col: "TEXT",
    "json": lambda col: "TEXT",
}
_ON_DELETE = {"cascade": "CASCADE", "set_null": "SET NULL", "restrict": "RESTRICT"}
NEW_PREFIX = "_vc_new_"
# UTC now, as '2024-01-31 09:30:00.123000' (%f is seconds with 3 decimals).
NOW_SQL = "strftime('%Y-%m-%d %H:%M:%f000', 'now')"


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def storage_value(value, field_type: str):
    """A canonical (snapshot) value as the app stores it."""
    if value is None:
        return None
    if field_type == "boolean":
        return 1 if value else 0
    if field_type == "datetime":
        stamp = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", ""))
        )
        return stamp.strftime("%Y-%m-%d %H:%M:%S.%f")
    if field_type == "date":
        return (
            value if isinstance(value, date) else date.fromisoformat(str(value))
        ).isoformat()
    if field_type == "json":
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if field_type == "decimal":
        return float(value)
    return value


def literal(value, field_type: str) -> str:
    stored = storage_value(value, field_type)
    if stored is None:
        return "NULL"
    if isinstance(stored, (int, float)) and not isinstance(stored, bool):
        return repr(stored)
    return "'" + str(stored).replace("'", "''") + "'"


def default_sql(col: dict) -> str | None:
    default = col.get("default")
    if not default:
        return None
    if default["kind"] == "now":
        return NOW_SQL
    if default["kind"] == "today":
        return "CURRENT_DATE"
    return literal(default["value"], col["type"])


def _type(col: dict, tables: dict) -> str:
    if col.get("fk"):
        if col["fk"]["column"] == "id":
            return "INTEGER"
        return _SQL_TYPE[
            tables[col["fk"]["table"]]["columns"][col["fk"]["column"]]["type"]
        ](tables[col["fk"]["table"]]["columns"][col["fk"]["column"]])
    return _SQL_TYPE[col["type"]](col)


def check_sql(table: dict, name: str) -> str:
    types = {c: table["columns"][c]["type"] for c in table["columns"]}
    return check_expr.render_storage_sql(
        table["checks"][name]["ast"], types, quote_all=True
    )


def table_body(table: dict, tables: dict) -> list[str]:
    """Everything inside CREATE TABLE (…) — what a rebuild compares."""
    parts = [f"{q('id')} INTEGER PRIMARY KEY AUTOINCREMENT"]
    for c in table["column_order"]:
        col = table["columns"][c]
        part = f"{q(c)} {_type(col, tables)}"
        if not col["nullable"]:
            part += " NOT NULL"
        default = default_sql(col)
        if default is not None:
            part += (
                f" DEFAULT {default}"
                if default[0] in "'-0123456789N"
                else f" DEFAULT ({default})"
            )
        parts.append(part)
    parts += [
        f"{q('created_at')} TEXT NOT NULL DEFAULT ({NOW_SQL})",
        f"{q('updated_at')} TEXT NOT NULL DEFAULT ({NOW_SQL})",
    ]
    parts += [
        f"CONSTRAINT {q(n)} CHECK ({check_sql(table, n)})" for n in table["checks"]
    ]
    for c in table["column_order"]:
        fk = table["columns"][c]["fk"]
        if fk:
            parts.append(
                f"CONSTRAINT {q(fk['name'])} FOREIGN KEY ({q(c)}) REFERENCES {q(fk['table'])} "
                f"({q(fk['column'])}) ON DELETE {_ON_DELETE[fk['on_delete']]}"
            )
    return parts


def index_statements(t: str, table: dict) -> dict[str, str]:
    """name -> CREATE [UNIQUE] INDEX, for every unique column/index and index."""
    out = {}
    for c in table["column_order"]:
        name = table["columns"][c]["unique"]
        if name:
            out[name] = f"CREATE UNIQUE INDEX {q(name)} ON {q(t)} ({q(c)});"
    for name, idx in table["indexes"].items():
        cols = ", ".join(q(c) for c in idx["columns"])
        out[name] = (
            f"CREATE {'UNIQUE ' if idx['unique'] else ''}INDEX {q(name)} ON {q(t)} ({cols});"
        )
    return out


def _insert(t: str, table: dict, row: dict) -> str:
    keys = [c for c in table["column_order"] if c in row]
    if not keys:
        return f"INSERT INTO {q(t)} DEFAULT VALUES;"
    values = ", ".join(literal(row[k], table["columns"][k]["type"]) for k in keys)
    return f"INSERT INTO {q(t)} ({', '.join(q(k) for k in keys)}) VALUES ({values});"


def _delete(t: str, table: dict, row: dict) -> str:
    # A seed row is identified by its values (except JSON); edited rows stay.
    keys = [
        c
        for c in table["column_order"]
        if c in row and table["columns"][c]["type"] != "json"
    ]
    if not keys:
        return "-- (one seed row has no comparable values, so it is left in place)"
    conditions = [
        f"{q(k)} IS NULL"
        if row[k] is None
        else f"{q(k)} = {literal(row[k], table['columns'][k]['type'])}"
        for k in keys
    ]
    return f"DELETE FROM {q(t)} WHERE {' AND '.join(conditions)};"


def _row_key(row: dict) -> str:
    return json.dumps(row, sort_keys=True)


def steps(old: dict, new: dict) -> list[str]:
    """SQL turning database `old` into database `new`."""
    old_t, new_t = old["tables"], new["tables"]
    old_order = old.get("table_order") or list(old_t)
    new_order = new.get("table_order") or list(new_t)
    out: list[str] = []

    # 1. Seed rows that are gone (while their table still has its old shape).
    for t in old_order:
        if t in new_t:
            keep = {_row_key(r) for r in new_t[t]["seed_rows"]}
            out += [
                _delete(t, old_t[t], r)
                for r in old_t[t]["seed_rows"]
                if _row_key(r) not in keep
            ]

    rebuilt = [
        t
        for t in new_order
        if t in old_t and table_body(old_t[t], old_t) != table_body(new_t[t], new_t)
    ]
    # 2. Indexes that change or go (a rebuilt table loses all of its own).
    for t in old_order:
        if t in new_t and t not in rebuilt:
            new_idx = index_statements(t, new_t[t])
            for name, stmt in index_statements(t, old_t[t]).items():
                if new_idx.get(name) != stmt:
                    out.append(f"DROP INDEX {q(name)};")

    # 3. Tables that go, children first.
    out += [
        f"DROP TABLE {q(t)};"
        for t in reversed(old_order)
        if t in old_t and t not in new_t
    ]

    # 4. New tables, parents first.
    created = [t for t in new_order if t not in old_t]
    for t in created:
        body = table_body(new_t[t], new_t)
        out.append(f"CREATE TABLE {q(t)} (")
        out += [f"    {part}," for part in body[:-1]] + [f"    {body[-1]}", ");"]
        out += list(index_statements(t, new_t[t]).values())

    # 5. Tables whose definition changed: rebuilt to the new shape.
    for t in rebuilt:
        o, n = old_t[t], new_t[t]
        body = table_body(n, new_t)
        copied = (
            ["id"]
            + [c for c in n["column_order"] if c in o["columns"]]
            + ["created_at", "updated_at"]
        )
        exprs = []
        for c in copied:
            col = n["columns"].get(c)
            if (
                col is not None
                and o["columns"][c]["nullable"]
                and not col["nullable"]
                and default_sql(col)
            ):
                exprs.append(f"COALESCE({q(c)}, {default_sql(col)})")
            else:
                exprs.append(q(c))
        out.append(
            f"-- {t}: rebuilt with its new definition (SQLite can't alter a column in place)."
        )
        out.append(f"CREATE TABLE {q(NEW_PREFIX + t)} (")
        out += [f"    {part}," for part in body[:-1]] + [f"    {body[-1]}", ");"]
        out.append(
            f"INSERT INTO {q(NEW_PREFIX + t)} ({', '.join(q(c) for c in copied)}) "
            f"SELECT {', '.join(exprs)} FROM {q(t)};"
        )
        out.append(f"DROP TABLE {q(t)};")
        out.append(f"ALTER TABLE {q(NEW_PREFIX + t)} RENAME TO {q(t)};")
        out += list(index_statements(t, n).values())

    # 6. Indexes that are new or changed on tables kept as they were.
    for t in new_order:
        if t in old_t and t not in rebuilt:
            old_idx = index_statements(t, old_t[t])
            out += [
                stmt
                for name, stmt in index_statements(t, new_t[t]).items()
                if old_idx.get(name) != stmt
            ]

    # 7. Seed rows: every seed of a new table, new seeds of the others.
    for t in new_order:
        if t not in old_t:
            out += [_insert(t, new_t[t], r) for r in new_t[t]["seed_rows"]]
        else:
            had = {_row_key(r) for r in old_t[t]["seed_rows"]}
            out += [
                _insert(t, new_t[t], r)
                for r in new_t[t]["seed_rows"]
                if _row_key(r) not in had
            ]
    return out


def _comment(text: str) -> str:
    return " ".join(str(text).split()).replace("TODO", "to-do")


def filename(rev_id: str, slug: str) -> str:
    return f"backend/migrations/{rev_id}_{slug}.sql"


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
        "Written by VengaiCode from this project's Architecture tables. src/migrate.rs",
        "applies it when the app starts (`cargo run -- revert` undoes the newest). VengaiCode",
        "never rewrites a migration once generated, so it is safe to edit this file by hand.",
    ]
    lines = [f"-- {line}".rstrip() for line in header] + ["", "-- migrate:up"]
    lines += steps(previous_snapshot, snap) or ["-- (no schema changes)"]
    lines += ["", "-- migrate:down"]
    lines += steps(snap, previous_snapshot) or ["-- (no schema changes)"]
    return "\n".join(lines) + "\n"


def runner_rs(revisions: list[dict]) -> str:
    """src/migrate.rs — embeds every migration (include_str!) and applies
    the pending ones with foreign keys off around each transaction."""
    entries = "\n".join(
        f'    ({int(r["id"])}, "{r["slug"]}", include_str!("../migrations/{r["id"]}_{r["slug"]}.sql")),'
        for r in revisions
    )
    return f"""//! Applies this app's database migrations (migrations/*.sql) — written by
//! VengaiCode. Every migration is compiled into the binary, so a packaged app
//! needs no files beside it.
//!
//! SQLite changes a column by rebuilding its table, and with foreign keys ON,
//! dropping a parent table deletes its children. PRAGMA foreign_keys can only
//! change outside a transaction (sqlx's own migrator always opens one), so each
//! migration runs here with foreign keys off around its own transaction.

use sqlx::sqlite::SqlitePool;
use sqlx::{{Connection, Executor}};

/// (version, name, SQL with `-- migrate:up` and `-- migrate:down` sections)
const MIGRATIONS: &[(i64, &str, &str)] = &[
{entries}
];

fn section<'a>(sql: &'a str, name: &str) -> &'a str {{
    let marker = format!("-- migrate:{{name}}");
    let start = sql.find(&marker).map(|i| i + marker.len()).unwrap_or(sql.len());
    let end = sql[start..].find("-- migrate:").map(|i| start + i).unwrap_or(sql.len());
    &sql[start..end]
}}

async fn apply(pool: &SqlitePool, sql: &str, record: &str, version: i64, name: &str) -> Result<(), sqlx::Error> {{
    let mut conn = pool.acquire().await?;
    conn.execute("PRAGMA foreign_keys = OFF").await?;
    let result = async {{
        let mut tx = conn.begin().await?;
        tx.execute(sql).await?;
        sqlx::query(record).bind(version).bind(name).execute(&mut *tx).await?;
        tx.commit().await
    }}
    .await;
    // Foreign keys were off while the tables were rebuilt: report any row that
    // now points at nothing (Postgres would have refused such a migration).
    if result.is_ok() {{
        if let Ok(broken) = sqlx::query("PRAGMA foreign_key_check").fetch_all(&mut *conn).await {{
            if !broken.is_empty() {{
                eprintln!("migration {{version}}: {{}} row(s) point at a row that doesn't exist", broken.len());
            }}
        }}
    }}
    // Back on before the connection returns to the pool, whatever happened.
    conn.execute("PRAGMA foreign_keys = ON").await?;
    result
}}

async fn applied(pool: &SqlitePool) -> Result<Vec<i64>, sqlx::Error> {{
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, \\
         applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    )
    .execute(pool)
    .await?;
    sqlx::query_scalar("SELECT version FROM _migrations ORDER BY version").fetch_all(pool).await
}}

/// Applies every pending migration, oldest first.
pub async fn run(pool: &SqlitePool) -> Result<(), sqlx::Error> {{
    let done = applied(pool).await?;
    for (version, name, sql) in MIGRATIONS {{
        if done.contains(version) {{
            continue;
        }}
        apply(pool, section(sql, "up"), "INSERT INTO _migrations (version, name) VALUES (?, ?)", *version, name).await?;
        println!("applied migration {{version:04}} {{name}}");
    }}
    Ok(())
}}

/// Undoes the newest applied migration (`cargo run -- revert`).
pub async fn revert(pool: &SqlitePool) -> Result<(), sqlx::Error> {{
    let done = applied(pool).await?;
    let Some(newest) = done.last() else {{
        println!("no migration to revert");
        return Ok(());
    }};
    let (version, name, sql) = MIGRATIONS
        .iter()
        .find(|(v, _, _)| v == newest)
        .expect("an applied migration is missing from migrations/");
    apply(pool, section(sql, "down"), "DELETE FROM _migrations WHERE version = ? AND name = ?", *version, name).await?;
    println!("reverted migration {{version:04}} {{name}}");
    Ok(())
}}
"""
