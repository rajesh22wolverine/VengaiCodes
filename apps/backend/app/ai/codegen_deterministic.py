# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic (Schema-Driven) Code Generation
#  ai/codegen_deterministic.py — An AI-less alternative to
#  codegen_runner.py for a small, explicit set of framework pairings:
#  real CRUD models, routes and screens are built directly from the
#  approved Architecture's database_tables via string templates instead
#  of one AI call per file. Zero AI calls, zero cost, instant, and can
#  never produce invalid syntax the way a freeform LLM response can.
#
#  Supported pairings (SUPPORTED_STACKS below):
#    - React + FastAPI (REST)  — SQLAlchemy models over Postgres/SQLite
#    - Vue + Express (REST)    — Mongoose schemas over MongoDB
#  Deliberately narrow rather than attempting all 8x13 adapter
#  combinations at once. The two pairings were chosen to prove the
#  approach generalizes across BOTH axes (a second frontend AND a
#  second backend/ORM paradigm — relational vs document), not just a
#  new frontend bolted onto the same backend. Adding a third pairing
#  means adding one more branch to the dispatch dicts near the bottom
#  of this file, not rewriting it.
#
#  2026-09-25 — typed schema + real migrations. Every table goes through
#  db_schema.resolve_schema() first, so a column's type, nullability,
#  default, uniqueness, foreign key (with its ON DELETE rule), checks and
#  indexes are the DECLARED ones (an undeclared field still gets the same
#  by-name inference as before). The same resolved schema feeds
#  migrations_gen.plan_migrations(), which writes the versioned Alembic /
#  migrate-mongo migration for whatever changed since the last run; the
#  generated app applies pending migrations at startup instead of
#  create_all. Everything the model files and the migrations must agree
#  on (types, server defaults, constraint and index names) comes from
#  db_schema / migrations_gen, never from a second copy here.
#
#  Scope, on purpose: standard CRUD only. A table's fields become real
#  columns/schema fields and a real REST CRUD surface
#  (list/create/get/update/delete) plus a matching list-and-form
#  screen. Anything beyond CRUD — bespoke business logic, custom
#  endpoints — belongs in the VENGAI:CUSTOM slots this module leaves in
#  every file it writes, which are the one thing regeneration never
#  touches (see extract_custom_slots/reinject_custom_slots below). This
#  is the concrete version of the "named slots AI/human fills in,
#  deterministic generator owns everything else" split.
#
#  Reuses the EXACT same wiring helpers the AI path uses (each
#  pairing's own FRONTEND_ADAPTERS[key]/BACKEND_ADAPTERS[key]
#  .manifest_files/.entry_point_files — in their migrations=True mode —
#  build_readme_setup, apply_package_json_name) rather than
#  reimplementing package.json/requirements.txt/main.py/App.jsx/
#  server.js, so the two paths can't silently drift.
#
#  Output lands in project.codegen_data in the IDENTICAL shape
#  codegen_runner.finalize() writes (see api/v1/codegen.py's
#  GenerateCodeResponse) plus two additive keys, "generation_mode" and
#  "migrations". This is what makes it packaging-transparent:
#  packaging.py, android_packaging.py and linux_packaging.py gate only
#  on codegen_data["user_approved"], codegen_data["validation_warnings"]
#  and stack_matrix.get_project_stack() — none of them has any opinion
#  on how the files were produced.
# ═══════════════════════════════════════════════════════════════

import json
import re
from datetime import datetime, timezone

from app.ai import db_schema, migrations_gen
from app.ai.codegen.backend import BACKEND_ADAPTERS
from app.ai.codegen.frontend import FRONTEND_ADAPTERS
from app.ai.codegen.readme import build_readme_setup
from app.ai.codegen.types import WiringCtx
from app.ai.codegen_shared import (
    GeneratedFile,
    apply_package_json_name,
    detect_native_capabilities,
    js_string_literal,
    validate_generated_content,
)
from app.models.project import Project

SUPPORTED_STACKS: set[tuple[str, str, str]] = {
    ("react", "fastapi", "rest"),
    ("vue", "express", "rest"),
}


class DeterministicCodegenError(RuntimeError):
    """A failure with a message meant for the user, not a stack trace."""


# ───────────────────────────────────────────────
#  Legacy by-name type inference — thin wrappers over db_schema, which
#  owns the one classifier (an undeclared field resolves exactly as it
#  always did). Kept because older callers and tests still use them.
# ───────────────────────────────────────────────
_SA_TYPE_BY_CATEGORY = {
    "email": "String(255)",
    "url": "String(500)",
    "float": "Float",
    "int": "Integer",
    "bool": "Boolean",
    "datetime": "DateTime(timezone=True)",
    "text": "Text",
    "string": "String(255)",
}

_MONGOOSE_TYPE_BY_CATEGORY = {
    "email": "String",
    "url": "String",
    "float": "Number",
    "int": "Number",
    "bool": "Boolean",
    "datetime": "Date",
    "text": "String",
    "string": "String",
}


def _classify_field(field_name: str) -> str:
    return db_schema.classify_field(field_name)


def _infer_sa_type(field_name: str) -> str:
    return _SA_TYPE_BY_CATEGORY[_classify_field(field_name)]


def _infer_mongoose_type(field_name: str) -> str:
    return _MONGOOSE_TYPE_BY_CATEGORY[_classify_field(field_name)]


def _table_slug_plural(name: str) -> str:
    return db_schema.table_sql_name(name)


# ───────────────────────────────────────────────
#  Custom-code preservation ("named slots")
# ───────────────────────────────────────────────
# Line-based, not a single clever regex, deliberately — a file mixes
# comment styles (# in Python, // and {/* */} / <!-- --> in JSX/Vue)
# and a line-based scan only needs to find the marker TEXT, never parse
# the comment syntax around it, so it works identically regardless of
# language.
_START_RE = re.compile(r"VENGAI:CUSTOM:([\w-]+):start")
_END_RE = re.compile(r"VENGAI:CUSTOM:([\w-]+):end")


def extract_custom_slots(content: str) -> dict[str, str]:
    """Every VENGAI:CUSTOM:<name>:start/:end block's body, keyed by name."""
    lines = content.splitlines(keepends=True)
    slots: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = _START_RE.search(lines[i])
        if m:
            name = m.group(1)
            body: list[str] = []
            j = i + 1
            while j < len(lines) and not _END_RE.search(lines[j]):
                body.append(lines[j])
                j += 1
            slots[name] = "".join(body)
            i = j
        i += 1
    return slots


def reinject_custom_slots(new_content: str, old_slots: dict[str, str]) -> str:
    """Replace each freshly-templated slot body with the previously saved
    one, when a slot of that name existed before. A slot name that's new
    (a table just added) keeps the template's own default placeholder."""
    if not old_slots:
        return new_content
    lines = new_content.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _START_RE.search(lines[i])
        if m and m.group(1) in old_slots:
            out.append(lines[i])
            out.append(old_slots[m.group(1)])
            j = i + 1
            while j < len(lines) and not _END_RE.search(lines[j]):
                j += 1
            i = j
            continue
        out.append(lines[i])
        i += 1
    return "".join(out)


def merge_preserving_custom_code(
    old_files: list[dict], new_files: list[GeneratedFile]
) -> list[GeneratedFile]:
    """For every freshly generated file, if a file at the same path
    existed before AND it carries any VENGAI:CUSTOM slots, splice the
    OLD slot contents into the NEW template output. Everything outside
    a slot always comes from the fresh template (so a schema change,
    e.g. a new column, still takes effect) — only what a user (or a
    future AI slot-filler) wrote inside a named slot survives.

    Known, honest limitation: a table removed from the architecture
    between runs has no new file to splice into, so any custom code
    that lived only in that table's slots is not recoverable by this
    function — there is nothing left to merge it into."""
    old_by_path = {f["path"]: f["content"] for f in old_files}
    merged: list[GeneratedFile] = []
    for gf in new_files:
        old_content = old_by_path.get(gf.path)
        if old_content:
            old_slots = extract_custom_slots(old_content)
            if old_slots:
                merged.append(
                    GeneratedFile(
                        path=gf.path,
                        language=gf.language,
                        content=reinject_custom_slots(gf.content, old_slots),
                        description=gf.description,
                    )
                )
                continue
        merged.append(gf)
    return merged


# ───────────────────────────────────────────────
#  Small rendering helpers
# ───────────────────────────────────────────────
def _py_str(text: str) -> str:
    # json.dumps output is always a valid Python string literal with the
    # same value (every JSON escape is also a Python escape).
    return json.dumps(str(text))


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _docstring_text(text: str) -> str:
    return _one_line(text).replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def _js_comment_text(text: str) -> str:
    """User text inside a // comment: one line, no "TODO", and no brackets
    unless they pair up (the generated-file check counts them everywhere)."""
    line = _one_line(text).replace("TODO", "to-do")
    if sum(line.count(c) for c in "{([") != sum(line.count(c) for c in "})]"):
        line = re.sub(r"[{}()\[\]]", "", line)
    return line


def _heading(table: db_schema.ResolvedTable) -> str:
    purpose = _one_line(table.purpose)
    return f"{table.name}: {purpose}" if purpose else table.name


def _upper(slug: str) -> str:
    return slug.upper()


