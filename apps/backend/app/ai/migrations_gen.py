# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Versioned Database Migrations for Generated Apps
#  ai/migrations_gen.py — Turns the deterministic (no-AI) generator's
#  resolved schema into REAL, versioned migrations for the app it
#  writes:
#    - React + FastAPI  -> Alembic revisions (SQLite by default,
#                          Postgres via DATABASE_URL)
#    - Vue + Express    -> migrate-mongo migrations (MongoDB)
#
#  How it works: every generation stores a db_schema.snapshot() of the
#  schema it wrote, one per revision, in codegen_data["migrations"]
#  (the "state" below). The next generation diffs the newest stored
#  snapshot against the current schema (db_schema.diff_snapshots) and,
#  if anything real changed, appends ONE new revision that performs
#  exactly that change — and whose downgrade is the reverse diff. A
#  regeneration with no schema change adds nothing.
#
#  The rules that make this safe to run against a database that already
#  holds real rows:
#    - A revision file is never rewritten. Once written it may already
#      have run against a real database, or been edited by hand, so a
#      later generation carries it over byte for byte from the project's
#      previous files; only a revision that is missing there is rendered
#      again (from its own stored snapshots, so it comes out identical).
#    - Changes no migration can apply to existing rows (a new required
#      field with no default, ...) are refused with the fix to make —
#      db_schema.migration_blockers() -> MigrationError.
#    - Changes that can destroy data (dropping a table or column,
#      changing a column's type) are refused unless the user explicitly
#      confirmed them — DestructiveMigrationError, which the codegen
#      endpoint turns into a 409 the UI can ask about.
#
#  Everything the migrations and the generated model files must agree on
#  (column types, server defaults, constraint names) comes from
#  db_schema.py, so the two can't drift; the SQL rendering below follows
#  the same DDL conventions the model templates use.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.ai import db_schema
from app.ai.codegen_shared import GeneratedFile, js_string_literal

# Added to the generated FastAPI app's requirements.txt. Same version
# VengaiCode's own backend runs (and that the end-to-end tests of this
# module ran the generated migrations with).
MIGRATION_PYTHON_REQUIREMENTS: list[str] = ["alembic==1.13.1"]

# Added to the generated Express app's package.json. migrate-mongo 14.0.7
# is the current release (npm view, 2026-09-24) and declares mongodb as a
# PEER dependency (^4.4.1 || ^5 || ^6 || ^7), so the app has to install
# the driver itself. "~6.20.0" is exactly the range mongoose 8.24.x (what
# the app's "mongoose": "^8.1.1" resolves to today) depends on, so npm
# installs ONE copy of the driver shared by Mongoose and migrate-mongo —
# verified with a real `npm install` of all three, which deduped to a
# single mongodb@6.20.0. migrate-mongo 14 needs Node >= 20.
MIGRATION_NPM_DEPENDENCIES: dict[str, str] = {
    "migrate-mongo": "^14.0.7",
    "mongodb": "~6.20.0",
}

MIGRATION_NPM_SCRIPTS: dict[str, str] = {
    "migrate": "migrate-mongo up",
    "migrate:status": "migrate-mongo status",
    "migrate:down": "migrate-mongo down",
}

_TOOLS = {"fastapi": "alembic", "express": "migrate-mongo"}

_RUN_HINTS = {
    "alembic": (
        "Migrations run automatically every time the backend starts. To run them by hand: "
        "cd backend, then `alembic upgrade head` (undo the newest one: `alembic downgrade -1`; "
        "see where the database is: `alembic current`)."
    ),
    "migrate-mongo": (
        "Migrations run automatically every time the server starts. To run them by hand: "
        "cd backend, then `npm run migrate` (see what has run: `npm run migrate:status`; "
        "undo the newest one: `npm run migrate:down`)."
    ),
}

_SLUG_MAX = 40
_AND_MORE = "_and_more"


class MigrationError(RuntimeError):
    """A schema change no migration can apply safely — the message is
    user-facing and lists every blocker with the fix to make."""


class DestructiveMigrationError(MigrationError):
    """The next migration would permanently change existing data and the
    user hasn't confirmed that. `.changes` lists each such change."""

    def __init__(self, changes: list[str]):
        self.changes = list(changes)
        super().__init__(
            "This regeneration would write a migration that permanently changes existing data:\n"
            + "\n".join(f"• {c}" for c in self.changes)
        )


@dataclass
class MigrationPlan:
    files: list[GeneratedFile]
    state: dict
    new_revision: dict | None = None


# ───────────────────────────────────────────────
#  Public API
# ───────────────────────────────────────────────
def plan_migrations(
    backend: str,
    schema: db_schema.ResolvedSchema,
    previous_state: dict | None,
    previous_files: list[dict],
    allow_destructive: bool = False,
    now_iso: str | None = None,
) -> MigrationPlan:
    """Every migration file the generated app needs (support files plus
    ALL revisions, old ones carried over untouched) and the new state to
    store in codegen_data["migrations"]. Raises MigrationError /
    DestructiveMigrationError (see the module header); ValueError for a
    backend that has no migration support."""
    tool = _TOOLS.get(backend)
    if tool is None:
        raise ValueError(
            f"No migration support for backend {backend!r} (supported: {', '.join(sorted(_TOOLS))})."
        )

    current = db_schema.snapshot(schema)
    created_at = now_iso or datetime.now(timezone.utc).isoformat(timespec="seconds")
    inherited = _usable_revisions(previous_state, backend)
    revisions = list(inherited)
    new_revision = None

    if not revisions:
        # Fresh start (first generation, or the project switched backend):
        # revision 0001 builds the whole schema from nothing. It is written
        # even for an empty schema so the migrations folder always exists.
        new_revision = _make_revision(
            backend, 1, db_schema.empty_snapshot(), current, created_at, destructive=[]
        )
        revisions.append(new_revision)
    else:
        last = revisions[-1]["snapshot"]
        # Snapshots can differ only cosmetically (a table's display label,
        # field order, a check's wording with the same meaning) — that
        # produces no operations and so no migration.
        ops = [] if current == last else db_schema.diff_snapshots(last, current)
        if ops:
            blockers = db_schema.migration_blockers(ops, last, current)
            if blockers:
                raise MigrationError(
                    "This schema change can't be applied to a database that already has rows:\n"
                    + "\n".join(f"• {b}" for b in blockers)
                )
            destructive = db_schema.destructive_changes(ops, last, current)
            if destructive and not allow_destructive:
                raise DestructiveMigrationError(destructive)
            number = int(revisions[-1]["id"]) + 1
            new_revision = _make_revision(
                backend, number, last, current, created_at, destructive=destructive
            )
            revisions.append(new_revision)

    files = _support_files(backend, schema)
    previous_by_path = {_file_attr(f, "path"): f for f in (previous_files or [])}
    inherited_ids = {r["id"] for r in inherited}
    for index, rev in enumerate(revisions):
        prior = (
            previous_by_path.get(rev["filename"])
            if rev["id"] in inherited_ids
            else None
        )
        if prior is not None and isinstance(_file_attr(prior, "content"), str):
            files.append(
                GeneratedFile(
                    path=rev["filename"],
                    language=_file_attr(prior, "language")
                    or _revision_language(backend),
                    content=_file_attr(prior, "content"),
                    description=_file_attr(prior, "description")
                    or _revision_description(rev),
                )
            )
            continue
        previous_snapshot = (
            revisions[index - 1]["snapshot"] if index else db_schema.empty_snapshot()
        )
        down_id = revisions[index - 1]["id"] if index else None
        render = (
            _render_alembic_revision if backend == "fastapi" else _render_mongo_revision
        )
        files.append(
            GeneratedFile(
                path=rev["filename"],
                language=_revision_language(backend),
                content=render(rev, down_id, previous_snapshot),
                description=_revision_description(rev),
            )
        )

    state = {"tool": tool, "backend": backend, "revisions": revisions}
    return MigrationPlan(files=files, state=state, new_revision=new_revision)


