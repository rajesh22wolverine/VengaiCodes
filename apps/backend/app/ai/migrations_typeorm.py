# ═══════════════════════════════════════════════════════════════
#  VengaiCode — TypeORM migrations for the deterministic NestJS backend
#  ai/migrations_typeorm.py — Renders one revision (bookkeeping, history
#  and safety rules are migrations_gen's, shared with every backend) as
#  a TypeORM migration class in src/migrations/NNNN-slug.ts: up() is the
#  diff from the previous revision's snapshot, down() the diff back.
#  The steps use TypeORM's own schema builder (createTable,
#  changeColumn, createCheckConstraint…), which rebuilds SQLite tables
#  itself, with foreign keys switched off while it runs.
#
#  Like the Alembic renderer: rows that already exist get the new
#  default before a column becomes required, and a downgrade that would
#  make a column required with nothing to fill it leaves it optional.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re

from app.ai import db_schema
from app.ai import typeorm_render as tr
from app.ai.typeorm_render import ts


def _one_line(text: str) -> str:
    return tr.comment(re.sub(r"[\s  ]+", " ", str(text)))


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class _Steps:
    def __init__(self, old: dict, new: dict) -> None:
        self.old, self.new = old, new
        self.lines: list[str] = []

    def add(self, *lines: str) -> None:
        self.lines.extend(lines)

    # ── seeds ──
    def insert_rows(self, t: str, table: dict, rows: list[dict]) -> None:
        columns = table["columns"]
        for row in rows:
            keys = [c for c in table["column_order"] if c in row]
            if not keys:
                self.add(
                    f"await queryRunner.query({ts(f'INSERT INTO {_ident(t)} DEFAULT VALUES')});"
                )
                continue
            sql = (
                f"INSERT INTO {_ident(t)} ({', '.join(_ident(k) for k in keys)}) "
                f"VALUES ({', '.join('?' for _ in keys)})"
            )
            values = ", ".join(
                ts(tr._literal_value(row[k], columns[k]["type"])) for k in keys
            )
            self.add(f"await queryRunner.query({ts(sql)}, [{values}]);")

    def delete_rows(self, t: str, table: dict, rows: list[dict]) -> None:
        # A seed row is identified by its values: every field it set except
        # JSON. A row someone has since edited is left alone.
        columns = table["columns"]
        for row in rows:
            keys = [
                c
                for c in table["column_order"]
                if c in row and columns[c]["type"] != "json"
            ]
            if not keys:
                self.add(
                    "// (one seed row has no comparable values, so it is left in place)"
                )
                continue
            conditions, values = [], []
            for k in keys:
                if row[k] is None:
                    conditions.append(f"{_ident(k)} IS NULL")
                else:
                    conditions.append(f"{_ident(k)} = ?")
                    values.append(ts(tr._literal_value(row[k], columns[k]["type"])))
            sql = f"DELETE FROM {_ident(t)} WHERE {' AND '.join(conditions)}"
            self.add(f"await queryRunner.query({ts(sql)}, [{', '.join(values)}]);")

    # ── operations ──
    def create_table(self, t: str) -> None:
        tables = self.new["tables"]
        table = tables[t]
        columns = [tr.ID_COLUMN]
        columns += [
            tr.migration_column(c, table["columns"][c], tables)
            for c in table["column_order"]
        ]
        columns += [tr.CREATED_AT_COLUMN, tr.UPDATED_AT_COLUMN]
        body = [f"name: {ts(t)},", "columns: ["] + [f"  {c}," for c in columns] + ["],"]
        uniques = tr.uniques(table)
        if uniques:
            body += (
                ["uniques: ["]
                + [
                    f"  {{ name: {ts(n)}, columnNames: [{', '.join(ts(c) for c in cols)}] }},"
                    for n, cols in uniques
                ]
                + ["],"]
            )
        if table["checks"]:
            body += (
                ["checks: ["]
                + [
                    f"  {{ name: {ts(n)}, expression: {ts(tr.check_sql(table, n))} }},"
                    for n in table["checks"]
                ]
                + ["],"]
            )
        indexes = tr.indexes(table)
        if indexes:
            body += (
                ["indices: ["]
                + [
                    f"  {{ name: {ts(n)}, columnNames: [{', '.join(ts(c) for c in cols)}] }},"
                    for n, cols in indexes
                ]
                + ["],"]
            )
        fks = [c for c in table["column_order"] if table["columns"][c]["fk"]]
        if fks:
            body += (
                ["foreignKeys: ["]
                + [f"  {tr.foreign_key(c, table['columns'][c])}," for c in fks]
                + ["],"]
            )
        self.add("await queryRunner.createTable(", "  new Table({")
        self.add(*[f"    {line}" for line in body])
        self.add("  }),", ");")
        if table["seed_rows"]:
            self.insert_rows(t, table, table["seed_rows"])

    def alter_column(self, t: str, column: str, changes: dict) -> None:
        old_col = self.old["tables"][t]["columns"][column]
        new_col = self.new["tables"][t]["columns"][column]
        becomes_required = "nullable" in changes and changes["nullable"][1] is False
        nullable = None
        if becomes_required and new_col["default"] is not None:
            literal = (
                tr.sql_literal(new_col["default"]["value"], new_col["type"])
                if new_col["default"]["kind"] == "literal"
                else {"now": "CURRENT_TIMESTAMP", "today": "CURRENT_DATE"}[
                    new_col["default"]["kind"]
                ]
            )
            sql = f"UPDATE {_ident(t)} SET {_ident(column)} = {literal} WHERE {_ident(column)} IS NULL"
            self.add(
                f"// Rows that already exist get the default before {column} becomes required.",
                f"await queryRunner.query({ts(sql)});",
            )
        elif becomes_required:
            # Only reachable in a downgrade (the upgrade is refused outright):
            # rows written since may have no value here.
            self.add(
                f"// {column} stays optional: rows written since the upgrade may have no value for it."
            )
            nullable = True
        del old_col
        definition = tr.migration_column(
            column, new_col, self.new["tables"], nullable=nullable
        )
        self.add(
            f"await queryRunner.changeColumn({ts(t)}, {ts(column)}, new TableColumn({definition}));"
        )

    def op(self, op: dict) -> None:
        kind, t = op["op"], op["table"]
        new_t, old_t = self.new["tables"], self.old["tables"]
        if kind == "create_table":
            self.create_table(t)
        elif kind == "drop_table":
            self.add(f"await queryRunner.dropTable({ts(t)});")
        elif kind == "add_column":
            c = op["column"]
            col = dict(new_t[t]["columns"][c])
            # Its foreign key arrives as its own add_fk step.
            self.add(
                f"await queryRunner.addColumn({ts(t)}, new TableColumn({tr.migration_column(c, col, new_t)}));"
            )
        elif kind == "drop_column":
            self.add(f"await queryRunner.dropColumn({ts(t)}, {ts(op['column'])});")
        elif kind == "alter_column":
            self.alter_column(t, op["column"], op["changes"])
        elif kind == "add_unique":
            self.add(
                f"await queryRunner.createUniqueConstraint({ts(t)}, new TableUnique({{ name: {ts(op['name'])}, "
                f"columnNames: [{ts(op['column'])}] }}));"
            )
        elif kind == "drop_unique":
            self.add(
                f"await queryRunner.dropUniqueConstraint({ts(t)}, {ts(op['name'])});"
            )
        elif kind == "add_fk":
            col = new_t[t]["columns"][op["column"]]
            self.add(
                f"await queryRunner.createForeignKey({ts(t)}, new TableForeignKey({tr.foreign_key(op['column'], col)}));"
            )
        elif kind == "drop_fk":
            self.add(f"await queryRunner.dropForeignKey({ts(t)}, {ts(op['name'])});")
        elif kind == "add_check":
            expression = tr.check_sql(new_t[t], op["name"])
            self.add(
                f"await queryRunner.createCheckConstraint({ts(t)}, new TableCheck({{ name: {ts(op['name'])}, "
                f"expression: {ts(expression)} }}));"
            )
        elif kind == "drop_check":
            self.add(
                f"await queryRunner.dropCheckConstraint({ts(t)}, {ts(op['name'])});"
            )
        elif kind == "add_index":
            idx = new_t[t]["indexes"][op["name"]]
            cols = ", ".join(ts(c) for c in idx["columns"])
            if idx["unique"]:
                self.add(
                    f"await queryRunner.createUniqueConstraint({ts(t)}, new TableUnique({{ name: {ts(op['name'])}, "
                    f"columnNames: [{cols}] }}));"
                )
            else:
                self.add(
                    f"await queryRunner.createIndex({ts(t)}, new TableIndex({{ name: {ts(op['name'])}, "
                    f"columnNames: [{cols}] }}));"
                )
        elif kind == "drop_index":
            if old_t[t]["indexes"][op["name"]]["unique"]:
                self.add(
                    f"await queryRunner.dropUniqueConstraint({ts(t)}, {ts(op['name'])});"
                )
            else:
                self.add(f"await queryRunner.dropIndex({ts(t)}, {ts(op['name'])});")
        elif kind == "insert_seed":
            self.insert_rows(t, new_t[t], op["rows"])
        elif kind == "delete_seed":
            self.delete_rows(t, old_t[t], op["rows"])
        else:  # pragma: no cover — diff_snapshots emits nothing else
            raise ValueError(f"Unknown migration op {kind!r}")