# ═══════════════════════════════════════════════
#  FastAPI backend (SQLAlchemy over SQLite/Postgres, Alembic migrations)
# ═══════════════════════════════════════════════
_ON_DELETE_SQL = {"cascade": "CASCADE", "set_null": "SET NULL", "restrict": "RESTRICT"}


def _sa_column_code(col: db_schema.ResolvedColumn) -> str:
    snap = col.snapshot()
    parts = [db_schema.sa_type_code(snap)]
    if col.fk:
        target = f"{col.fk.ref_table_sql}.{col.fk.ref_column}"
        parts.append(
            f"sa.ForeignKey({_py_str(target)}, name={_py_str(col.fk.constraint_name)}, "
            f'ondelete="{_ON_DELETE_SQL[col.fk.on_delete]}")'
        )
    parts.append(f"nullable={col.nullable}")
    default = db_schema.sa_server_default_code(snap)
    if default is not None:
        parts.append(f"server_default={default}")
    return f"sa.Column({', '.join(parts)})"


def generate_model_file_fastapi(table: db_schema.ResolvedTable) -> GeneratedFile:
    # __table_args__ names every constraint and index exactly as the
    # migration that created them did (both read db_schema), so
    # `alembic revision --autogenerate` finds nothing to change.
    table_args = [
        f"sa.UniqueConstraint({_py_str(c.column)}, name={_py_str(c.unique_constraint_name)}),"
        for c in table.columns
        if c.unique
    ]
    table_args += [
        f"sa.CheckConstraint({_py_str(chk.sql)}, name={_py_str(chk.constraint_name)}),"
        for chk in table.checks
    ]
    for idx in table.indexes:
        cols = ", ".join(_py_str(c) for c in idx.columns)
        table_args.append(
            f"sa.Index({_py_str(idx.name)}, {cols}{', unique=True' if idx.unique else ''}),"
        )

    lines = [
        f'"""{_docstring_text(_heading(table))}',
        "",
        "Deterministically generated by VengaiCode from the Architecture tab (no AI",
        "call). The database table itself is created and changed by the versioned",
        "migrations in migrations/versions/; this class describes it to the app.",
        '"""',
        "",
        "import sqlalchemy as sa",
        "",
        "from app.core.database import Base",
        "",
        "",
        f"class {table.class_name}(Base):",
        f"    __tablename__ = {_py_str(table.sql_name)}",
    ]
    if table_args:
        lines.append("    __table_args__ = (")
        lines += [f"        {arg}" for arg in table_args]
        lines.append("    )")
    lines += [
        "",
        "    id = sa.Column(sa.Integer(), primary_key=True, autoincrement=True)",
    ]
    lines += [f"    {c.column} = {_sa_column_code(c)}" for c in table.columns]
    lines += [
        "    created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True)",
        "    updated_at = sa.Column(",
        "        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=True",
        "    )",
        "",
        f"    # VENGAI:CUSTOM:{table.slug}_model:start",
        f"    # Add relationships, validators or computed properties for {table.class_name} here.",
        "    # A new column belongs in the Architecture tab instead, so a migration adds",
        "    # it to the database (or write one yourself: alembic revision --autogenerate).",
        "    # This block is preserved across future regenerations.",
        f"    # VENGAI:CUSTOM:{table.slug}_model:end",
    ]
    return GeneratedFile(
        path=f"backend/models/{table.slug}.py",
        language="python",
        content="\n".join(lines) + "\n",
        description=f"Deterministic SQLAlchemy model for {table.name}",
    )


# Capitalized names routes/api.py imports. A table whose model class would
# be called one of these (a table named "Decimal", "Field"...) is imported
# as <Class>Model instead, so neither name hides the other.
_ROUTES_IMPORTED_NAMES = frozenset(
    {
        "APIRouter",
        "Any",
        "AsyncSession",
        "BaseModel",
        "ConfigDict",
        "Decimal",
        "Depends",
        "Field",
        "HTTPException",
        "IntegrityError",
        "Optional",
    }
)

# Lower-case type names a request model's annotations use. A field called
# e.g. "date" becomes a class attribute, and every LATER annotation in that
# class body would then read the attribute (None) instead of the type — so
# when any field has one of these names, the type is used under an alias.
_SHADOWABLE_TYPES = ("str", "int", "float", "bool", "date", "datetime")


class _PyTypes:
    def __init__(self, field_names: set[str]):
        self.clash = {t for t in _SHADOWABLE_TYPES if t in field_names}
        self.used: set[str] = set()

    def ref(self, type_code: str) -> str:
        self.used.add(type_code)
        return f"_{type_code}" if type_code in self.clash else type_code

    def import_lines(self) -> tuple[list[str], list[str]]:
        """(stdlib import lines, alias lines for shadowed built-ins)."""
        imports = []
        dt_names = []
        for name in ("date", "datetime"):
            if name in self.used:
                dt_names.append(f"{name} as _{name}" if name in self.clash else name)
        if dt_names:
            imports.append(f"from datetime import {', '.join(dt_names)}")
        if "Decimal" in self.used:
            imports.append("from decimal import Decimal")
        aliases = [
            f"_{name} = {name}"
            for name in ("str", "int", "float", "bool")
            if name in self.used and name in self.clash
        ]
        return imports, aliases


def _model_refs(schema: db_schema.ResolvedSchema) -> dict[str, str]:
    return {
        t.sql_name: (
            f"{t.class_name}Model"
            if t.class_name in _ROUTES_IMPORTED_NAMES
            else t.class_name
        )
        for t in schema.tables
    }


def _pydantic_field_line(
    col: db_schema.ResolvedColumn, types: _PyTypes, mode: str
) -> str:
    type_code = db_schema.python_type_code(col.snapshot())
    ann = (
        types.ref(type_code)
        if type_code in _SHADOWABLE_TYPES or type_code == "Decimal"
        else type_code
    )
    constraints = []
    if col.type == "string":
        constraints.append(f"max_length={col.length}")
    if col.type == "decimal":
        constraints += [
            f"max_digits={db_schema.DECIMAL_PRECISION}",
            f"decimal_places={db_schema.DECIMAL_SCALE}",
        ]
    if mode == "create" and not col.nullable and col.default is None:
        # Required: no default for the database to fall back on.
        return f"    {col.column}: {ann}" + (
            f" = Field({', '.join(constraints)})" if constraints else ""
        )
    if col.nullable and type_code != "Any":
        ann = f"Optional[{ann}]"
    # A NOT NULL field that may be left out keeps its plain type: omitting it
    # is fine (the default applies, or on update the value is kept), but an
    # explicit null is rejected with a 422 instead of reaching the database.
    if not constraints:
        return f"    {col.column}: {ann} = None"
    return (
        f"    {col.column}: {ann} = Field({', '.join(['default=None', *constraints])})"
    )


def _constraint_entries(table: db_schema.ResolvedTable) -> list[tuple[str, int, str]]:
    """(text to look for in the database's error, HTTP status, message).
    SQLite reports a failed UNIQUE by its columns and a failed CHECK by
    its name; Postgres names the constraint — so both keys are listed."""
    entries = []

    def unique_message(columns: list[str]) -> str:
        return f"Another record in {table.name} already has this {', '.join(columns)}."

    for c in table.columns:
        if c.unique:
            msg = unique_message([c.name])
            entries += [
                (c.unique_constraint_name, 409, msg),
                (f"{table.sql_name}.{c.column}", 409, msg),
            ]
    for idx in table.indexes:
        if idx.unique:
            display = [
                next((c.name for c in table.columns if c.column == col), col)
                for col in idx.columns
            ]
            msg = unique_message(display)
            sqlite_key = ", ".join(f"{table.sql_name}.{col}" for col in idx.columns)
            entries += [(idx.name, 409, msg), (sqlite_key, 409, msg)]
    for chk in table.checks:
        entries.append(
            (
                chk.constraint_name,
                422,
                f'{table.name}: breaks the rule "{chk.name}" ({chk.sql}).',
            )
        )
    return entries