def public_migration_info(state: dict | None) -> dict | None:
    """What the API shows about a project's migrations — everything
    except the stored snapshots."""
    if not isinstance(state, dict) or not state.get("revisions"):
        return None
    tool = state.get("tool") or _TOOLS.get(state.get("backend"))
    return {
        "tool": tool,
        "revisions": [
            {
                "id": rev.get("id"),
                "filename": rev.get("filename"),
                "summary": list(rev.get("summary") or []),
                "destructive": list(rev.get("destructive") or []),
                "created_at": rev.get("created_at"),
            }
            for rev in state["revisions"]
            if isinstance(rev, dict)
        ],
        "run_hint": _RUN_HINTS.get(tool, ""),
    }


# ───────────────────────────────────────────────
#  Revision bookkeeping
# ───────────────────────────────────────────────
def _file_attr(f: Any, key: str) -> Any:
    return f.get(key) if isinstance(f, dict) else getattr(f, key, None)


def _usable_revisions(previous_state: dict | None, backend: str) -> list[dict]:
    """The previous state's revisions (deep-copied), or [] when the
    migration history has to start over: no state yet, a different
    backend (an Alembic history means nothing to MongoDB), or a state
    this module didn't write."""
    if not isinstance(previous_state, dict) or previous_state.get("backend") != backend:
        return []
    revisions = previous_state.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        return []
    for expected, rev in enumerate(revisions, start=1):
        if not (
            isinstance(rev, dict)
            and str(rev.get("id") or "").isdigit()
            and int(rev["id"]) == expected
            and isinstance(rev.get("filename"), str)
            and isinstance(rev.get("snapshot"), dict)
            and isinstance(rev["snapshot"].get("tables"), dict)
        ):
            return []
    return copy.deepcopy(revisions)


def _op_slug(op: dict) -> str:
    table, column, name = op.get("table"), op.get("column"), op.get("name")
    return {
        "create_table": f"create_{table}",
        "drop_table": f"drop_{table}",
        "add_column": f"add_{table}_{column}",
        "drop_column": f"drop_{table}_{column}",
        "alter_column": f"alter_{table}_{column}",
        "add_unique": f"unique_{table}_{column}",
        "drop_unique": f"drop_unique_{table}_{column}",
        "add_fk": f"add_fk_{table}_{column}",
        "drop_fk": f"drop_fk_{table}_{column}",
        "add_check": f"add_{name}",
        "drop_check": f"drop_{name}",
        "add_index": f"add_{name}",
        "drop_index": f"drop_{name}",
        "insert_seed": f"seed_{table}",
        "delete_seed": f"unseed_{table}",
    }.get(op["op"], op["op"])


def _revision_slug(number: int, ops: list[dict]) -> str:
    if number == 1:
        return "initial"
    if not ops:
        return "no_changes"
    base = (
        re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]+", "_", _op_slug(ops[0]).lower())).strip(
            "_"
        )
        or "change"
    )
    if len(ops) == 1:
        return base[:_SLUG_MAX].rstrip("_")
    return base[: _SLUG_MAX - len(_AND_MORE)].rstrip("_") + _AND_MORE


def _revision_filename(backend: str, rev_id: str, slug: str) -> str:
    if backend == "fastapi":
        return f"backend/migrations/versions/{rev_id}_{slug}.py"
    return f"backend/migrations/{rev_id}-{slug}.js"


def _revision_language(backend: str) -> str:
    return "python" if backend == "fastapi" else "javascript"


def _revision_description(rev: dict) -> str:
    return f"Database migration {rev['id']} ({rev['slug'].replace('_', ' ')})"


def _make_revision(
    backend: str,
    number: int,
    old: dict,
    new: dict,
    created_at: str,
    destructive: list[str],
) -> dict:
    ops = db_schema.diff_snapshots(old, new)
    rev_id = f"{number:04d}"
    slug = _revision_slug(number, ops)
    return {
        "id": rev_id,
        "slug": slug,
        "filename": _revision_filename(backend, rev_id, slug),
        "snapshot": copy.deepcopy(new),
        "summary": [db_schema.describe_op(op, old, new) for op in ops],
        "destructive": list(destructive),
        "created_at": created_at,
    }


def _revision_title(rev: dict) -> str:
    if rev["id"] == "0001":
        return "Initial schema"
    summary = rev.get("summary") or []
    if not summary:
        return "No schema changes"
    head = summary[0][:1].upper() + summary[0][1:]
    return head if len(summary) == 1 else f"{head} (and {len(summary) - 1} more)"


def _one_line(text: str) -> str:
    # Seed values and check literals can contain newlines / Unicode line
    # separators; a comment or docstring line must stay one line.
    return re.sub(r"[\s  ]+", " ", str(text)).strip()


# ═══════════════════════════════════════════════
#  Alembic (FastAPI / SQLAlchemy)
# ═══════════════════════════════════════════════
_ON_DELETE_SQL = {"cascade": "CASCADE", "set_null": "SET NULL", "restrict": "RESTRICT"}

# Postgres spelling of each column type, for ALTER COLUMN ... TYPE ...
# USING col::<type>. Postgres refuses most type changes without an
# explicit USING cast; SQLite's batch mode casts while copying instead.
_PG_TYPES = {
    "text": "TEXT",
    "integer": "INTEGER",
    "float": "FLOAT",
    "decimal": f"NUMERIC({db_schema.DECIMAL_PRECISION}, {db_schema.DECIMAL_SCALE})",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "datetime": "TIMESTAMP WITH TIME ZONE",
    "json": "JSON",
}

_IMPLICIT_SA_COLUMNS = (
    'sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True)',
    'sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True)',
    'sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True)',
)


def _q(text: str) -> str:
    # json.dumps output is always a valid Python string literal with the
    # same value (every JSON escape is also a Python escape).
    return json.dumps(text)


def _pg_type(col: dict) -> str:
    if col["type"] == "string":
        return f"VARCHAR({col.get('length') or db_schema.STRING_LENGTH})"
    return _PG_TYPES[col["type"]]


