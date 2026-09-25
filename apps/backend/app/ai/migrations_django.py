# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Django migrations for the deterministic Django backend
#  ai/migrations_django.py — Renders one revision (see migrations_gen:
#  the bookkeeping, history and safety rules are shared with Alembic and
#  migrate-mongo) as a real Django migration module:
#  api/migrations/NNNN_slug.py with operations Django reverses itself,
#  so `manage.py migrate api NNNN` walks back through the history too.
#
#  Operations come from db_schema.diff_snapshots(), in its
#  execution-safe order; every field, constraint and index is rendered
#  by django_render, the same code the model classes come from, so
#  `manage.py makemigrations --check` finds nothing to add.
#
#  Django-specific handling:
#    - A new table's foreign keys go inside CreateModel when their
#      target already exists (or is the table itself); one pointing at a
#      table created LATER in the same migration is added after it.
#    - A foreign key added to (or removed from) an existing column keeps
#      its data: db_column is pinned, the field is renamed in Django's
#      state only (customer_id <-> customer), then its type changes.
#    - Seed rows are RunPython steps with their own reverse (a removed
#      seed row is matched on every non-JSON value it was seeded with,
#      exactly like the Alembic renderer).
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re

from app.ai import db_schema
from app.ai import django_render as dr


def _one_line(text: str) -> str:
    return re.sub(r"[\s  ]+", " ", str(text)).strip()


def _doc_line(text: str) -> str:
    return _one_line(text).replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