def _crud_block_fastapi(
    table: db_schema.ResolvedTable,
    schema: db_schema.ResolvedSchema,
    refs: dict[str, str],
    types: _PyTypes,
) -> list[str]:
    model = refs[table.sql_name]
    create_name, update_name = f"{table.class_name}Create", f"{table.class_name}Update"
    references_name = f"_{_upper(table.slug)}_REFERENCES"
    label = _py_str(table.name)
    path = f"/{table.sql_name}"
    config = (
        ["    model_config = ConfigDict(protected_namespaces=())", ""]
        if any(c.column.startswith("model_") for c in table.columns)
        else []
    )

    lines = [f"# ─── {_one_line(table.name)} ───", f"class {create_name}(BaseModel):"]
    lines += config
    lines += [_pydantic_field_line(c, types, "create") for c in table.columns] or [
        "    pass"
    ]
    lines += ["", "", f"class {update_name}(BaseModel):"]
    lines += config
    lines += [_pydantic_field_line(c, types, "update") for c in table.columns] or [
        "    pass"
    ]
    lines += ["", ""]

    fk_columns = [c for c in table.columns if c.fk]
    lines.append(f"{references_name} = [")
    for c in fk_columns:
        parent = schema.table(c.fk.ref_table_sql)
        lines.append(
            f"    ({_py_str(c.column)}, {refs[parent.sql_name]}, {_py_str(c.fk.ref_column)}, {_py_str(parent.name)}),"
        )
    lines += ["]", ""]

    blockers = [
        child.name
        for child, fk in schema.referencing(table.sql_name)
        if fk.fk.on_delete == "restrict"
    ]
    if blockers:
        restrict = f"Can't delete this record: {', '.join(sorted(set(blockers)))} still refer to it."
    else:
        restrict = "Can't delete this record: other records still refer to it."

    lines += [
        "",
        f'@router.get("{path}")',
        f"async def list_{table.sql_name}(db: AsyncSession = Depends(get_db)):",
        f"    result = await db.execute(select({model}).order_by({model}.id))",
        "    return result.scalars().all()",
        "",
        "",
        f'@router.post("{path}", status_code=201)',
        f"async def create_{table.slug}(payload: {create_name}, db: AsyncSession = Depends(get_db)):",
        "    data = payload.model_dump(exclude_unset=True)",
        f"    await _check_references(db, data, {references_name})",
        f"    item = {model}(**data)",
        "    db.add(item)",
        "    await _commit(db)",
        "    await db.refresh(item)",
        "    return item",
        "",
        "",
        f'@router.get("{path}/{{item_id}}")',
        f"async def get_{table.slug}(item_id: int, db: AsyncSession = Depends(get_db)):",
        f"    return await _get_or_404(db, {model}, item_id, {label})",
        "",
        "",
        f'@router.put("{path}/{{item_id}}")',
        f"async def update_{table.slug}(item_id: int, payload: {update_name}, db: AsyncSession = Depends(get_db)):",
        f"    item = await _get_or_404(db, {model}, item_id, {label})",
        "    data = payload.model_dump(exclude_unset=True)",
        f"    await _check_references(db, data, {references_name})",
        "    for key, value in data.items():",
        "        setattr(item, key, value)",
        "    await _commit(db)",
        "    await db.refresh(item)",
        "    return item",
        "",
        "",
        f'@router.delete("{path}/{{item_id}}", status_code=204)',
        f"async def delete_{table.slug}(item_id: int, db: AsyncSession = Depends(get_db)):",
        f"    item = await _get_or_404(db, {model}, item_id, {label})",
        "    await db.delete(item)",
        f"    await _commit(db, restrict_message={_py_str(restrict)})",
        "    return None",
        "",
        "",
    ]
    return lines


_ROUTES_HELPERS_FASTAPI = '''

def _constraint_error(exc: IntegrityError, restrict_message: Optional[str] = None) -> HTTPException:
    """A readable HTTP error for a constraint the database refused."""
    text = str(exc.orig)
    for key, status, message in _CONSTRAINTS:
        if re.search(re.escape(key) + r"(?![\\w.])", text):
            return HTTPException(status_code=status, detail=message)
    if restrict_message and "foreign key" in text.lower():
        # Deleting a row that an ON DELETE RESTRICT foreign key still points at.
        return HTTPException(status_code=409, detail=restrict_message)
    return HTTPException(status_code=409, detail=f"The database refused this change: {text}")


async def _commit(db: AsyncSession, restrict_message: Optional[str] = None) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _constraint_error(exc, restrict_message) from None


async def _get_or_404(db: AsyncSession, model, item_id: int, label: str):
    item = await db.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{label} {item_id} not found.")
    return item


async def _check_references(db: AsyncSession, data: dict, references: list) -> None:
    """A 422 naming the field, instead of a database error, when a foreign
    key points at a row that doesn't exist."""
    for field, model, column, label in references:
        value = data.get(field)
        if value is None:
            continue
        target = getattr(model, column)
        found = await db.execute(select(target).where(target == value).limit(1))
        if found.first() is None:
            raise HTTPException(status_code=422, detail=f"{field}: no row in {label} has {column} {value!r}.")

'''


def generate_routes_file_fastapi(schema: db_schema.ResolvedSchema) -> GeneratedFile:
    tables = list(schema.tables)
    refs = _model_refs(schema)
    field_names = {c.column for t in tables for c in t.columns}
    types = _PyTypes(field_names)

    body: list[str] = []
    for table in tables:
        body += _crud_block_fastapi(table, schema, refs, types)

    constraints = [entry for t in tables for entry in _constraint_entries(t)]
    # Longest key first, so "orders.status_code" is tried before "orders.status".
    constraints.sort(key=lambda e: len(e[0]), reverse=True)

    stdlib, aliases = types.import_lines()
    uses_any = any(
        db_schema.python_type_code(c.snapshot()) == "Any"
        for t in tables
        for c in t.columns
    )
    uses_field = any(c.type in ("string", "decimal") for t in tables for c in t.columns)
    uses_config = any(c.column.startswith("model_") for t in tables for c in t.columns)

    lines = [
        "# REST CRUD routes for every table — deterministically generated by VengaiCode",
        "# from the Architecture tab (no AI call). Everything outside the",
        "# VENGAI:CUSTOM:extra_routes block is rewritten on every regeneration.",
        "",
        "import re",
    ]
    lines += stdlib
    lines.append(f"from typing import {'Any, ' if uses_any else ''}Optional")
    pydantic_names = (
        ["BaseModel"]
        + (["ConfigDict"] if uses_config else [])
        + (["Field"] if uses_field else [])
    )
    lines += [
        "",
        "from fastapi import APIRouter, Depends, HTTPException",
        f"from pydantic import {', '.join(pydantic_names)}",
        "from sqlalchemy import select",
        "from sqlalchemy.exc import IntegrityError",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "",
        "from app.core.database import get_db",
    ]
    for table in tables:
        ref = refs[table.sql_name]
        alias = f" as {ref}" if ref != table.class_name else ""
        lines.append(f"from models.{table.slug} import {table.class_name}{alias}")
    if aliases:
        lines += [
            "",
            "# A field named like a built-in type would hide it inside its request model.",
        ]
        lines += aliases
    lines += [
        "",
        "# Mounted under /api — the paths the generated screens call (and the",
        "# installer rewrites to the bundled backend's local address).",
        'router = APIRouter(prefix="/api")',
        "",
        "# What each database constraint means, so a violation comes back as a",
        "# sentence instead of a raw database error: (text to find, status, message).",
        "_CONSTRAINTS = [",
    ]
    lines += [
        f"    ({_py_str(key)}, {status}, {_py_str(message)}),"
        for key, status, message in constraints
    ]
    lines.append("]")
    lines += _ROUTES_HELPERS_FASTAPI.split("\n")
    lines += body
    lines += [
        "# VENGAI:CUSTOM:extra_routes:start",
        "# Add custom, non-CRUD endpoints here — this block is preserved across regenerations.",
        '# Example: @router.get("/reports/summary") ...',
        "# VENGAI:CUSTOM:extra_routes:end",
    ]
    return GeneratedFile(
        path="backend/routes/api.py",
        language="python",
        content="\n".join(lines) + "\n",
        description="Deterministic CRUD routes for every database table",
    )


# ═══════════════════════════════════════════════
#  Express backend (Mongoose over MongoDB, migrate-mongo migrations)
# ═══════════════════════════════════════════════
def _mongoose_type(
    col: db_schema.ResolvedColumn, schema: db_schema.ResolvedSchema
) -> str:
    if col.fk and col.fk.ref_column == "id":
        return "mongoose.Schema.Types.ObjectId"
    return {
        "string": "String",
        "text": "String",
        "integer": "Number",
        "float": "Number",
        "decimal": "Number",
        "boolean": "Boolean",
        "date": "Date",
        "datetime": "Date",
        "json": "mongoose.Schema.Types.Mixed",
    }[col.type]


def _mongoose_default(col: db_schema.ResolvedColumn) -> str | None:
    default = col.default
    if default is None:
        return None
    if default["kind"] == "now":
        return "Date.now"
    if default["kind"] == "today":
        return "() => new Date(new Date().toISOString().slice(0, 10))"
    value = default["value"]
    if col.type in ("date", "datetime"):
        return f"() => {migrations_gen.js_value_literal(value, col.type)}"
    if col.type == "json":
        # A function, so every document gets its own copy of the object.
        return f"() => ({migrations_gen.js_json_literal(value)})"
    return migrations_gen.js_value_literal(value, col.type)


def _mongoose_field(
    col: db_schema.ResolvedColumn, schema: db_schema.ResolvedSchema
) -> str:
    parts = [f"type: {_mongoose_type(col, schema)}"]
    if col.fk and col.fk.ref_column == "id":
        parts.append(f"ref: {js_string_literal(col.fk.ref_class)}")
    if not col.nullable:
        parts.append("required: true")
    if col.type == "string" and col.length:
        parts.append(f"maxlength: {col.length}")
    if col.type == "integer" and not (col.fk and col.fk.ref_column == "id"):
        parts.append(
            "validate: { validator: (v) => v == null || Number.isInteger(v), message: '{PATH} must be a whole number' }"
        )
    default = _mongoose_default(col)
    if default is not None:
        parts.append(f"default: {default}")
    return f"    {col.column}: {{ {', '.join(parts)} }},"