class _PyRenderer:
    """Renders snapshot-diff operations as Alembic op.* calls. Steps are
    ("top", lines) or ("batch", table, lines); consecutive batch steps on
    one table share a single `with op.batch_alter_table(...)` block."""

    def __init__(self) -> None:
        self.imports: set[str] = set()

    # ── values ──
    def literal(self, value: Any, field_type: str) -> str:
        if field_type == "decimal":
            self.imports.add("from decimal import Decimal")
        elif field_type == "date":
            self.imports.add("from datetime import date")
        elif field_type == "datetime":
            self.imports.add("from datetime import datetime")
        if field_type == "json":
            return _py_json_literal(value)
        if isinstance(value, float) and not math.isfinite(value):
            return f'float("{value}")'
        return db_schema.python_literal(value, field_type)

    def default_value(self, col: dict) -> str:
        default = col["default"]
        if default["kind"] == "now":
            return "sa.func.now()"
        if default["kind"] == "today":
            return "sa.func.current_date()"
        return self.literal(default["value"], col["type"])

    # ── definitions ──
    @staticmethod
    def column_code(name: str, col: dict, nullable: bool | None = None) -> str:
        parts = [
            _q(name),
            db_schema.sa_type_code(col),
            f"nullable={col['nullable'] if nullable is None else nullable}",
        ]
        default = db_schema.sa_server_default_code(col)
        if default is not None:
            parts.append(f"server_default={default}")
        return f"sa.Column({', '.join(parts)})"

    @staticmethod
    def fk_constraint_code(column: str, fk: dict) -> str:
        return (
            f"sa.ForeignKeyConstraint([{_q(column)}], [{_q(fk['table'] + '.' + fk['column'])}], "
            f'name={_q(fk["name"])}, ondelete="{_ON_DELETE_SQL[fk["on_delete"]]}")'
        )

    def lightweight_table(
        self, table: str, columns: list[tuple[str, dict]]
    ) -> list[str]:
        """`table_ = sa.table(...)` with typed columns, so values bind as
        the right type (dates, decimals, JSON) on every database."""
        lines = ["table_ = sa.table(", f"    {_q(table)},"]
        lines += [
            f"    sa.column({_q(name)}, {db_schema.sa_type_code(col)}),"
            for name, col in columns
        ]
        lines.append(")")
        return lines

    def row_literal(self, row: dict, columns: dict, order: list[str]) -> str:
        keys = [k for k in order if k in row]
        return (
            "{"
            + ", ".join(
                f"{_q(k)}: {self.literal(row[k], columns[k]['type'])}" for k in keys
            )
            + "}"
        )

    def seed_lines(
        self, rows: list[dict], columns: dict, order: list[str]
    ) -> list[str]:
        """op.bulk_insert() for runs of rows that set the same fields
        (executemany needs one shape per call; a field a row leaves out
        must get its SERVER default, not NULL), in the original order."""
        lines: list[str] = []
        groups: list[tuple[frozenset, list[dict]]] = []
        for row in rows:
            keys = frozenset(row)
            if groups and groups[-1][0] == keys:
                groups[-1][1].append(row)
            else:
                groups.append((keys, [row]))
        for keys, group in groups:
            if not keys:
                lines += ["op.execute(table_.insert().values({}))"] * len(group)
                continue
            lines += ["op.bulk_insert(", "    table_,", "    ["]
            lines += [
                f"        {self.row_literal(row, columns, order)}," for row in group
            ]
            lines += ["    ],", ")"]
        return lines

    # ── operations ──
    def steps(self, ops: list[dict], old: dict, new: dict) -> list[tuple]:
        out: list[tuple] = []
        for op in ops:
            out.extend(self.op_steps(op, old, new))
        return out

    def op_steps(self, op: dict, old: dict, new: dict) -> list[tuple]:
        kind, t = op["op"], op["table"]
        if kind == "create_table":
            return self.create_table(t, new["tables"][t])
        if kind == "drop_table":
            return [("top", [f"op.drop_table({_q(t)})"])]
        if kind == "add_column":
            col = new["tables"][t]["columns"][op["column"]]
            if not col["nullable"] and col["default"] is None:
                # Only reachable in a downgrade that restores a dropped
                # required field (an upgrade like this is refused outright).
                return [
                    (
                        "batch",
                        t,
                        [
                            "# Restored as optional: its old values are gone and there is no default to refill it with.",
                            f"batch_op.add_column({self.column_code(op['column'], col, nullable=True)})",
                        ],
                    )
                ]
            return [
                (
                    "batch",
                    t,
                    [f"batch_op.add_column({self.column_code(op['column'], col)})"],
                )
            ]
        if kind == "drop_column":
            return [("batch", t, [f"batch_op.drop_column({_q(op['column'])})"])]
        if kind == "alter_column":
            return self.alter_column(
                t,
                op["column"],
                op["changes"],
                old["tables"][t]["columns"][op["column"]],
                new["tables"][t]["columns"][op["column"]],
            )
        if kind == "add_unique":
            return [
                (
                    "batch",
                    t,
                    [
                        f"batch_op.create_unique_constraint({_q(op['name'])}, [{_q(op['column'])}])"
                    ],
                )
            ]
        if kind == "drop_unique":
            return [
                (
                    "batch",
                    t,
                    [f'batch_op.drop_constraint({_q(op["name"])}, type_="unique")'],
                )
            ]
        if kind == "add_fk":
            fk = new["tables"][t]["columns"][op["column"]]["fk"]
            return [
                (
                    "batch",
                    t,
                    [
                        f"batch_op.create_foreign_key({_q(fk['name'])}, {_q(fk['table'])}, [{_q(op['column'])}], "
                        f'[{_q(fk["column"])}], ondelete="{_ON_DELETE_SQL[fk["on_delete"]]}")'
                    ],
                )
            ]
        if kind == "drop_fk":
            return [
                (
                    "batch",
                    t,
                    [f'batch_op.drop_constraint({_q(op["name"])}, type_="foreignkey")'],
                )
            ]
        if kind == "add_check":
            chk = new["tables"][t]["checks"][op["name"]]
            return [
                (
                    "batch",
                    t,
                    [
                        f"batch_op.create_check_constraint({_q(op['name'])}, {chk['sql']!r})"
                    ],
                )
            ]
        if kind == "drop_check":
            return [
                (
                    "batch",
                    t,
                    [f'batch_op.drop_constraint({_q(op["name"])}, type_="check")'],
                )
            ]
        if kind == "add_index":
            idx = new["tables"][t]["indexes"][op["name"]]
            return [("top", [self.create_index_code(t, op["name"], idx)])]
        if kind == "drop_index":
            return [("top", [f"op.drop_index({_q(op['name'])}, table_name={_q(t)})"])]
        if kind == "insert_seed":
            ts = new["tables"][t]
            return [("top", self.insert_rows(t, op["rows"], ts))]
        if kind == "delete_seed":
            return [("top", self.delete_rows(t, op["rows"], old["tables"][t]))]
        raise ValueError(f"Unknown migration operation {kind!r}")

    @staticmethod
    def create_index_code(table: str, name: str, idx: dict) -> str:
        columns = ", ".join(_q(c) for c in idx["columns"])
        return f"op.create_index({_q(name)}, {_q(table)}, [{columns}], unique={bool(idx['unique'])})"

    def create_table(self, t: str, ts: dict) -> list[tuple]:
        columns = ts["columns"]
        lines = [
            f"{'table_ = ' if ts['seed_rows'] else ''}op.create_table(",
            f"    {_q(t)},",
        ]
        lines.append(f"    {_IMPLICIT_SA_COLUMNS[0]},")
        lines += [f"    {self.column_code(c, columns[c])}," for c in ts["column_order"]]
        lines += [f"    {code}," for code in _IMPLICIT_SA_COLUMNS[1:]]
        lines += [
            f"    {self.fk_constraint_code(c, columns[c]['fk'])},"
            for c in ts["column_order"]
            if columns[c]["fk"]
        ]
        lines += [
            f"    sa.UniqueConstraint({_q(c)}, name={_q(columns[c]['unique'])}),"
            for c in ts["column_order"]
            if columns[c]["unique"]
        ]
        lines += [
            f"    sa.CheckConstraint({chk['sql']!r}, name={_q(name)}),"
            for name, chk in ts["checks"].items()
        ]
        lines.append(")")
        steps: list[tuple] = [("top", lines)]
        for name, idx in ts["indexes"].items():
            steps.append(("top", [self.create_index_code(t, name, idx)]))
        if ts["seed_rows"]:
            steps.append(
                ("top", self.seed_lines(ts["seed_rows"], columns, ts["column_order"]))
            )
        return steps

    def insert_rows(self, t: str, rows: list[dict], ts: dict) -> list[str]:
        used = [c for c in ts["column_order"] if any(c in row for row in rows)]
        return self.lightweight_table(
            t, [(c, ts["columns"][c]) for c in used]
        ) + self.seed_lines(rows, ts["columns"], ts["column_order"])

    def delete_rows(self, t: str, rows: list[dict], ts: dict) -> list[str]:
        # A seed row is identified by its values: every field the seed set
        # (except JSON, which Postgres can't compare with "="). So a seed
        # row someone has since edited in the app is left alone, and an
        # app-created row that happens to hold exactly the same values is
        # removed with it — the closest a row without a stable key allows.
        columns = ts["columns"]
        used = [
            c
            for c in ts["column_order"]
            if columns[c]["type"] != "json" and any(c in row for row in rows)
        ]
        lines = [
            "# Removes each seed row that no longer exists in the design, matched on",
            "# every value it was seeded with (edited rows are left alone).",
        ]
        lines += self.lightweight_table(t, [(c, columns[c]) for c in used])
        for row in rows:
            keys = [c for c in used if c in row]
            if not keys:
                lines.append(
                    "# (one seed row has no comparable values, so it is left in place)"
                )
                continue
            conditions = ", ".join(
                f"table_.c[{_q(c)}] == {self.literal(row[c], columns[c]['type'])}"
                for c in keys
            )
            lines.append(f"op.execute(table_.delete().where({conditions}))")
        return lines

    def alter_column(
        self, t: str, column: str, changes: dict, old_col: dict, new_col: dict
    ) -> list[tuple]:
        steps: list[tuple] = []
        old_default = db_schema.sa_server_default_code(old_col)
        new_default = db_schema.sa_server_default_code(new_col)
        current_type = db_schema.sa_type_code(old_col)
        current_default = old_default
        type_change = "type" in changes or "length" in changes
        if type_change:
            args = [
                _q(column),
                f"existing_type={current_type}",
                f"type_={db_schema.sa_type_code(new_col)}",
                f"existing_nullable={old_col['nullable']}",
            ]
            if old_default is not None:
                # The old default goes first: Postgres re-casts a column's
                # default along with its type and fails if it can't.
                args += [
                    f"existing_server_default={old_default}",
                    "server_default=None",
                ]
                current_default = None
            if "type" in changes:
                ident = db_schema.check_expr.sql_identifier(column)
                args.append(f"postgresql_using={_q(f'{ident}::{_pg_type(new_col)}')}")
            steps.append(("batch", t, [f"batch_op.alter_column({', '.join(args)})"]))
            current_type = db_schema.sa_type_code(new_col)

        becomes_required = "nullable" in changes and changes["nullable"][1] is False
        if becomes_required and new_col["default"] is not None:
            lines = [
                f"# Rows that already exist get the default before {_q(column)} becomes required."
            ]
            lines += self.lightweight_table(t, [(column, new_col)])
            lines.append(
                f"op.execute(table_.update().where(table_.c[{_q(column)}].is_(None))"
                f".values({{{_q(column)}: {self.default_value(new_col)}}}))"
            )
            steps.append(("top", lines))

        args = []
        comment = []
        if "nullable" in changes:
            if becomes_required and new_col["default"] is None:
                # Only reachable in a downgrade (the upgrade is refused
                # outright): rows written since may have no value here.
                comment.append(
                    f"# {_q(column)} stays optional: rows written since the upgrade may have no value for it."
                )
            else:
                args.append(f"nullable={new_col['nullable']}")
        if new_default != current_default:
            args.append(
                f"server_default={new_default if new_default is not None else 'None'}"
            )
        if args:
            head = [
                _q(column),
                f"existing_type={current_type}",
                f"existing_nullable={old_col['nullable']}",
            ]
            if current_default is not None:
                head.append(f"existing_server_default={current_default}")
            steps.append(
                (
                    "batch",
                    t,
                    comment + [f"batch_op.alter_column({', '.join(head + args)})"],
                )
            )
        elif comment:
            steps.append(("top", comment))
        return steps