def _steps(old: dict, new: dict) -> list[str]:
    steps = _Steps(old, new)
    for op in db_schema.diff_snapshots(old, new):
        steps.op(op)
    return steps.lines


def render_revision(rev: dict, down_id: str | None, previous_snapshot: dict) -> str:
    snap = rev["snapshot"]
    up = _steps(previous_snapshot, snap)
    down = _steps(snap, previous_snapshot)
    name = tr.migration_class(rev)

    title = (
        "Initial schema"
        if rev["id"] == "0001"
        else (rev.get("summary") or ["No schema changes"])[0]
    )
    doc = [_one_line(title[:1].upper() + title[1:]), ""]
    doc += [f"- {_one_line(line)}" for line in rev.get("summary") or []] or [
        "- (no schema changes)"
    ]
    if rev.get("destructive"):
        doc += [
            "",
            "Permanently changes existing data (confirmed when it was generated):",
        ]
        doc += [f"- {_one_line(line)}" for line in rev["destructive"]]
    doc += [
        "",
        f"Revision {rev['id']}"
        + (f" (after {down_id})" if down_id else "")
        + f", created {_one_line(rev.get('created_at') or '')}.",
        "Written by VengaiCode from this project's Architecture tables. VengaiCode never",
        "rewrites a migration once it has been generated (every later schema change",
        "arrives as a NEW migration), because it may already have run against a real",
        "database — so it is safe to edit this file by hand; your edits are kept.",
    ]
    lines = ["/**"] + [f" * {line}".rstrip() for line in doc] + [" */"]
    lines += [
        "import {",
        "  MigrationInterface,",
        "  QueryRunner,",
        "  Table,",
        "  TableCheck,",
        "  TableColumn,",
        "  TableForeignKey,",
        "  TableIndex,",
        "  TableUnique,",
        "} from 'typeorm';",
        "",
        f"export class {name} implements MigrationInterface {{",
        f"  name = {ts(name)};",
        "",
        "  public async up(queryRunner: QueryRunner): Promise<void> {",
    ]
    lines += [f"    {line}" for line in up] or ["    // (no schema changes)"]
    lines += [
        "  }",
        "",
        "  public async down(queryRunner: QueryRunner): Promise<void> {",
    ]
    lines += [f"    {line}" for line in down] or ["    // (no schema changes)"]
    lines += ["  }", "}", ""]
    return "\n".join(lines)