def generate_model_file_express(
    table: db_schema.ResolvedTable, schema: db_schema.ResolvedSchema
) -> GeneratedFile:
    schema_var = f"{table.class_name}Schema"
    ts = db_schema.snapshot(schema)["tables"][table.sql_name]
    lines = [
        "const mongoose = require('mongoose');",
        "const { applyChecks } = require('../lib/checks');",
        "",
        f"// {_js_comment_text(_heading(table))}",
        "// Deterministically generated by VengaiCode from the Architecture tab (no AI",
        "// call). The collection, its validator and its indexes are created by the",
        "// migrations in migrations/ (autoCreate and autoIndex are off); the index",
        "// declarations below mirror what they built.",
        f"const {schema_var} = new mongoose.Schema(",
        "  {",
    ]
    lines += [_mongoose_field(c, schema) for c in table.columns]
    lines += [
        "  },",
        "  {",
        f"    collection: {js_string_literal(table.sql_name)},",
        "    timestamps: { createdAt: 'created_at', updatedAt: 'updated_at' },",
        "    autoCreate: false,",
        "    autoIndex: false,",
        "  }",
        ");",
    ]
    specs = migrations_gen.mongo_index_specs(ts)
    if specs:
        lines.append("")
        lines += [
            f"{schema_var}.index({json.dumps(keys)}, {json.dumps(options)});"
            for keys, options in specs
        ]
    if table.checks:
        # MongoDB has no CHECK constraints; lib/checks.js evaluates each rule
        # (parsed, never as code) before a document is saved.
        checks = [
            "  { "
            + ", ".join(
                [
                    f"name: {js_string_literal(chk.name)}",
                    f"constraint: {js_string_literal(chk.constraint_name)}",
                    f"sql: {js_string_literal(chk.sql)}",
                    f"fields: {migrations_gen.js_json_literal(list(chk.fields))}",
                    f"ast: {migrations_gen.js_json_literal(chk.ast)}",
                ]
            )
            + " },"
            for chk in table.checks
        ]
        column_types = ", ".join(
            f"{js_string_literal(k)}: {js_string_literal(v)}"
            for k, v in table.column_types().items()
        )
        lines += (
            ["", f"applyChecks({schema_var}, ["]
            + checks
            + [f"], {{ {column_types} }});"]
        )
    lines += [
        "",
        f"// VENGAI:CUSTOM:{table.slug}_model:start",
        f"// Add custom virtuals, methods or hooks for {schema_var} here",
        f"// (e.g. {schema_var}.methods.someMethod = function () {{ ... }};).",
        "// A new field belongs in the Architecture tab instead: the collection's",
        "// validator only accepts the fields the migrations declared.",
        "// This block is preserved across future regenerations.",
        f"// VENGAI:CUSTOM:{table.slug}_model:end",
        "",
        f"module.exports = mongoose.model({js_string_literal(table.class_name)}, {schema_var});",
    ]
    return GeneratedFile(
        path=f"backend/models/{table.slug}.js",
        language="javascript",
        content="\n".join(lines) + "\n",
        description=f"Deterministic Mongoose model for {table.name}",
    )


_CHECKS_JS = r"""// Check constraints for the Mongoose models, written by VengaiCode.
//
// MongoDB has no CHECK constraints, so every rule from the Architecture tab
// is evaluated here before a document is saved, with exactly the meaning it
// has as a SQL CHECK constraint (and in VengaiCode's own validation of seed
// rows): three-valued logic, where anything compared with a missing value is
// "unknown", and only a definite false rejects the document. Rules arrive as
// parsed trees, never as code, so a rule can't run anything but itself.

const NUMERIC = new Set(['integer', 'float', 'decimal']);
const TEMPORAL = new Set(['date', 'datetime']);
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const ZONED = /(?:[zZ]|[+-]\d{2}:?\d{2})$/;

function toNumber(value) {
  if (value === null || value === undefined || typeof value === 'boolean') return null;
  if (typeof value === 'number') return Number.isNaN(value) ? null : value;
  const text = String(value).trim();
  if (text === '') return null;
  const n = Number(text);
  return Number.isNaN(n) ? null : n;
}

function toTime(value) {
  if (value === null || value === undefined) return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value.getTime();
  if (typeof value !== 'string') return null;
  const text = value.trim();
  // Date constants in a rule carry no time zone; they mean UTC, like every
  // date MongoDB stores.
  let iso = text;
  if (DATE_ONLY.test(text)) iso = `${text}T00:00:00Z`;
  else if (!ZONED.test(text)) iso = `${text}Z`;
  const time = Date.parse(iso);
  return Number.isNaN(time) ? null : time;
}

function readField(doc, field) {
  // The implicit "id" of every table is MongoDB's _id.
  const key = field === 'id' ? '_id' : field;
  const value = typeof doc.get === 'function' ? doc.get(key) : doc[key];
  return value === undefined ? null : value;
}

function operand(node, doc, types) {
  if ('field' in node) return [readField(doc, node.field), types[node.field] || 'string'];
  if ('length' in node) {
    const [inner] = operand(node.length, doc, types);
    // Counted in characters (code points), as SQL's LENGTH() does.
    return [inner === null ? null : [...String(inner)].length, 'integer'];
  }
  const value = node.value;
  if (typeof value === 'number') return [value, 'float'];
  if (typeof value === 'boolean') return [value, 'boolean'];
  return [value, 'string'];
}

function coercePair(a, aType, b, bType) {
  if (TEMPORAL.has(aType) || TEMPORAL.has(bType)) return [toTime(a), toTime(b)];
  if (NUMERIC.has(aType) || NUMERIC.has(bType)) return [toNumber(a), toNumber(b)];
  return [a, b];
}

function compare(op, a, b) {
  if (a === null || b === null) return null;
  if (typeof a !== typeof b) {
    // Different kinds of value are simply unequal, and can't be ordered.
    if (op === '=') return false;
    if (op === '<>') return true;
    return null;
  }
  switch (op) {
    case '=':
      return a === b;
    case '<>':
      return a !== b;
    case '<':
      return a < b;
    case '<=':
      return a <= b;
    case '>':
      return a > b;
    case '>=':
      return a >= b;
    default:
      return null;
  }
}

function asciiLower(text) {
  // LIKE ignores the case of A-Z only, exactly as SQLite's LIKE does.
  return text.replace(/[A-Z]/g, (ch) => ch.toLowerCase());
}

function likeMatch(pattern, text) {
  // % matches any run of characters (including none), _ exactly one.
  const p = [...asciiLower(pattern)];
  const t = [...asciiLower(text)];
  let pi = 0;
  let ti = 0;
  let star = -1;
  let mark = 0;
  while (ti < t.length) {
    if (pi < p.length && p[pi] === '%') {
      star = pi;
      pi += 1;
      mark = ti;
    } else if (pi < p.length && (p[pi] === '_' || p[pi] === t[ti])) {
      pi += 1;
      ti += 1;
    } else if (star !== -1) {
      pi = star + 1;
      mark += 1;
      ti = mark;
    } else {
      return false;
    }
  }
  while (pi < p.length && p[pi] === '%') pi += 1;
  return pi === p.length;
}

function evaluate(node, doc, types) {
  if ('and' in node) {
    const results = node.and.map((child) => evaluate(child, doc, types));
    if (results.includes(false)) return false;
    return results.includes(null) ? null : true;
  }
  if ('or' in node) {
    const results = node.or.map((child) => evaluate(child, doc, types));
    if (results.includes(true)) return true;
    return results.includes(null) ? null : false;
  }
  if ('not' in node) {
    const inner = evaluate(node.not, doc, types);
    return inner === null ? null : !inner;
  }
  if ('cmp' in node) {
    const [a, aType] = operand(node.left, doc, types);
    const [b, bType] = operand(node.right, doc, types);
    const [x, y] = coercePair(a, aType, b, bType);
    return compare(node.cmp, x, y);
  }
  if ('is_null' in node) {
    const [value] = operand(node.is_null, doc, types);
    const result = value === null;
    return node.negated ? !result : result;
  }
  if ('in' in node) {
    const [value, valueType] = operand(node.in, doc, types);
    if (value === null) return null;
    let hit = false;
    for (const candidate of node.values) {
      const [x, y] = coercePair(value, valueType, candidate, typeof candidate === 'number' ? 'float' : 'string');
      if (compare('=', x, y) === true) {
        hit = true;
        break;
      }
    }
    return node.negated ? !hit : hit;
  }
  if ('between' in node) {
    const [value, valueType] = operand(node.between, doc, types);
    const [low, lowType] = operand(node.low, doc, types);
    const [high, highType] = operand(node.high, doc, types);
    const [v1, lo] = coercePair(value, valueType, low, lowType);
    const [v2, hi] = coercePair(value, valueType, high, highType);
    const ge = compare('>=', v1, lo);
    const le = compare('<=', v2, hi);
    if (ge === false || le === false) return node.negated ? true : false;
    if (ge === null || le === null) return null;
    return node.negated ? false : true;
  }
  if ('like' in node) {
    const [value] = operand(node.like, doc, types);
    if (value === null) return null;
    const hit = likeMatch(node.pattern, String(value));
    return node.negated ? !hit : hit;
  }
  throw new Error(`Unknown check rule: ${JSON.stringify(node)}`);
}

/** true / false / null ("unknown"). A rule rejects a document only on false. */
function evaluateCheck(ast, doc, types = {}) {
  return evaluate(ast, doc, types);
}

/** Installs a pre-validate hook enforcing every check of one schema. */
function applyChecks(schema, checks, types) {
  if (!checks.length) return;
  schema.pre('validate', function enforceChecks(next) {
    for (const check of checks) {
      if (evaluate(check.ast, this, types) === false) {
        const field = check.fields.length ? check.fields[0] : 'id';
        this.invalidate(field === 'id' ? '_id' : field, `Breaks the rule "${check.name}": ${check.sql}`);
      }
    }
    next();
  });
}

module.exports = { applyChecks, evaluateCheck };
"""