class _Renderer:
    def __init__(self, old: dict, new: dict, rev_id: str) -> None:
        self.old, self.new = old, new
        self.rev_id = rev_id
        self.imports = dr.Imports()
        self.functions: list[str] = []
        self._seed_count = 0
        self.ops: list[str] = []

    # ── helpers ──
    def _field(self, tables: dict, table: dict, column: str, **kw) -> str:
        return dr.field_code(
            column, table["columns"][column], tables, self.imports, **kw
        )

    def _model(self, tables: dict, t: str) -> str:
        return dr.model_name(tables[t])

    def _seed_function(
        self, t: str, table: dict, rows: list[dict], insert: bool
    ) -> str:
        """forward/backward pair name for inserting (or removing) rows."""
        self._seed_count += 1
        number = self._seed_count
        name = f"_seed_{self.rev_id}_{number}"
        model = dr.model_name(table)
        columns = table["columns"]

        def attname(column: str) -> str:
            col = columns[column]
            if col["fk"]:
                return f"{dr.field_name(column, col)}_id"
            return column

        def row_code(row: dict, keys: list[str]) -> str:
            items = ", ".join(
                f'"{attname(c)}": {dr.value_code(row[c], columns[c]["type"], self.imports)}'
                for c in keys
            )
            return "{" + items + "}"

        order = table["column_order"]
        comparable = [c for c in order if columns[c]["type"] != "json"]
        insert_rows = [row_code(r, [c for c in order if c in r]) for r in rows]
        match_rows = [row_code(r, [c for c in comparable if c in r]) for r in rows]
        insert_body = [
            f'    model = apps.get_model("{dr.APP_LABEL}", "{model}")',
            "    for values in [",
            *[f"        {r}," for r in insert_rows],
            "    ]:",
            "        model.objects.create(**values)",
        ]
        # A seed row is identified by its values: every field it set
        # (except JSON, which Postgres can't compare with "="). A row
        # someone has since edited is left alone.
        delete_body = [
            f'    model = apps.get_model("{dr.APP_LABEL}", "{model}")',
            "    for values in [",
            *[f"        {r}," for r in match_rows if r != "{}"],
            "    ]:",
            "        model.objects.filter(**values).delete()",
        ]
        first, second = (
            (insert_body, delete_body) if insert else (delete_body, insert_body)
        )
        self.functions += [
            f"def {name}_forward(apps, schema_editor):",
            *first,
            "",
            "",
            f"def {name}_backward(apps, schema_editor):",
            *second,
            "",
            "",
        ]
        return f"migrations.RunPython({name}_forward, {name}_backward)"

    # ── operations ──
    def create_table(self, t: str, created: set[str]) -> list[str]:
        tables = self.new["tables"]
        table = tables[t]
        fields = [f'("id", {dr.ID_FIELD}),']
        deferred = []
        for c in table["column_order"]:
            col = table["columns"][c]
            name = dr.field_name(c, col)
            fk = col["fk"]
            if (
                fk
                and fk["table"] != t
                and fk["table"] not in created
                and fk["table"] not in self.old["tables"]
            ):
                deferred.append(c)
                continue
            fields.append(f'("{name}", {self._field(tables, table, c)}),')
        fields += [
            f'("created_at", {dr.CREATED_AT_FIELD}),',
            f'("updated_at", {dr.UPDATED_AT_FIELD}),',
        ]
        model = dr.model_name(table)
        out = [
            "migrations.CreateModel(",
            f'    name="{model}",',
            "    fields=[",
            *[f"        {f}" for f in fields],
            "    ],",
            f'    options={{"db_table": "{t}"}},',
            "),",
        ]
        self._deferred.extend((t, c) for c in deferred)
        for constraint in dr.table_constraints(table, self.imports):
            out.append(
                f'migrations.AddConstraint(model_name="{model.lower()}", constraint={constraint}),'
            )
        for index in dr.table_indexes(table):
            out.append(
                f'migrations.AddIndex(model_name="{model.lower()}", index={index}),'
            )
        if table["seed_rows"]:
            self._seeds.append(
                self._seed_function(t, table, table["seed_rows"], insert=True) + ","
            )
        return out

    def render(self, ops: list[dict]) -> list[str]:
        new_t, old_t = self.new["tables"], self.old["tables"]
        created: set[str] = set()
        added_columns = {
            (o["table"], o["column"]) for o in ops if o["op"] == "add_column"
        }
        dropped_columns = {
            (o["table"], o["column"]) for o in ops if o["op"] == "drop_column"
        }
        self._deferred: list[tuple[str, str]] = []
        self._seeds: list[str] = []
        out: list[str] = []
        for op in ops:
            kind, t = op["op"], op["table"]
            if kind == "create_table":
                out += self.create_table(t, created)
                created.add(t)
                continue
            if kind == "drop_table":
                out.append(f'migrations.DeleteModel(name="{self._model(old_t, t)}"),')
                continue
            tables = old_t if kind.startswith(("drop_", "delete_")) else new_t
            table = tables[t]
            model = dr.model_name(table).lower()
            if kind == "add_column":
                c = op["column"]
                name = dr.field_name(c, table["columns"][c])
                out.append(
                    f'migrations.AddField(model_name="{model}", name="{name}", field={self._field(new_t, table, c)}),'
                )
            elif kind == "drop_column":
                c = op["column"]
                name = dr.field_name(c, table["columns"][c])
                out.append(
                    f'migrations.RemoveField(model_name="{model}", name="{name}"),'
                )
            elif kind == "alter_column":
                c = op["column"]
                old_col, new_col = old_t[t]["columns"][c], new_t[t]["columns"][c]
                # A foreign key that changes arrives as its own drop_fk /
                # add_fk; in between, the column is a plain one.
                fk = old_col["fk"] if old_col["fk"] == new_col["fk"] else None
                name = dr.field_name(c, {"fk": fk})
                field = dr.field_code(c, new_col, new_t, self.imports, fk=fk)
                out.append(
                    f'migrations.AlterField(model_name="{model}", name="{name}", field={field}),'
                )
            elif kind == "add_fk":
                if (t, op["column"]) not in added_columns:
                    out += self._fk_on_existing_column(t, op["column"], adding=True)
            elif kind == "drop_fk":
                if (t, op["column"]) not in dropped_columns:
                    out += self._fk_on_existing_column(t, op["column"], adding=False)
            elif kind == "add_unique":
                constraint = dr.unique_constraint_code(
                    table, [op["column"]], op["name"]
                )
                out.append(
                    f'migrations.AddConstraint(model_name="{model}", constraint={constraint}),'
                )
            elif kind in ("drop_unique", "drop_check"):
                out.append(
                    f'migrations.RemoveConstraint(model_name="{model}", name="{op["name"]}"),'
                )
            elif kind == "add_check":
                constraint = dr.check_constraint_code(table, op["name"], self.imports)
                out.append(
                    f'migrations.AddConstraint(model_name="{model}", constraint={constraint}),'
                )
            elif kind == "add_index":
                if table["indexes"][op["name"]]["unique"]:
                    columns = table["indexes"][op["name"]]["columns"]
                    constraint = dr.unique_constraint_code(table, columns, op["name"])
                    out.append(
                        f'migrations.AddConstraint(model_name="{model}", constraint={constraint}),'
                    )
                else:
                    out.append(
                        f'migrations.AddIndex(model_name="{model}", index={dr.index_code(table, op["name"])}),'
                    )
            elif kind == "drop_index":
                if table["indexes"][op["name"]]["unique"]:
                    out.append(
                        f'migrations.RemoveConstraint(model_name="{model}", name="{op["name"]}"),'
                    )
                else:
                    out.append(
                        f'migrations.RemoveIndex(model_name="{model}", name="{dr.index_name(op["name"])}"),'
                    )
            elif kind == "insert_seed":
                self._seeds.append(
                    self._seed_function(t, table, op["rows"], insert=True) + ","
                )
            elif kind == "delete_seed":
                out.append(
                    self._seed_function(t, table, op["rows"], insert=False) + ","
                )
            else:  # pragma: no cover — diff_snapshots emits nothing else
                raise ValueError(f"Unknown migration op {kind!r}")
        for t, c in self._deferred:
            table = new_t[t]
            name = dr.field_name(c, table["columns"][c])
            out.append(
                f'migrations.AddField(model_name="{dr.model_name(table).lower()}", name="{name}", '
                f"field={self._field(new_t, table, c)}),"
            )
        # Seed rows last, once every table and foreign key they need exists.
        return out + self._seeds

    def _fk_on_existing_column(self, t: str, c: str, adding: bool) -> list[str]:
        """Turn an existing column into a foreign key (or back) without
        touching its data: pin its column name, rename the Django field
        (state only), then change its type. Adding runs after the
        column's other changes, removing before them (diff_snapshots'
        order), so each uses that side's snapshot."""
        tables = self.new["tables"] if adding else self.old["tables"]
        col = tables[t]["columns"][c]
        model = dr.model_name(tables[t]).lower()
        fk_name = dr.field_name(c, col)
        pinned = dr.field_code(c, col, tables, self.imports, fk=None, pin_column=True)
        plain = dr.field_code(c, col, tables, self.imports, fk=None)
        as_fk = dr.field_code(c, col, tables, self.imports)
        if fk_name == c:  # the column already has the field's name
            field = as_fk if adding else plain
            return [
                f'migrations.AlterField(model_name="{model}", name="{c}", field={field}),'
            ]
        if adding:
            return [
                f'migrations.AlterField(model_name="{model}", name="{c}", field={pinned}),',
                f'migrations.RenameField(model_name="{model}", old_name="{c}", new_name="{fk_name}"),',
                f'migrations.AlterField(model_name="{model}", name="{fk_name}", field={as_fk}),',
            ]
        return [
            f'migrations.AlterField(model_name="{model}", name="{fk_name}", field={pinned}),',
            f'migrations.RenameField(model_name="{model}", old_name="{fk_name}", new_name="{c}"),',
            f'migrations.AlterField(model_name="{model}", name="{c}", field={plain}),',
        ]