def _py_json_literal(value: Any) -> str:
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(
                f"{_q(str(k))}: {_py_json_literal(v)}" for k, v in value.items()
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ", ".join(_py_json_literal(v) for v in value) + "]"
    if isinstance(value, float) and not math.isfinite(value):
        return f'float("{value}")'
    if isinstance(value, str):
        return _q(value)
    return repr(value)


def _assemble_py(steps: list[tuple]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(steps):
        if out:
            out.append("")
        if steps[i][0] == "batch":
            table = steps[i][1]
            block: list[str] = []
            while i < len(steps) and steps[i][0] == "batch" and steps[i][1] == table:
                block.extend(steps[i][2])
                i += 1
            out.append(f"with op.batch_alter_table({_q(table)}) as batch_op:")
            out.extend(f"    {line}" for line in block)
        else:
            out.extend(steps[i][1])
            i += 1
    return out or ["pass"]


def _py_docstring_line(text: str) -> str:
    return _one_line(text).replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def _render_alembic_revision(
    rev: dict, down_id: str | None, previous_snapshot: dict
) -> str:
    snap = rev["snapshot"]
    renderer = _PyRenderer()
    upgrade = _assemble_py(
        renderer.steps(
            db_schema.diff_snapshots(previous_snapshot, snap), previous_snapshot, snap
        )
    )
    downgrade = _assemble_py(
        renderer.steps(
            db_schema.diff_snapshots(snap, previous_snapshot), snap, previous_snapshot
        )
    )

    doc = [_py_docstring_line(_revision_title(rev)), ""]
    doc += [f"- {_py_docstring_line(line)}" for line in rev.get("summary") or []] or [
        "- (no schema changes)"
    ]
    if rev.get("destructive"):
        doc += [
            "",
            "Permanently changes existing data (confirmed when it was generated):",
        ]
        doc += [f"- {_py_docstring_line(line)}" for line in rev["destructive"]]
    doc += [
        "",
        f"Revision ID: {rev['id']}",
        f"Revises: {down_id or ''}".rstrip(),
        f"Create Date: {_py_docstring_line(rev.get('created_at') or '')}",
        "",
        "Written by VengaiCode from this project's Architecture tables. VengaiCode",
        "never rewrites a revision once it has been generated (every later schema",
        "change arrives as a NEW revision), because it may already have run against",
        "a real database — so it is safe to edit this file by hand; your edits are",
        "kept on every regeneration.",
    ]
    stdlib = sorted(i for i in renderer.imports)
    header = ['"""' + doc[0]] + doc[1:] + ['"""', ""]
    if stdlib:
        header += stdlib + [""]
    header += [
        "import sqlalchemy as sa",
        "from alembic import op",
        "",
        "# revision identifiers, used by Alembic.",
        f"revision = {_q(rev['id'])}",
        f"down_revision = {_q(down_id) if down_id else 'None'}",
        "branch_labels = None",
        "depends_on = None",
        "",
        "",
        "def upgrade() -> None:",
    ]
    body = header + [f"    {line}" if line else "" for line in upgrade]
    body += ["", "", "def downgrade() -> None:"]
    body += [f"    {line}" if line else "" for line in downgrade]
    return "\n".join(body) + "\n"


def _alembic_ini() -> str:
    return """# Alembic configuration for this app, written by VengaiCode.
#
# Migrations run automatically every time the backend starts (see
# app/core/migrate.py), so this file is only needed to run Alembic by hand,
# from this backend/ folder:
#   alembic upgrade head      apply every pending migration
#   alembic downgrade -1      undo the newest migration
#   alembic current           show which revision the database is at
#
# There is deliberately no sqlalchemy.url here: migrations/env.py uses
# DATABASE_URL from app/core/database.py (which reads the DATABASE_URL
# environment variable), so the app and its migrations can never point at
# two different databases.

[alembic]
script_location = migrations
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""


def _alembic_env_py(schema: db_schema.ResolvedSchema) -> str:
    model_imports = "\n".join(
        f"import models.{t.slug}  # noqa: E402,F401" for t in schema.tables
    )
    return f'''"""Alembic environment for this app, written by VengaiCode.

Runs the versioned scripts in migrations/versions/ — at every startup via
app/core/migrate.py, or by hand with the `alembic` command (see alembic.ini).
"""

import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import event, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import DATABASE_URL, Base

# Every model module, so Base.metadata describes every table. Only
# `alembic revision --autogenerate` reads it; upgrading runs the versioned
# scripts, never the models.
{model_imports}

config = context.config

# Only when run through alembic.ini; at app startup there is no ini file,
# and the app's own logging setup is left alone.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
logger = logging.getLogger("alembic.env")


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={{"paramstyle": "named"}},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _warn_about_orphaned_rows(connection: Connection) -> None:
    # Foreign keys are off while migrating on SQLite (see below), so a
    # migration that adds a foreign key to rows pointing at nothing
    # succeeds there — where Postgres would refuse it. Say so instead of
    # staying silent.
    for table, rowid, parent, _fk in connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
        logger.warning("%s row %s points at a %s row that doesn't exist", table, rowid, parent)


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
    if connection.dialect.name == "sqlite":
        _warn_about_orphaned_rows(connection)


async def run_async_migrations() -> None:
    # Its own short-lived engine (NullPool: nothing is kept open after the
    # migration), deliberately NOT the app's engine from app/core/database.py.
    connectable = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)

    if connectable.dialect.name == "sqlite":
        # SQLite can't ALTER most things, so batch mode rebuilds a table:
        # copy it, DROP the original, rename the copy. With foreign keys
        # ON, that DROP would fire every ON DELETE CASCADE / SET NULL
        # pointing at the table and wipe or orphan the child rows. Foreign
        # keys are off by default on a new SQLite connection (the app's
        # engine switches them on); this makes the migration connection's
        # setting explicit rather than accidental.
        @event.listens_for(connectable.sync_engine, "connect")
        def _foreign_keys_off(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.close()

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''


# Alembic's own standard revision template (identical in its "generic"
# and "async" templates), so `alembic revision --autogenerate` keeps
# working for anyone who wants to write their own migrations later.
_SCRIPT_PY_MAKO = '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''

_MIGRATE_PY = '''"""Brings the database up to date — main.py calls run_migrations() once at
startup, before the app serves any request. Written by VengaiCode.

The schema is owned by the versioned Alembic scripts in migrations/versions/
(not by Base.metadata.create_all), so an existing database is upgraded in
place — its rows kept — whenever the app's tables change.
"""

import os
import sys

from alembic import command
from alembic.config import Config


def _backend_dir() -> str:
    # A PyInstaller one-file build unpacks its bundled files (the
    # migrations/ folder included) into sys._MEIPASS; otherwise this file
    # is backend/app/core/migrate.py, two folders below backend/.
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return bundled
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_migrations() -> None:
    """`alembic upgrade head`, without needing alembic.ini or a particular
    working directory. Blocking, and migrations/env.py runs its own event
    loop — so call it from a worker thread (main.py uses asyncio.to_thread),
    never directly on a running event loop."""
    backend_dir = _backend_dir()
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    config = Config()
    # Alembic reads options through ConfigParser, where "%" is special.
    config.set_main_option("script_location", os.path.join(backend_dir, "migrations").replace("%", "%%"))
    command.upgrade(config, "head")
'''


# ═══════════════════════════════════════════════
#  migrate-mongo (Express / Mongoose / MongoDB)
# ═══════════════════════════════════════════════
_BRACKETS_OPEN = "{(["
_BRACKETS_CLOSE = "})]"

# $convert targets when a column's stored type changes.
_MONGO_CONVERT_TO = {
    "string": "string",
    "text": "string",
    "integer": "long",
    "float": "double",
    "decimal": "double",
    "boolean": "bool",
    "date": "date",
    "datetime": "date",
}


def _balanced(text: str) -> bool:
    return sum(text.count(c) for c in _BRACKETS_OPEN) == sum(
        text.count(c) for c in _BRACKETS_CLOSE
    )


def _js_str(text: str) -> str:
    """A JS string literal. Brackets inside a user's value are written as
    \\u escapes when they don't pair up, and "TODO" is split the same way:
    identical string at runtime, but the file still passes VengaiCode's
    generated-file sanity check (balanced brackets, no TODO markers)."""
    return js_string_literal(text)


def _js_comment(text: str) -> str:
    line = _one_line(text).replace("TODO", "to-do")
    if not _balanced(line):
        line = re.sub(r"[{}()\[\]]", "", line)
    return line


def _js_json(value: Any) -> str:
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(f"{_js_str(str(k))}: {_js_json(v)}" for k, v in value.items())
            + " }"
            if value
            else "{}"
        )
    if isinstance(value, list):
        return "[" + ", ".join(_js_json(v) for v in value) + "]"
    if isinstance(value, str):
        return _js_str(value)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value)  # numbers; inf/nan become Infinity/NaN, both valid JS


def _js_date(value: str, field_type: str) -> str:
    if field_type == "date":
        # A date-only ISO string is parsed as UTC midnight by every JS engine.
        return f"new Date({json.dumps(str(value)[:10])})"
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        # Naive date-times are treated as UTC, never the server's local zone.
        stamp = stamp.replace(tzinfo=timezone.utc)
    utc = stamp.astimezone(timezone.utc)
    return f'new Date("{utc.strftime("%Y-%m-%dT%H:%M:%S")}.{utc.microsecond // 1000:03d}Z")'


def _js_value(value: Any, field_type: str) -> str:
    if value is None:
        return "null"
    if field_type in ("date", "datetime"):
        return _js_date(value, field_type)
    if field_type == "decimal":
        return json.dumps(float(Decimal(str(value))))
    if field_type in ("string", "text"):
        return _js_str(value)
    return _js_json(value)


def _bson_type(col: dict) -> str | None:
    """How a column is stored by the generated Mongoose models."""
    if col.get("fk") and col["fk"].get("column") == "id":
        return "objectId"  # a reference to another document's _id
    return {
        "string": "string",
        "text": "string",
        "integer": "number",
        "float": "number",
        "decimal": "number",
        "boolean": "bool",
        "date": "date",
        "datetime": "date",
    }.get(col["type"])


_MONGO_IMPLICIT_BSON = {"id": "objectId", "created_at": "date", "updated_at": "date"}


def _mongo_field(column: str) -> str:
    # The implicit "id" is Mongoose's virtual over the real _id field.
    return "_id" if column == "id" else column


def _mongo_validator(ts: dict) -> dict:
    """A $jsonSchema validator mirroring the table's columns: types,
    string lengths, required (NOT NULL) fields, and no fields beyond the
    declared ones plus the four Mongoose manages itself — the MongoDB
    equivalent of a table's column list. Check constraints and foreign
    keys aren't expressible here; the Mongoose models enforce those."""
    properties: dict[str, dict] = {"_id": {"bsonType": "objectId"}}
    required: list[str] = []
    for name in ts["column_order"]:
        col = ts["columns"][name]
        bson = _bson_type(col)
        prop: dict[str, Any] = {}
        if bson:
            prop["bsonType"] = [bson, "null"] if col["nullable"] else bson
        elif not col["nullable"]:
            prop["not"] = {"bsonType": "null"}
        if col["type"] == "string" and col.get("length"):
            prop["maxLength"] = col["length"]
        properties[name] = prop
        if not col["nullable"]:
            required.append(name)
    properties["created_at"] = {"bsonType": ["date", "null"]}
    properties["updated_at"] = {"bsonType": ["date", "null"]}
    properties["__v"] = {"bsonType": "number"}
    schema: dict[str, Any] = {"bsonType": "object"}
    if required:
        schema["required"] = required
    schema["properties"] = properties
    schema["additionalProperties"] = False
    return {"$jsonSchema": schema}


def _mongo_unique_specs(ts: dict) -> dict[str, tuple[dict, dict]]:
    """name -> (keys, options) for every unique index a table needs. The
    partial filter indexes only documents where every field holds a real
    value, so documents with the field missing or null never collide —
    exactly how SQL UNIQUE treats NULL."""
    specs: dict[str, tuple[dict, dict]] = {}

    def bson(col_name: str) -> str | None:
        if col_name in _MONGO_IMPLICIT_BSON:
            return _MONGO_IMPLICIT_BSON[col_name]
        return _bson_type(ts["columns"][col_name])

    for name in ts["column_order"]:
        col = ts["columns"][name]
        if col["unique"]:
            specs[col["unique"]] = (
                {name: 1},
                {
                    "name": col["unique"],
                    "unique": True,
                    "partialFilterExpression": {name: {"$type": bson(name)}},
                },
            )
    for idx_name, idx in ts["indexes"].items():
        if idx["unique"]:
            fields = [_mongo_field(c) for c in idx["columns"]]
            specs[idx_name] = (
                {f: 1 for f in fields},
                {
                    "name": idx_name,
                    "unique": True,
                    "partialFilterExpression": {
                        f: {"$type": bson(c)} for f, c in zip(fields, idx["columns"])
                    },
                },
            )
    return specs


def mongo_index_specs(ts: dict) -> list[tuple[dict, dict]]:
    """(keys, options) for every index a table's collection gets — the
    unique ones first, as the migrations create them. The generated
    Mongoose model declares exactly these (autoIndex is off, so purely as
    documentation of what the migrations built)."""
    specs = list(_mongo_unique_specs(ts).values())
    for name, idx in ts["indexes"].items():
        if not idx["unique"]:
            specs.append(({_mongo_field(c): 1 for c in idx["columns"]}, {"name": name}))
    return specs


def js_json_literal(value: Any) -> str:
    """A JSON value as JS source, user strings escaped like _js_str."""
    return _js_json(value)


def js_value_literal(value: Any, field_type: str) -> str:
    """A canonical column value as JS source — dates as UTC Date objects,
    decimals as numbers — the way the migrations write seed documents."""
    return _js_value(value, field_type)


_MONGO_HELPERS = {
    "collectionExists": """async function collectionExists(db, name) {
  const matches = await db.listCollections({ name }, { nameOnly: true }).toArray();
  return matches.length > 0;
}""",
    "applyValidator": """// Creates the collection with its validator — or, when it already exists
// (e.g. documents this app saved before it had migrations), updates the
// validator in place. "moderate" validates every insert, and every update to
// a document that already passes, without making older documents
// impossible to update.
async function applyValidator(db, name, validator) {
  if (await collectionExists(db, name)) {
    await db.command({ collMod: name, validator, validationLevel: 'moderate' });
  } else {
    await db.createCollection(name, { validator, validationLevel: 'moderate' });
  }
}""",
    "dropCollection": """async function dropCollection(db, name) {
  if (await collectionExists(db, name)) {
    await db.collection(name).drop();
  }
}""",
    "dropIndex": """async function dropIndex(db, collection, name) {
  if (!(await collectionExists(db, collection))) return;
  const indexes = await db.collection(collection).indexes();
  if (indexes.some((index) => index.name === name)) {
    await db.collection(collection).dropIndex(name);
  }
}""",
}

_MONGO_HELPER_DEPENDENCIES = {
    "applyValidator": ["collectionExists"],
    "dropCollection": ["collectionExists"],
    "dropIndex": ["collectionExists"],
}


class _JsRenderer:
    def __init__(self) -> None:
        self.helpers: set[str] = set()

    def use(self, helper: str) -> str:
        self.helpers.add(helper)
        for dep in _MONGO_HELPER_DEPENDENCIES.get(helper, []):
            self.helpers.add(dep)
        return helper

    def body(self, ops: list[dict], old: dict, new: dict) -> list[str]:
        self.uses_now = False
        self.uses_today = False
        lines: list[str] = []
        validated: set[str] = set()
        touched_indexes: set[tuple[str, str]] = set()

        def ensure_validator(t: str) -> None:
            if t in validated:
                return
            validated.add(t)
            before = old["tables"].get(t)
            after = new["tables"].get(t)
            if after is not None and (
                before is None or _mongo_validator(before) != _mongo_validator(after)
            ):
                lines.extend(self.apply_validator(t, after))

        for op in ops:
            kind, t = op["op"], op["table"]
            if kind == "create_table":
                validated.add(t)
                lines.extend(self.create_table(t, new["tables"][t]))
            elif kind == "drop_table":
                lines.append(f"await {self.use('dropCollection')}(db, {_js_str(t)});")
            elif kind in (
                "add_column",
                "drop_column",
                "alter_column",
                "add_fk",
                "drop_fk",
            ):
                ensure_validator(t)
                lines.extend(self.column_op(op, old, new))
            elif kind in ("add_unique", "add_index"):
                touched_indexes.add((t, op["name"]))
                spec = self.index_spec(new["tables"][t], op["name"])
                if spec is not None:
                    lines.append(self.create_index(t, *spec))
            elif kind in ("drop_unique", "drop_index"):
                touched_indexes.add((t, op["name"]))
                lines.append(
                    f"await {self.use('dropIndex')}(db, {_js_str(t)}, {_js_str(op['name'])});"
                )
            elif kind in ("add_check", "drop_check"):
                verb = "Added" if kind == "add_check" else "Removed"
                lines.append(
                    f"// {verb} check {op['name']}: enforced by the Mongoose model (lib/checks.js), "
                    "since MongoDB has no CHECK constraints."
                )
            elif kind == "insert_seed":
                lines.extend(self.insert_rows(t, op["rows"], new["tables"][t]))
            elif kind == "delete_seed":
                lines.extend(self.delete_rows(t, op["rows"], old["tables"][t]))
            else:
                raise ValueError(f"Unknown migration operation {kind!r}")

        # A column whose stored type changed invalidates the type filter of
        # every unique index over it — rebuild those the ops didn't touch.
        for t, after in new["tables"].items():
            before = old["tables"].get(t)
            if before is None:
                continue
            ensure_validator(t)
            old_specs, new_specs = (
                _mongo_unique_specs(before),
                _mongo_unique_specs(after),
            )
            for name, spec in new_specs.items():
                if (
                    name in old_specs
                    and old_specs[name] != spec
                    and (t, name) not in touched_indexes
                ):
                    lines.append(
                        f"await {self.use('dropIndex')}(db, {_js_str(t)}, {_js_str(name)});"
                    )
                    lines.append(self.create_index(t, *spec))

        prelude = []
        if self.uses_now or self.uses_today:
            prelude.append("const now = new Date();")
        if self.uses_today:
            prelude.append("const today = new Date(now.toISOString().slice(0, 10));")
        body = prelude + ([""] if prelude and lines else []) + lines
        return body or ["// Nothing to do."]

    # ── pieces ──
    def apply_validator(self, t: str, ts: dict) -> list[str]:
        validator = json.dumps(_mongo_validator(ts), indent=2).splitlines()
        return (
            [f"await {self.use('applyValidator')}(db, {_js_str(t)}, {validator[0]}"]
            + validator[1:-1]
            + [f"{validator[-1]});"]
        )

    def index_spec(self, ts: dict, name: str) -> tuple[dict, dict] | None:
        uniques = _mongo_unique_specs(ts)
        if name in uniques:
            return uniques[name]
        idx = ts["indexes"].get(name)
        if idx is None:
            return None
        return ({_mongo_field(c): 1 for c in idx["columns"]}, {"name": name})

    @staticmethod
    def create_index(t: str, keys: dict, options: dict) -> str:
        return f"await db.collection({_js_str(t)}).createIndex({json.dumps(keys)}, {json.dumps(options)});"

    def create_table(self, t: str, ts: dict) -> list[str]:
        lines = self.apply_validator(t, ts)
        for name, idx in list(_mongo_unique_specs(ts).items()):
            lines.append(self.create_index(t, *idx))
        for name, idx in ts["indexes"].items():
            if not idx["unique"]:
                lines.append(self.create_index(t, *self.index_spec(ts, name)))
        if ts["seed_rows"]:
            lines.extend(self.insert_rows(t, ts["seed_rows"], ts))
        return lines

    def default_js(self, col: dict) -> str:
        default = col["default"]
        if default["kind"] == "now":
            self.uses_now = True
            return "now"
        if default["kind"] == "today":
            self.uses_today = True
            return "today"
        return _js_value(default["value"], col["type"])

    def insert_rows(self, t: str, rows: list[dict], ts: dict) -> list[str]:
        # MongoDB has no server-side defaults, so a seed document gets its
        # columns' defaults and timestamps written in explicitly — what
        # SQL's DEFAULT clauses and the Mongoose model would have filled in.
        self.uses_now = True
        columns = ts["columns"]
        lines = [f"await db.collection({_js_str(t)}).insertMany(["]
        for row in rows:
            fields = []
            for name in ts["column_order"]:
                col = columns[name]
                if name in row:
                    fields.append(
                        f"{_js_str(name)}: {_js_value(row[name], col['type'])}"
                    )
                elif col["default"] is not None:
                    fields.append(f"{_js_str(name)}: {self.default_js(col)}")
            fields += ['"created_at": now', '"updated_at": now']
            lines.append(f"  {{ {', '.join(fields)} }},")
        lines.append("]);")
        return lines

    def delete_rows(self, t: str, rows: list[dict], ts: dict) -> list[str]:
        columns = ts["columns"]
        lines = [
            "// Removes each seed document that no longer exists in the design, matched on",
            "// every value it was seeded with (edited documents are left alone).",
        ]
        for row in rows:
            keys = [
                c
                for c in ts["column_order"]
                if c in row and columns[c]["type"] != "json"
            ]
            if not keys:
                lines.append(
                    "// (one seed document has no comparable values, so it is left in place)"
                )
                continue
            match = ", ".join(
                f"{_js_str(c)}: {_js_value(row[c], columns[c]['type'])}" for c in keys
            )
            lines.append(
                f"await db.collection({_js_str(t)}).deleteMany({{ {match} }});"
            )
        return lines

    def column_op(self, op: dict, old: dict, new: dict) -> list[str]:
        kind, t = op["op"], op["table"]
        coll = f"db.collection({_js_str(t)})"
        column = op["column"]
        field = _js_str(column)
        if kind == "add_column":
            col = new["tables"][t]["columns"][column]
            if col["default"] is None:
                return []
            # Like SQL's ADD COLUMN ... DEFAULT: existing rows get the default.
            return [
                f"await {coll}.updateMany({{ {field}: {{ $exists: false }} }}, {{ $set: {{ {field}: {self.default_js(col)} }} }});"
            ]
        if kind == "drop_column":
            return [
                f"await {coll}.updateMany({{ {field}: {{ $exists: true }} }}, {{ $unset: {{ {field}: '' }} }});"
            ]
        if kind in ("add_fk", "drop_fk"):
            verb = "Added" if kind == "add_fk" else "Removed"
            return [
                f"// {verb} foreign key {op['name']}: enforced (with its on-delete rule) by the Mongoose "
                "models, since MongoDB has no foreign keys."
            ]
        # alter_column
        old_col = old["tables"][t]["columns"][column]
        new_col = new["tables"][t]["columns"][column]
        lines = []
        old_bson, new_bson = _bson_type(old_col), _bson_type(new_col)
        target = (
            "objectId"
            if new_bson == "objectId"
            else _MONGO_CONVERT_TO.get(new_col["type"])
        )
        if old_bson != new_bson and target:
            # Converts what can be converted; a value that can't keeps its
            # old type (listed as a risk when this migration was confirmed).
            ref = json.dumps(f"${column}")
            lines.append(
                f"await {coll}.updateMany({{ {field}: {{ $exists: true, $ne: null }} }}, "
                f'[{{ $set: {{ {field}: {{ $convert: {{ input: {ref}, to: "{target}", onError: {ref} }} }} }} }}]);'
            )
        changes = op["changes"]
        if (
            "nullable" in changes
            and changes["nullable"][1] is False
            and new_col["default"] is not None
        ):
            lines.append(
                f"// Documents without {column} get the default before it becomes required."
            )
            lines.append(
                f"await {coll}.updateMany({{ {field}: null }}, {{ $set: {{ {field}: {self.default_js(new_col)} }} }});"
            )
        return lines


def _render_mongo_revision(
    rev: dict, down_id: str | None, previous_snapshot: dict
) -> str:
    snap = rev["snapshot"]
    renderer = _JsRenderer()
    up = renderer.body(
        db_schema.diff_snapshots(previous_snapshot, snap), previous_snapshot, snap
    )
    down = renderer.body(
        db_schema.diff_snapshots(snap, previous_snapshot), snap, previous_snapshot
    )

    header = [f"// Migration {rev['id']}: {_js_comment(_revision_title(rev))}", "//"]
    header += [f"//   - {_js_comment(line)}" for line in rev.get("summary") or []] or [
        "//   - (no schema changes)"
    ]
    if rev.get("destructive"):
        header += [
            "//",
            "// Permanently changes existing data (confirmed when it was generated):",
        ]
        header += [f"//   - {_js_comment(line)}" for line in rev["destructive"]]
    header += [
        "//",
        f"// Revision {rev['id']}{f' (after {down_id})' if down_id else ''}, created {_js_comment(rev.get('created_at') or '')}.",
        "// Written by VengaiCode from this project's Architecture tables. VengaiCode",
        "// never rewrites a migration once it has been generated (every later schema",
        "// change arrives as a NEW file), because it may already have run against a",
        "// real database — so it is safe to edit this file by hand; your edits are",
        "// kept on every regeneration.",
        "//",
        "// Check constraints and foreign keys (with their on-delete rules) are",
        "// enforced by the Mongoose models, because MongoDB itself has neither —",
        "// so they need no database changes here.",
        "",
    ]
    ordered = [name for name in _MONGO_HELPERS if name in renderer.helpers]
    for name in ordered:
        header += [_MONGO_HELPERS[name], ""]
    body = header + ["module.exports = {", "  async up(db) {"]
    body += [f"    {line}" if line else "" for line in up]
    body += ["  },", "", "  async down(db) {"]
    body += [f"    {line}" if line else "" for line in down]
    body += ["  },", "};"]
    return "\n".join(body) + "\n"


_MIGRATE_MONGO_CONFIG_JS = """// migrate-mongo configuration, written by VengaiCode. Used by the
// `npm run migrate` / `migrate:status` / `migrate:down` scripts (the
// migrate-mongo command line, run from this backend/ folder) and by
// lib/migrate.js, which applies pending migrations every time the server
// starts.
require('dotenv').config();

module.exports = {
  mongodb: {
    // The same variable and default as server.js, so the server and its
    // migrations always use the same database. The database name is the
    // URI's path (/app), exactly as for mongoose.connect().
    url: process.env.MONGODB_URI || 'mongodb://localhost:27017/app',
    options: {},
  },
  migrationsDir: 'migrations',
  // Collection recording which migrations have run.
  changelogCollectionName: 'changelog',
  // Locking is off (lockTtl 0), migrate-mongo's own default: with it on, a
  // server killed mid-migration would refuse to start again until the lock
  // expired.
  lockCollectionName: 'changelog_lock',
  lockTtl: 0,
  migrationFileExtension: '.js',
  useFileHash: false,
  moduleSystem: 'commonjs',
};
"""

_MIGRATE_JS = """// Applies this app's pending MongoDB migrations (migrations/*.js), written
// by VengaiCode. server.js calls runMigrations() once at startup, before
// the server accepts requests — it is exactly `npm run migrate`, using the
// same migrate-mongo-config.js.
const path = require('path');

async function runMigrations() {
  // migrate-mongo is an ES module, loaded with import(): its CommonJS entry
  // point only hands back Promises of its functions.
  const { config, database, up } = await import('migrate-mongo');
  config.set({
    ...require('../migrate-mongo-config'),
    // migrate-mongo resolves a relative migrationsDir against the current
    // working directory; anchoring it here lets the server start from any
    // folder.
    migrationsDir: path.join(__dirname, '..', 'migrations'),
  });
  const { db, client } = await database.connect();
  try {
    const applied = await up(db, client);
    applied.forEach((fileName) => console.log(`Applied migration ${fileName}`));
    return applied;
  } finally {
    await client.close();
  }
}

module.exports = { runMigrations };
"""


# ───────────────────────────────────────────────
#  Support files
# ───────────────────────────────────────────────
def _support_files(
    backend: str, schema: db_schema.ResolvedSchema
) -> list[GeneratedFile]:
    if backend == "fastapi":
        return [
            GeneratedFile(
                path="backend/alembic.ini",
                language="ini",
                content=_alembic_ini(),
                description="Alembic configuration (for running migrations by hand)",
            ),
            GeneratedFile(
                path="backend/migrations/env.py",
                language="python",
                content=_alembic_env_py(schema),
                description="Alembic environment (async, SQLite-safe batch mode)",
            ),
            GeneratedFile(
                path="backend/migrations/script.py.mako",
                language="mako",
                content=_SCRIPT_PY_MAKO,
                description="Alembic's template for hand-written revisions",
            ),
            GeneratedFile(
                path="backend/app/core/migrate.py",
                language="python",
                content=_MIGRATE_PY,
                description="Runs pending database migrations at startup",
            ),
        ]
    return [
        GeneratedFile(
            path="backend/migrate-mongo-config.js",
            language="javascript",
            content=_MIGRATE_MONGO_CONFIG_JS,
            description="migrate-mongo configuration",
        ),
        GeneratedFile(
            path="backend/lib/migrate.js",
            language="javascript",
            content=_MIGRATE_JS,
            description="Runs pending MongoDB migrations at startup",
        ),
    ]