def generate_checks_file_express() -> GeneratedFile:
    return GeneratedFile(
        path="backend/lib/checks.js",
        language="javascript",
        content=_CHECKS_JS,
        description="Check-constraint evaluation for the Mongoose models",
    )


_ROUTES_HELPERS_EXPRESS = r"""// Passes a rejected promise from an async handler on to the error handler below.
const asyncHandler = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);

class RequestError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function pick(body, fields) {
  const out = {};
  for (const field of fields) {
    if (body && Object.prototype.hasOwnProperty.call(body, field)) out[field] = body[field];
  }
  return out;
}

async function findOr404(Model, id, label) {
  const doc = await Model.findById(id);
  if (!doc) throw new RequestError(404, `${label} ${id} not found.`);
  return doc;
}

function matchFor(ref, doc) {
  return { [ref.field]: ref.toField === '_id' ? doc._id : doc.get(ref.toField) };
}

// A foreign key must point at a document that exists (MongoDB won't check).
async function assertReferencesExist(Model, doc) {
  for (const ref of REFERENCES) {
    if (ref.from !== Model) continue;
    const value = doc.get(ref.field);
    if (value === null || value === undefined) continue;
    if (!(await ref.to.exists({ [ref.toField]: value }))) {
      throw new RequestError(400, `${ref.field}: no record in ${ref.toLabel} has that ${ref.toField === '_id' ? 'id' : ref.toField}.`);
    }
  }
}

// ON DELETE rules, applied here because MongoDB has no foreign keys. First
// the whole cascade is checked for a RESTRICT that would forbid it, so a
// refused delete changes nothing; then children are deleted (cascade) or
// unlinked (set_null) before the document itself. Not a transaction: a
// server that dies halfway leaves the part it already did.
async function assertDeletable(Model, doc, seen) {
  const key = `${Model.modelName}:${doc._id}`;
  if (seen.has(key)) return;
  seen.add(key);
  for (const ref of REFERENCES) {
    if (ref.to !== Model) continue;
    const match = matchFor(ref, doc);
    if (ref.onDelete === 'restrict') {
      if (await ref.from.exists(match)) {
        throw new RequestError(409, `Can't delete this record: ${ref.fromLabel} still refer to it.`);
      }
    } else if (ref.onDelete === 'cascade') {
      for (const child of await ref.from.find(match)) await assertDeletable(ref.from, child, seen);
    }
  }
}

async function deleteWithRules(Model, doc, seen) {
  const key = `${Model.modelName}:${doc._id}`;
  if (seen.has(key)) return;
  seen.add(key);
  for (const ref of REFERENCES) {
    if (ref.to !== Model) continue;
    const match = matchFor(ref, doc);
    if (ref.onDelete === 'cascade') {
      for (const child of await ref.from.find(match)) await deleteWithRules(ref.from, child, seen);
    } else if (ref.onDelete === 'set_null') {
      await ref.from.updateMany(match, { $set: { [ref.field]: null } });
    }
  }
  await Model.deleteOne({ _id: doc._id });
}
"""

_ROUTES_ERROR_HANDLER_EXPRESS = r"""// Errors from every route above, as { error } with a fitting status.
// eslint-disable-next-line no-unused-vars
router.use((err, req, res, next) => {
  if (err instanceof RequestError) return res.status(err.status).json({ error: err.message });
  if (err instanceof mongoose.Error.ValidationError) {
    const details = Object.values(err.errors).map((e) => e.message);
    return res.status(400).json({ error: details.join('\n'), details });
  }
  if (err instanceof mongoose.Error.CastError) {
    return res.status(400).json({ error: `Invalid value for ${err.path}.` });
  }
  if (err && err.code === 11000) {
    const name = Object.keys(DUPLICATE_MESSAGES).find((n) => String(err.message).includes(`index: ${n} `));
    return res.status(409).json({ error: name ? DUPLICATE_MESSAGES[name] : 'Another record already has this value.' });
  }
  if (err && err.code === 121) {
    return res.status(400).json({ error: "The database refused this record: it doesn't match the collection's schema." });
  }
  console.error(err);
  return res.status(500).json({ error: 'Something went wrong on the server.' });
});
"""


def _crud_block_express(table: db_schema.ResolvedTable) -> list[str]:
    model = f"{table.class_name}Model"
    fields_const = f"{_upper(table.slug)}_FIELDS"
    label = js_string_literal(table.name)
    path = f"/{table.sql_name}"
    return [
        f"// {_js_comment_text(table.name)}",
        f"router.get('{path}', asyncHandler(async (req, res) => {{",
        f"  res.json(await {model}.find().sort({{ _id: 1 }}));",
        "}));",
        "",
        f"router.post('{path}', asyncHandler(async (req, res) => {{",
        f"  const doc = new {model}(pick(req.body, {fields_const}));",
        f"  await assertReferencesExist({model}, doc);",
        "  await doc.save();",
        "  res.status(201).json(doc);",
        "}));",
        "",
        f"router.get('{path}/:id', asyncHandler(async (req, res) => {{",
        f"  res.json(await findOr404({model}, req.params.id, {label}));",
        "}));",
        "",
        f"router.put('{path}/:id', asyncHandler(async (req, res) => {{",
        f"  const doc = await findOr404({model}, req.params.id, {label});",
        f"  doc.set(pick(req.body, {fields_const}));",
        f"  await assertReferencesExist({model}, doc);",
        "  await doc.save();",
        "  res.json(doc);",
        "}));",
        "",
        f"router.delete('{path}/:id', asyncHandler(async (req, res) => {{",
        f"  const doc = await findOr404({model}, req.params.id, {label});",
        f"  await assertDeletable({model}, doc, new Set());",
        f"  await deleteWithRules({model}, doc, new Set());",
        "  res.status(204).end();",
        "}));",
        "",
    ]


def generate_routes_file_express(schema: db_schema.ResolvedSchema) -> GeneratedFile:
    tables = list(schema.tables)
    lines = [
        "// REST CRUD routes for every table — deterministically generated by VengaiCode",
        "// from the Architecture tab (no AI call). Everything outside the",
        "// VENGAI:CUSTOM:extra_routes block is rewritten on every regeneration.",
        "const express = require('express');",
        "const mongoose = require('mongoose');",
    ]
    # <Class>Model, never the bare class name: a table called "Date" or
    # "Map" would otherwise hide the JavaScript built-in in this file.
    lines += [
        f"const {t.class_name}Model = require('../models/{t.slug}');" for t in tables
    ]
    lines += ["", "const router = express.Router();", ""]
    lines.append(
        "// The fields a request may set, per table (never _id or the timestamps)."
    )
    for t in tables:
        lines.append(
            f"const {_upper(t.slug)}_FIELDS = [{', '.join(js_string_literal(c.column) for c in t.columns)}];"
        )
    lines += [
        "",
        "// Every foreign key: who points at whom, and what happens on delete.",
    ]
    lines.append("const REFERENCES = [")
    for t in tables:
        for c in t.columns:
            if not c.fk:
                continue
            parent = schema.table(c.fk.ref_table_sql)
            to_field = "_id" if c.fk.ref_column == "id" else c.fk.ref_column
            lines.append(
                "  { "
                + ", ".join(
                    [
                        f"from: {t.class_name}Model",
                        f"field: {js_string_literal(c.column)}",
                        f"to: {parent.class_name}Model",
                        f"toField: {js_string_literal(to_field)}",
                        f"onDelete: {js_string_literal(c.fk.on_delete)}",
                        f"fromLabel: {js_string_literal(t.name)}",
                        f"toLabel: {js_string_literal(parent.name)}",
                    ]
                )
                + " },"
            )
    lines += ["];", ""]
    lines.append("// Readable messages for the unique indexes the migrations created.")
    lines.append("const DUPLICATE_MESSAGES = {")
    for t in tables:
        for key, status, message in _constraint_entries(t):
            if status == 409 and "." not in key:
                lines.append(f"  {key}: {js_string_literal(message)},")
    lines += ["};", ""]
    lines += _ROUTES_HELPERS_EXPRESS.split("\n")
    for t in tables:
        lines += _crud_block_express(t)
    lines += [
        "// VENGAI:CUSTOM:extra_routes:start",
        "// Add custom, non-CRUD endpoints here — this block is preserved across regenerations.",
        "// Example: router.get('/reports/summary', async (req, res) => { ... });",
        "// VENGAI:CUSTOM:extra_routes:end",
        "",
    ]
    lines += _ROUTES_ERROR_HANDLER_EXPRESS.split("\n")
    lines += ["module.exports = router;"]
    return GeneratedFile(
        path="backend/routes/api.js",
        language="javascript",
        content="\n".join(lines) + "\n",
        description="Deterministic CRUD routes for every database table",
    )