def render_revision(rev: dict, previous: dict | None, previous_snapshot: dict) -> str:
    """The migration module for one revision. `previous` is the revision
    before it (None for the first)."""
    snap = rev["snapshot"]
    ops = db_schema.diff_snapshots(previous_snapshot, snap)
    renderer = _Renderer(previous_snapshot, snap, rev["id"])
    operations = renderer.render(ops)

    title = (
        "Initial schema"
        if rev["id"] == "0001"
        else ((rev.get("summary") or ["No schema changes"])[0])
    )
    doc = [_doc_line(title[:1].upper() + title[1:]), ""]
    doc += [f"- {_doc_line(line)}" for line in rev.get("summary") or []] or [
        "- (no schema changes)"
    ]
    if rev.get("destructive"):
        doc += [
            "",
            "Permanently changes existing data (confirmed when it was generated):",
        ]
        doc += [f"- {_doc_line(line)}" for line in rev["destructive"]]
    doc += [
        "",
        f"Created: {_doc_line(rev.get('created_at') or '')}",
        "",
        "Written by VengaiCode from this project's Architecture tables. VengaiCode",
        "never rewrites a migration once it has been generated (every later schema",
        "change arrives as a NEW migration), because it may already have run against",
        "a real database — so it is safe to edit this file by hand; your edits are",
        "kept on every regeneration.",
    ]
    lines = ['"""' + doc[0], *doc[1:], '"""', ""]
    lines += renderer.imports.lines(migrations=True)
    lines += ["", ""]
    lines += renderer.functions
    dependencies = (
        f'[("{dr.APP_LABEL}", "{previous["id"]}_{previous["slug"]}")]'
        if previous
        else "[]"
    )
    lines += ["class Migration(migrations.Migration):"]
    if previous is None:
        lines += ["    initial = True", ""]
    lines += [f"    dependencies = {dependencies}", "", "    operations = ["]
    lines += [f"        {line}" for line in operations] or []
    lines += ["    ]", ""]
    return "\n".join(lines)