# ═══════════════════════════════════════════════
#  Frontend (React and Vue share the field description and helpers)
# ═══════════════════════════════════════════════
_CRUD_JS = r"""// Shared helpers for the generated CRUD screens, written by VengaiCode.
//
// Every screen describes its table with a FIELDS list, one entry per column:
//   { key, label, type, required, maxLength, default, ref }
// type is string, text, integer, float, decimal, boolean, date, datetime,
// json, or reference (a MongoDB document id). For a foreign key, ref says
// where the choices come from: { url, valueKey, labelKey }.

const ZONED = /(?:[zZ]|[+-]\d{2}:?\d{2})$/;

/** The server's error for a failed request, as readable text. */
export async function errorText(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  const detail = body ? body.detail ?? body.error ?? body.message : null;
  if (Array.isArray(detail)) {
    // FastAPI's 422: one entry per invalid field.
    return detail
      .map((d) => (d && d.msg ? `${(d.loc || []).filter((p) => p !== 'body').join('.')}: ${d.msg}` : String(d)))
      .join('\n');
  }
  if (detail) return String(detail);
  return `Request failed with status ${res.status}.`;
}

/** A fresh, empty form: checkboxes start at their field's default. */
export function emptyForm(fields) {
  const form = {};
  for (const field of fields) {
    form[field.key] = field.type === 'boolean' ? field.default === true : '';
  }
  return form;
}

/**
 * Form values -> request body. An empty input is left out, so the database
 * applies the field's default (or leaves it empty). Throws an Error with a
 * readable message for a value that can't be sent.
 */
export function toPayload(fields, form) {
  const body = {};
  for (const field of fields) {
    const raw = form[field.key];
    if (field.type === 'boolean') {
      body[field.key] = Boolean(raw);
      continue;
    }
    if (raw === undefined || raw === null || raw === '') continue;
    const text = String(raw).trim();
    switch (field.type) {
      case 'string':
      case 'text':
        body[field.key] = String(raw);
        break;
      case 'integer': {
        const n = Number(text);
        if (text === '' || !Number.isInteger(n)) throw new Error(`${field.label} must be a whole number.`);
        body[field.key] = n;
        break;
      }
      case 'float': {
        const n = Number(text);
        if (text === '' || !Number.isFinite(n)) throw new Error(`${field.label} must be a number.`);
        body[field.key] = n;
        break;
      }
      case 'decimal':
        if (!/^-?\d+(?:\.\d+)?$/.test(text)) throw new Error(`${field.label} must be a number like 12.50.`);
        body[field.key] = text;
        break;
      case 'datetime': {
        const when = new Date(text);
        if (Number.isNaN(when.getTime())) throw new Error(`${field.label} must be a date and time.`);
        body[field.key] = when.toISOString();
        break;
      }
      case 'json':
        try {
          body[field.key] = JSON.parse(text);
        } catch {
          throw new Error(`${field.label} must be valid JSON.`);
        }
        break;
      default:
        // date (the date input already gives YYYY-MM-DD) and reference ids
        if (text !== '') body[field.key] = text;
    }
  }
  return body;
}

/** A foreign-key choice's visible text. */
export function optionLabel(field, row) {
  const label = field.ref.labelKey ? row[field.ref.labelKey] : null;
  return label === null || label === undefined || label === '' ? String(row[field.ref.valueKey]) : String(label);
}

/** How a stored value reads in the table. */
export function displayValue(field, value, options) {
  if (value === null || value === undefined) return '';
  if (field.ref) {
    const row = (options[field.key] || []).find((r) => String(r[field.ref.valueKey]) === String(value));
    if (row) return optionLabel(field, row);
  }
  switch (field.type) {
    case 'boolean':
      return value ? '✓' : '—';
    case 'json':
      return JSON.stringify(value);
    case 'datetime': {
      // SQLite hands back UTC date-times without a zone; read them as UTC.
      const text = String(value);
      const when = new Date(ZONED.test(text) ? text : `${text}Z`);
      return Number.isNaN(when.getTime()) ? text : when.toLocaleString();
    }
    default:
      return String(value);
  }
}
"""


def generate_crud_helpers_file() -> GeneratedFile:
    return GeneratedFile(
        path="frontend/src/lib/crud.js",
        language="javascript",
        content=_CRUD_JS,
        description="Shared helpers for the generated CRUD screens",
    )


def _label_column(table: db_schema.ResolvedTable) -> str | None:
    """What a foreign-key dropdown shows for a row of `table`: its first
    text field that isn't itself a foreign key (else the id)."""
    return next(
        (c.column for c in table.columns if c.type in ("string", "text") and not c.fk),
        None,
    )


def _fields_js(
    table: db_schema.ResolvedTable, schema: db_schema.ResolvedSchema, backend: str
) -> list[str]:
    lines = ["const FIELDS = ["]
    for c in table.columns:
        parts = [
            f"key: {js_string_literal(c.column)}",
            f"label: {js_string_literal(c.name)}",
        ]
        field_type = c.type
        ref = None
        if c.fk:
            parent = schema.table(c.fk.ref_table_sql)
            value_key = (
                "_id"
                if backend == "express" and c.fk.ref_column == "id"
                else c.fk.ref_column
            )
            if backend == "express" and c.fk.ref_column == "id":
                field_type = "reference"
            label_key = _label_column(parent)
            ref = (
                "{ "
                + f"url: {js_string_literal('/api/' + parent.sql_name)}, valueKey: {js_string_literal(value_key)}, "
                + f"labelKey: {js_string_literal(label_key) if label_key else 'null'}"
                + " }"
            )
        # "required" drives the input's required attribute: nothing for the
        # database to fall back on. A checkbox is always sent, so never.
        required = not c.nullable and c.default is None and field_type != "boolean"
        default = "null"
        if field_type == "boolean" and c.default and c.default["kind"] == "literal":
            default = "true" if c.default["value"] else "false"
        parts += [
            f"type: {js_string_literal(field_type)}",
            f"required: {'true' if required else 'false'}",
            f"maxLength: {c.length if c.type == 'string' and c.length else 'null'}",
            f"default: {default}",
            f"ref: {ref or 'null'}",
        ]
        lines.append("  { " + ", ".join(parts) + " },")
    lines.append("];")
    return lines


_SCREEN_TEMPLATE_REACT = """import { useEffect, useState } from 'react';
import { displayValue, emptyForm, errorText, optionLabel, toPayload } from '../lib/crud';

// __HEADING__
// Deterministically generated by VengaiCode from the Architecture tab (no AI
// call). FIELDS describes the table's columns; the markup below is generic.
const TITLE = __TITLE__;
__FIELDS__

const INPUT_CLASS = 'border rounded px-2 py-1 text-sm';

export default function __COMPONENT__() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState(() => emptyForm(FIELDS));
  const [options, setOptions] = useState({});
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const res = await fetch('/api/__TABLE_SQL__');
      if (!res.ok) throw new Error(await errorText(res));
      setItems(await res.json());
    } catch (err) {
      setError(err.message);
    }
  };

  // The choices for every foreign-key field, from the table it points at.
  const loadOptions = async () => {
    const next = {};
    for (const field of FIELDS) {
      if (!field.ref) continue;
      try {
        const res = await fetch(field.ref.url);
        next[field.key] = res.ok ? await res.json() : [];
      } catch {
        next[field.key] = [];
      }
    }
    setOptions(next);
  };

  useEffect(() => {
    load();
    loadOptions();
  }, []);

  const setValue = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleCreate = async (e) => {
    e.preventDefault();
    setError('');
    let body;
    try {
      body = toPayload(FIELDS, form);
    } catch (err) {
      setError(err.message);
      return;
    }
    const res = await fetch('/api/__TABLE_SQL__', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      setError(await errorText(res));
      return;
    }
    setForm(emptyForm(FIELDS));
    load();
  };

  const handleDelete = async (id) => {
    setError('');
    const res = await fetch(`/api/__TABLE_SQL__/${id}`, { method: 'DELETE' });
    if (!res.ok) {
      setError(await errorText(res));
      return;
    }
    load();
  };

  const renderInput = (field) => {
    const id = `field-${field.key}`;
    const value = form[field.key] ?? '';
    const onChange = (e) => setValue(field.key, e.target.value);
    if (field.ref) {
      return (
        <select id={id} className={INPUT_CLASS} required={field.required} value={value} onChange={onChange}>
          <option value="">{field.required ? 'Choose…' : '— none —'}</option>
          {(options[field.key] || []).map((row) => (
            <option key={row[field.ref.valueKey]} value={row[field.ref.valueKey]}>
              {optionLabel(field, row)}
            </option>
          ))}
        </select>
      );
    }
    switch (field.type) {
      case 'boolean':
        return <input id={id} type="checkbox" checked={Boolean(form[field.key])} onChange={(e) => setValue(field.key, e.target.checked)} />;
      case 'text':
      case 'json':
        return <textarea id={id} className={INPUT_CLASS} rows={2} required={field.required} value={value} onChange={onChange} />;
      case 'integer':
        return <input id={id} className={INPUT_CLASS} type="number" step="1" required={field.required} value={value} onChange={onChange} />;
      case 'float':
      case 'decimal':
        return <input id={id} className={INPUT_CLASS} type="number" step="any" required={field.required} value={value} onChange={onChange} />;
      case 'date':
        return <input id={id} className={INPUT_CLASS} type="date" required={field.required} value={value} onChange={onChange} />;
      case 'datetime':
        return <input id={id} className={INPUT_CLASS} type="datetime-local" required={field.required} value={value} onChange={onChange} />;
      default:
        return (
          <input
            id={id}
            className={INPUT_CLASS}
            type="text"
            maxLength={field.maxLength || undefined}
            required={field.required}
            value={value}
            onChange={onChange}
          />
        );
    }
  };

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold mb-4">{TITLE}</h1>

      <form onSubmit={handleCreate} className="flex gap-3 mb-4 flex-wrap items-end">
        {FIELDS.map((field) => (
          <label key={field.key} htmlFor={`field-${field.key}`} className="flex flex-col gap-1 text-xs">
            <span>
              {field.label}
              {field.required ? ' *' : ''}
            </span>
            {renderInput(field)}
          </label>
        ))}
        <button type="submit" className="bg-black text-white px-3 py-1 rounded text-sm">Add</button>
      </form>

      {error && <p role="alert" className="text-red-600 text-sm mb-3 whitespace-pre-line">{error}</p>}

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b">
            {FIELDS.map((field) => (
              <th key={field.key} className="text-left p-2">{field.label}</th>
            ))}
            <th className="text-left p-2"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className="border-b">
              {FIELDS.map((field) => (
                <td key={field.key} className="p-2">{displayValue(field, item[field.key], options)}</td>
              ))}
              <td className="p-2">
                <button onClick={() => handleDelete(item.id)} className="text-red-600 text-xs">Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* VENGAI:CUSTOM:__SLOT_NAME__:start */}
      {/* Add custom UI for __SLOT_LABEL__ here — this block is preserved across regenerations. */}
      {/* VENGAI:CUSTOM:__SLOT_NAME__:end */}
    </div>
  );
}
"""


def generate_screen_file_react(
    table: db_schema.ResolvedTable, schema: db_schema.ResolvedSchema
) -> GeneratedFile:
    component_name = f"{table.class_name}Screen"
    content = (
        _SCREEN_TEMPLATE_REACT.replace("__COMPONENT__", component_name)
        .replace("__HEADING__", _js_comment_text(_heading(table)))
        .replace("__TITLE__", js_string_literal(table.name))
        .replace("__FIELDS__", "\n".join(_fields_js(table, schema, "fastapi")))
        .replace("__TABLE_SQL__", table.sql_name)
        .replace("__SLOT_NAME__", f"{table.slug}_screen")
        .replace("__SLOT_LABEL__", table.class_name)
    )
    return GeneratedFile(
        path=f"frontend/src/screens/{component_name}.jsx",
        language="javascript",
        content=content,
        description=f"Deterministic CRUD screen for {table.name}",
    )


# Mongoose documents key on _id, not id — a real difference from the
# SQLAlchemy side this screen has to render/act on correctly, not paper
# over with the same "id" everywhere.
_SCREEN_TEMPLATE_VUE = """<script setup>
import { onMounted, ref } from 'vue';
import { displayValue, emptyForm, errorText, optionLabel, toPayload } from '../lib/crud';

// __HEADING__
// Deterministically generated by VengaiCode from the Architecture tab (no AI
// call). FIELDS describes the table's columns; the markup below is generic.
const TITLE = __TITLE__;
__FIELDS__

const INPUT_TYPES = { integer: 'number', float: 'number', decimal: 'number', date: 'date', datetime: 'datetime-local' };

const items = ref([]);
const form = ref(emptyForm(FIELDS));
const options = ref({});
const error = ref('');

async function load() {
  try {
    const res = await fetch('/api/__TABLE_SQL__');
    if (!res.ok) throw new Error(await errorText(res));
    items.value = await res.json();
  } catch (err) {
    error.value = err.message;
  }
}

// The choices for every foreign-key field, from the table it points at.
async function loadOptions() {
  const next = {};
  for (const field of FIELDS) {
    if (!field.ref) continue;
    try {
      const res = await fetch(field.ref.url);
      next[field.key] = res.ok ? await res.json() : [];
    } catch {
      next[field.key] = [];
    }
  }
  options.value = next;
}

onMounted(() => {
  load();
  loadOptions();
});

async function handleCreate() {
  error.value = '';
  let body;
  try {
    body = toPayload(FIELDS, form.value);
  } catch (err) {
    error.value = err.message;
    return;
  }
  const res = await fetch('/api/__TABLE_SQL__', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    error.value = await errorText(res);
    return;
  }
  form.value = emptyForm(FIELDS);
  load();
}

async function handleDelete(id) {
  error.value = '';
  const res = await fetch(`/api/__TABLE_SQL__/${id}`, { method: 'DELETE' });
  if (!res.ok) {
    error.value = await errorText(res);
    return;
  }
  load();
}
</script>

<template>
  <div class="p-6">
    <h1 class="text-xl font-semibold mb-4">{{ TITLE }}</h1>

    <form @submit.prevent="handleCreate" class="flex gap-3 mb-4 flex-wrap items-end">
      <label v-for="field in FIELDS" :key="field.key" :for="`field-${field.key}`" class="flex flex-col gap-1 text-xs">
        <span>{{ field.label }}{{ field.required ? ' *' : '' }}</span>
        <select
          v-if="field.ref"
          :id="`field-${field.key}`"
          v-model="form[field.key]"
          :required="field.required"
          class="border rounded px-2 py-1 text-sm"
        >
          <option value="">{{ field.required ? 'Choose…' : '— none —' }}</option>
          <option v-for="row in options[field.key] || []" :key="row[field.ref.valueKey]" :value="row[field.ref.valueKey]">
            {{ optionLabel(field, row) }}
          </option>
        </select>
        <input v-else-if="field.type === 'boolean'" :id="`field-${field.key}`" v-model="form[field.key]" type="checkbox" />
        <textarea
          v-else-if="field.type === 'text' || field.type === 'json'"
          :id="`field-${field.key}`"
          v-model="form[field.key]"
          :required="field.required"
          rows="2"
          class="border rounded px-2 py-1 text-sm"
        ></textarea>
        <input
          v-else
          :id="`field-${field.key}`"
          v-model="form[field.key]"
          :type="INPUT_TYPES[field.type] || 'text'"
          :step="field.type === 'integer' ? '1' : 'any'"
          :maxlength="field.maxLength || undefined"
          :required="field.required"
          class="border rounded px-2 py-1 text-sm"
        />
      </label>
      <button type="submit" class="bg-black text-white px-3 py-1 rounded text-sm">Add</button>
    </form>

    <p v-if="error" role="alert" class="text-red-600 text-sm mb-3 whitespace-pre-line">{{ error }}</p>

    <table class="w-full text-sm border-collapse">
      <thead>
        <tr class="border-b">
          <th v-for="field in FIELDS" :key="field.key" class="text-left p-2">{{ field.label }}</th>
          <th class="text-left p-2"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item._id" class="border-b">
          <td v-for="field in FIELDS" :key="field.key" class="p-2">{{ displayValue(field, item[field.key], options) }}</td>
          <td class="p-2">
            <button @click="handleDelete(item._id)" class="text-red-600 text-xs">Delete</button>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- VENGAI:CUSTOM:__SLOT_NAME__:start -->
    <!-- Add custom UI for __SLOT_LABEL__ here — this block is preserved across regenerations. -->
    <!-- VENGAI:CUSTOM:__SLOT_NAME__:end -->
  </div>
</template>
"""


def generate_screen_file_vue(
    table: db_schema.ResolvedTable, schema: db_schema.ResolvedSchema
) -> GeneratedFile:
    component_name = f"{table.class_name}Screen"
    content = (
        _SCREEN_TEMPLATE_VUE.replace("__HEADING__", _js_comment_text(_heading(table)))
        .replace("__TITLE__", js_string_literal(table.name))
        .replace("__FIELDS__", "\n".join(_fields_js(table, schema, "express")))
        .replace("__TABLE_SQL__", table.sql_name)
        .replace("__SLOT_NAME__", f"{table.slug}_screen")
        .replace("__SLOT_LABEL__", table.class_name)
    )
    return GeneratedFile(
        path=f"frontend/src/screens/{component_name}.vue",
        language="javascript",
        content=content,
        description=f"Deterministic CRUD screen for {table.name}",
    )


# ───────────────────────────────────────────────
#  Dispatch — which generator functions a pairing uses
# ───────────────────────────────────────────────
def _fastapi_backend_files(
    schema: db_schema.ResolvedSchema,
) -> tuple[list[GeneratedFile], list[GeneratedFile]]:
    return [generate_model_file_fastapi(t) for t in schema.tables], [
        generate_routes_file_fastapi(schema)
    ]


def _express_backend_files(
    schema: db_schema.ResolvedSchema,
) -> tuple[list[GeneratedFile], list[GeneratedFile]]:
    models = [generate_model_file_express(t, schema) for t in schema.tables]
    return models, [
        generate_routes_file_express(schema),
        generate_checks_file_express(),
    ]


_BACKEND_GENERATORS = {
    "fastapi": _fastapi_backend_files,
    "express": _express_backend_files,
}
_SCREEN_GENERATORS = {
    "react": generate_screen_file_react,
    "vue": generate_screen_file_vue,
}


def _check_generated_names(schema: db_schema.ResolvedSchema) -> None:
    """Refuses a schema whose generated class names would collide inside
    one file — e.g. tables "order" and "order update": the first's request
    model OrderUpdate is the second's model class."""
    refs = _model_refs(schema)
    owners: dict[str, str] = {}
    for t in schema.tables:
        for name in (
            refs[t.sql_name],
            f"{t.class_name}Create",
            f"{t.class_name}Update",
        ):
            if name in owners and owners[name] != t.name:
                raise DeterministicCodegenError(
                    f'Tables "{owners[name]}" and "{t.name}" would both produce a class named {name} in the '
                    "generated code — rename one of them in Architecture."
                )
            owners[name] = t.name


def _readme_notes(backend: str) -> list[str]:
    notes = [
        "This project was generated DETERMINISTICALLY from your Architecture's database "
        "tables — no AI call was made, so it costs nothing and is instant to (re)generate.",
        "Every model/route/screen file has one or more `VENGAI:CUSTOM:<name>:start` / "
        "`:end` marked sections. Edit freely inside those — they are preserved across "
        "future regenerations. Everything outside a marked section is regenerated fresh "
        "every time and should not be hand-edited.",
        "Scope: standard CRUD per table only. For custom, non-CRUD endpoints, use the "
        "VENGAI:CUSTOM:extra_routes section in the routes file.",
        "Database migrations: the schema is owned by versioned migrations in "
        + (
            "backend/migrations/versions/ (Alembic)"
            if backend == "fastapi"
            else "backend/migrations/ (migrate-mongo)"
        )
        + ", and pending ones run automatically every time the backend starts. Each "
        "regeneration that changes a table adds ONE new migration; existing migration files "
        "are never rewritten, so it is safe to edit them by hand.",
    ]
    if backend == "fastapi":
        notes += [
            "Run migrations by hand from backend/: `alembic upgrade head` (undo the newest: "
            "`alembic downgrade -1`; see where the database is: `alembic current`). The database "
            "is SQLite (backend/app.db) unless DATABASE_URL is set — e.g. "
            "`postgresql+asyncpg://user:pass@host/db` after `pip install asyncpg`.",
            "A database created by an OLDER VengaiCode build (tables made at startup, with no "
            "`alembic_version` table) must be told it already matches the first migration, once: "
            "`alembic stamp 0001` from backend/. To start the history over instead, delete "
            "migrations/versions/ and app.db, then regenerate.",
        ]
    else:
        notes += [
            "Run migrations by hand from backend/: `npm run migrate` (see what has run: "
            "`npm run migrate:status`; undo the newest: `npm run migrate:down`). They use "
            "MONGODB_URI, the same database the server connects to. migrate-mongo needs Node 20 or newer.",
            "A database created by an OLDER VengaiCode build: the first migration adopts existing "
            "collections (it updates their validators instead of failing), but a unique index "
            "can't be built over documents that already repeat a value — remove the duplicates, "
            "or start from an empty database.",
        ]
    return notes


# ───────────────────────────────────────────────
#  Orchestration — builds the same codegen_data shape codegen_runner.finalize() does
# ───────────────────────────────────────────────
def build_deterministic_codegen_data(
    project: Project, stack_info: dict, allow_destructive_migration: bool = False
) -> dict:
    """Raises DeterministicCodegenError (schema problems — fix them in
    Architecture), migrations_gen.DestructiveMigrationError (the new
    migration would lose data and allow_destructive_migration is False)
    or migrations_gen.MigrationError (a change no migration can apply)."""
    architecture = (project.architecture_data or {}).get("architecture", {})
    tables = architecture.get("database_tables", [])
    if not tables:
        raise DeterministicCodegenError(
            "Architecture has no database tables to generate from — deterministic mode needs "
            "at least one table (AI-generated screens with no backing table aren't supported "
            "by this mode)."
        )

    frontend_key = stack_info["frontend_framework"]
    backend_key = stack_info["backend_framework"]
    try:
        schema = db_schema.resolve_schema(tables, backend=backend_key, strict=True)
    except db_schema.SchemaValidationError as e:
        raise DeterministicCodegenError(
            "Fix these in Architecture before generating:\n"
            + db_schema.format_issues(e.issues)
        ) from e
    if backend_key == "fastapi":
        # Only routes/api.py puts every table's classes in one namespace;
        # the Express routes name each model <Class>Model and nothing else.
        _check_generated_names(schema)

    model_files, backend_files = _BACKEND_GENERATORS[backend_key](schema)
    routes_file = backend_files[0]
    screen_files = [_SCREEN_GENERATORS[frontend_key](t, schema) for t in schema.tables]
    real_files = (
        model_files + backend_files + screen_files + [generate_crud_helpers_file()]
    )

    old_codegen_data = project.codegen_data or {}
    old_files = (old_codegen_data.get("codegen") or {}).get("files", [])
    # Only a deterministic run's history continues: an AI run's files were
    # never built from these migrations.
    previous_state = (
        old_codegen_data.get("migrations")
        if old_codegen_data.get("generation_mode") == "deterministic"
        else None
    )
    plan = migrations_gen.plan_migrations(
        backend_key,
        schema,
        previous_state,
        old_files,
        allow_destructive=allow_destructive_migration,
    )

    validation_warnings: list[dict] = []
    for f in real_files + plan.files:
        issue = validate_generated_content(f.language, f.content)
        if issue:
            validation_warnings.append({"path": f.path, "reason": issue})

    frontend_adapter = FRONTEND_ADAPTERS[frontend_key]
    backend_adapter = BACKEND_ADAPTERS[backend_key]
    wiring_ctx = WiringCtx(
        project_name=project.name,
        model_files=model_files,
        routes_files=[routes_file],
        screen_files=screen_files,
        endpoints=architecture.get("api_endpoints", []),
        tables=tables,
    )
    wiring_files: list[GeneratedFile] = []
    # migrations=True: requirements/package.json gain the migration tool,
    # and the entry point runs pending migrations instead of create_all.
    wiring_files += backend_adapter.manifest_files(wiring_ctx, migrations=True)
    wiring_files += backend_adapter.entry_point_files(wiring_ctx, migrations=True)
    if frontend_adapter.manifest_files:
        wiring_files += frontend_adapter.manifest_files(wiring_ctx)
    if frontend_adapter.entry_point_files:
        wiring_files += frontend_adapter.entry_point_files(wiring_ctx)

    backend_commands = (
        backend_adapter.setup_commands(project.name)
        if backend_adapter.setup_commands
        else None
    )
    frontend_commands = (
        frontend_adapter.setup_commands(project.name)
        if frontend_adapter.setup_commands
        else None
    )
    wiring_files.append(
        build_readme_setup(
            project.name,
            backend_commands,
            frontend_commands,
            _readme_notes(backend_key),
        )
    )

    frd = (project.requirements_data or {}).get("frd", {}) or {}
    features_text = " ".join(frd.get("key_features", []) or [])
    stories_text = " ".join(frd.get("user_stories", []) or [])
    native_capabilities = detect_native_capabilities(f"{features_text} {stories_text}")

    # Migration files skip the custom-slot merge: a revision that already
    # exists is carried over byte for byte by plan_migrations itself.
    merged_files = (
        merge_preserving_custom_code(old_files, real_files + wiring_files) + plan.files
    )

    generated_files = [f.model_dump() for f in merged_files]
    apply_package_json_name(generated_files, project.name)

    if plan.new_revision is not None:
        migration_note = f" Database migration {plan.new_revision['id']} was written for the schema changes."
    else:
        migration_note = " The database schema is unchanged since the last generation, so no new migration was needed."
    summary = (
        f"Generated {len(real_files)} real implementation files deterministically from "
        f"{len(schema.tables)} database table(s) — no AI call was made.{migration_note}"
    )

    return {
        "codegen": {"summary": summary, "files": generated_files},
        "files_generated": len(generated_files),
        "native_capabilities": native_capabilities,
        "validation_warnings": validation_warnings,
        "stack_used": {
            "codegen_target": stack_info["codegen_target"],
            "source": stack_info["source"],
            "fallback_reason": stack_info.get("fallback_reason"),
        },
        "generation_mode": "deterministic",
        "migrations": plan.state,
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def is_supported_stack(stack_info: dict) -> bool:
    return (
        stack_info.get("frontend_framework"),
        stack_info.get("backend_framework"),
        stack_info.get("api_style"),
    ) in SUPPORTED_STACKS


_DISPLAY_LABELS = {
    "react": "React",
    "vue": "Vue",
    "fastapi": "FastAPI",
    "express": "Express",
}


def supported_stacks_label() -> str:
    """Human-readable list for error messages/UI, e.g. 'React + FastAPI or Vue + Express (REST)'."""
    parts = [
        f"{_DISPLAY_LABELS.get(fe, fe)} + {_DISPLAY_LABELS.get(be, be)}"
        for fe, be, _api in sorted(SUPPORTED_STACKS)
    ]
    return " or ".join(parts) + " (REST)"
