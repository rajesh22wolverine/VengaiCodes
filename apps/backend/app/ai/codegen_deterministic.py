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
#  Scope, on purpose: standard CRUD only. A table's fields become real
#  columns/schema fields and a real REST CRUD surface
#  (list/create/get/update/delete) plus a matching list-and-form
#  screen. Anything beyond CRUD — bespoke business logic, non-obvious
#  relationships, custom endpoints — belongs in the VENGAI:CUSTOM slots
#  this module leaves in every file it writes, which are the one thing
#  regeneration never touches (see extract_custom_slots/
#  reinject_custom_slots below). This is the concrete version of the
#  "named slots AI/human fills in, deterministic generator owns
#  everything else" split.
#
#  Reuses the EXACT same wiring helpers the AI path uses (each
#  pairing's own FRONTEND_ADAPTERS[key]/BACKEND_ADAPTERS[key]
#  .manifest_files/.entry_point_files, build_readme_setup,
#  apply_package_json_name) rather than reimplementing package.json/
#  requirements.txt/main.py/App.jsx/server.js — those are already
#  deterministic templates with zero AI involvement, so there is
#  nothing to gain by duplicating them, and every reason not to
#  (duplication is exactly how the two paths would silently drift).
#
#  Output lands in project.codegen_data in the IDENTICAL shape
#  codegen_runner.finalize() writes (see api/v1/codegen.py's
#  GenerateCodeResponse) plus one additive key, "generation_mode". This
#  is what makes it packaging-transparent: packaging.py,
#  android_packaging.py and linux_packaging.py gate only on
#  codegen_data["user_approved"], codegen_data["validation_warnings"]
#  and stack_matrix.get_project_stack() — none of them, and nothing else
#  downstream, has any opinion on how the files were produced. Wiring
#  this into the Android/Windows/Linux build pipelines therefore
#  required NO changes to any of those three files, for either pairing.
# ═══════════════════════════════════════════════════════════════

import re
from datetime import datetime, timezone

from app.ai.codegen.backend import BACKEND_ADAPTERS
from app.ai.codegen.frontend import FRONTEND_ADAPTERS
from app.ai.codegen.readme import build_readme_setup
from app.ai.codegen.types import WiringCtx
from app.ai.codegen_shared import (
    GeneratedFile,
    _pascal,
    _slug,
    apply_package_json_name,
    detect_native_capabilities,
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
#  Column-type inference
# ───────────────────────────────────────────────
# A table's fields arrive as a flat list of strings (ArchitectureDesign's
# real shape — see architecture.py's DatabaseTable: {name, purpose,
# key_fields: list[str]}, no type info at all). Heuristic, not a
# guarantee — same honesty standard as codegen_shared.py's own
# heuristic validators. A field this misclassifies is still a real,
# working string field a user can widen by hand; it just won't be the
# tightest possible type on the first pass.
#
# One shared classification, two renderings (SQLAlchemy, Mongoose) —
# keeps the heuristic itself from drifting between backends even though
# the two ORMs spell types differently (e.g. Float vs Number).
_CATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"email"), "email"),
    (re.compile(r"url|link|href|website"), "url"),
    (re.compile(r"price|amount|total|cost|rating|score|percent|rate|weight|latitude|longitude"), "float"),
    (re.compile(r"count|quantity|qty|number|num|age|year|stock|inventory|duration"), "int"),
    (re.compile(r"^is_|^has_"), "bool"),
    (re.compile(r"_at$|_date$|^date|^time|timestamp"), "datetime"),
    (re.compile(r"description|bio|notes|content|body|summary|address"), "text"),
]

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
    lowered = field_name.lower()
    for pattern, category in _CATEGORY_RULES:
        if pattern.search(lowered):
            return category
    return "string"


def _infer_sa_type(field_name: str) -> str:
    return _SA_TYPE_BY_CATEGORY[_classify_field(field_name)]


def _infer_mongoose_type(field_name: str) -> str:
    return _MONGOOSE_TYPE_BY_CATEGORY[_classify_field(field_name)]


def _pydantic_type(sa_type: str) -> str:
    if sa_type.startswith("Integer"):
        return "Optional[int]"
    if sa_type.startswith("Float"):
        return "Optional[float]"
    if sa_type.startswith("Boolean"):
        return "Optional[bool]"
    return "Optional[str]"


def _table_slug_plural(name: str) -> str:
    slug = _slug(name)
    return slug if slug.endswith("s") else f"{slug}s"


def _real_fields(table: dict) -> list[str]:
    return [f for f in (table.get("key_fields") or []) if _slug(f) not in ("id", "_id")]


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


# ═══════════════════════════════════════════════
#  FastAPI backend (SQLAlchemy over Postgres/SQLite)
# ═══════════════════════════════════════════════
def generate_model_file_fastapi(table: dict) -> GeneratedFile:
    name = table.get("name", "Item")
    class_name = _pascal(name)
    slug = _slug(name)
    table_slug = _table_slug_plural(name)
    fields = _real_fields(table)

    lines = [
        "from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text",
        "from sqlalchemy.sql import func",
        "",
        "from app.core.database import Base",
        "",
        "",
        f"class {class_name}(Base):",
        f'    """{table.get("purpose") or class_name} — deterministically generated, no AI call."""',
        "",
        f'    __tablename__ = "{table_slug}"',
        "",
        "    id = Column(Integer, primary_key=True, autoincrement=True)",
    ]
    for field in fields:
        lines.append(f"    {_slug(field)} = Column({_infer_sa_type(field)}, nullable=True)")
    lines += [
        "    created_at = Column(DateTime(timezone=True), server_default=func.now())",
        "    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())",
        "",
        f"    # VENGAI:CUSTOM:{slug}_model:start",
        f"    # Add custom columns, relationships, validators or computed properties for {class_name} here.",
        "    # This block is preserved across future regenerations.",
        f"    # VENGAI:CUSTOM:{slug}_model:end",
    ]
    return GeneratedFile(
        path=f"backend/models/{slug}.py",
        language="python",
        content="\n".join(lines) + "\n",
        description=f"Deterministic SQLAlchemy model for {name}",
    )


def _crud_block_fastapi(table: dict) -> list[str]:
    name = table.get("name", "Item")
    class_name = _pascal(name)
    slug = _slug(name)
    table_slug = _table_slug_plural(name)
    fields = _real_fields(table)

    schema_lines = [f"    {_slug(f)}: {_pydantic_type(_infer_sa_type(f))} = None" for f in fields] or ["    pass"]

    return [
        f"class {class_name}In(BaseModel):",
        *schema_lines,
        "",
        "",
        f'@router.get("/{table_slug}")',
        f"async def list_{table_slug}(db: AsyncSession = Depends(get_db)):",
        f"    result = await db.execute(select({class_name}))",
        "    return result.scalars().all()",
        "",
        "",
        f'@router.post("/{table_slug}", status_code=201)',
        f"async def create_{slug}(payload: {class_name}In, db: AsyncSession = Depends(get_db)):",
        f"    item = {class_name}(**payload.dict(exclude_unset=True))",
        "    db.add(item)",
        "    await db.commit()",
        "    await db.refresh(item)",
        "    return item",
        "",
        "",
        f'@router.get("/{table_slug}/{{item_id}}")',
        f"async def get_{slug}(item_id: int, db: AsyncSession = Depends(get_db)):",
        f"    result = await db.execute(select({class_name}).where({class_name}.id == item_id))",
        "    item = result.scalar_one_or_none()",
        "    if item is None:",
        f'        raise HTTPException(status_code=404, detail="{class_name} not found")',
        "    return item",
        "",
        "",
        f'@router.put("/{table_slug}/{{item_id}}")',
        f"async def update_{slug}(item_id: int, payload: {class_name}In, db: AsyncSession = Depends(get_db)):",
        f"    result = await db.execute(select({class_name}).where({class_name}.id == item_id))",
        "    item = result.scalar_one_or_none()",
        "    if item is None:",
        f'        raise HTTPException(status_code=404, detail="{class_name} not found")',
        "    for key, value in payload.dict(exclude_unset=True).items():",
        "        setattr(item, key, value)",
        "    await db.commit()",
        "    await db.refresh(item)",
        "    return item",
        "",
        "",
        f'@router.delete("/{table_slug}/{{item_id}}", status_code=204)',
        f"async def delete_{slug}(item_id: int, db: AsyncSession = Depends(get_db)):",
        f"    result = await db.execute(select({class_name}).where({class_name}.id == item_id))",
        "    item = result.scalar_one_or_none()",
        "    if item is None:",
        f'        raise HTTPException(status_code=404, detail="{class_name} not found")',
        "    await db.delete(item)",
        "    await db.commit()",
        "    return None",
        "",
    ]


def generate_routes_file_fastapi(tables: list[dict]) -> GeneratedFile:
    lines = [
        "from typing import Optional",
        "",
        "from fastapi import APIRouter, Depends, HTTPException",
        "from pydantic import BaseModel",
        "from sqlalchemy import select",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "",
        "from app.core.database import get_db",
    ]
    for table in tables:
        name = table.get("name", "Item")
        lines.append(f"from models.{_slug(name)} import {_pascal(name)}")
    lines += ["", "router = APIRouter()", "", ""]

    for table in tables:
        lines += _crud_block_fastapi(table)
        lines.append("")

    lines += [
        "# VENGAI:CUSTOM:extra_routes:start",
        "# Add custom, non-CRUD endpoints here — this block is preserved across regenerations.",
        "# Example: @router.get(\"/reports/summary\") ...",
        "# VENGAI:CUSTOM:extra_routes:end",
    ]
    return GeneratedFile(
        path="backend/routes/api.py",
        language="python",
        content="\n".join(lines) + "\n",
        description="Deterministic CRUD routes for every database table",
    )


# ═══════════════════════════════════════════════
#  React frontend
# ═══════════════════════════════════════════════
def _field_input_line_react(field: str) -> str:
    slug = _slug(field)
    return (
        '          <input className="border rounded px-2 py-1 text-sm" placeholder="' + field + '" '
        "value={form." + slug + " || ''} "
        "onChange={(e) => setForm({ ...form, " + slug + ": e.target.value })} />"
    )


def _header_cell_line(field: str) -> str:
    """Shared by React and Vue — both render the same plain <th> markup."""
    return '              <th className="text-left p-2">' + field + "</th>"


def _row_cell_line_react(field: str) -> str:
    return '                <td className="p-2">{item.' + _slug(field) + "}</td>"


_SCREEN_TEMPLATE_REACT = """import { useEffect, useState } from 'react';

export default function __COMPONENT__() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({});

  const load = () => {
    fetch('/api/__TABLE_SLUG__')
      .then((res) => res.json())
      .then(setItems)
      .catch(() => setItems([]));
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    await fetch('/api/__TABLE_SLUG__', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    });
    setForm({});
    load();
  };

  const handleDelete = async (id) => {
    await fetch(`/api/__TABLE_SLUG__/${id}`, { method: 'DELETE' });
    load();
  };

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold mb-4">__DISPLAY_NAME__</h1>

      <form onSubmit={handleCreate} className="flex gap-2 mb-4 flex-wrap">
__FIELD_INPUTS__
        <button type="submit" className="bg-black text-white px-3 py-1 rounded text-sm">Add</button>
      </form>

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b">
__HEADER_CELLS__
            <th className="text-left p-2"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className="border-b">
__ROW_CELLS__
              <td className="p-2">
                <button onClick={() => handleDelete(item.id)} className="text-red-600 text-xs">Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* VENGAI:CUSTOM:__SLOT_NAME__:start */}
      {/* Add custom UI for __DISPLAY_NAME__ here — this block is preserved across regenerations. */}
      {/* VENGAI:CUSTOM:__SLOT_NAME__:end */}
    </div>
  );
}
"""


def generate_screen_file_react(table: dict) -> GeneratedFile:
    name = table.get("name", "Item")
    class_name = _pascal(name)
    slug = _slug(name)
    table_slug = _table_slug_plural(name)
    fields = _real_fields(table) or ["name"]
    component_name = f"{class_name}Screen"

    content = (
        _SCREEN_TEMPLATE_REACT
        .replace("__COMPONENT__", component_name)
        .replace("__TABLE_SLUG__", table_slug)
        .replace("__DISPLAY_NAME__", name)
        .replace("__SLOT_NAME__", f"{slug}_screen")
        .replace("__FIELD_INPUTS__", "\n".join(_field_input_line_react(f) for f in fields))
        .replace("__HEADER_CELLS__", "\n".join(_header_cell_line(f) for f in fields))
        .replace("__ROW_CELLS__", "\n".join(_row_cell_line_react(f) for f in fields))
    )
    return GeneratedFile(
        path=f"frontend/src/screens/{component_name}.jsx",
        language="javascript",
        content=content,
        description=f"Deterministic CRUD screen for {name}",
    )


# ═══════════════════════════════════════════════
#  Express backend (Mongoose over MongoDB)
# ═══════════════════════════════════════════════
def generate_model_file_express(table: dict) -> GeneratedFile:
    name = table.get("name", "Item")
    class_name = _pascal(name)
    slug = _slug(name)
    fields = _real_fields(table)

    field_lines = [
        f"  {_slug(f)}: {{ type: {_infer_mongoose_type(f)}, required: false }}," for f in fields
    ]
    schema_body = "\n".join(field_lines) if field_lines else "  // no fields beyond the standard _id/timestamps"

    content = (
        "const mongoose = require('mongoose');\n\n"
        f"// {table.get('purpose') or class_name} — deterministically generated, no AI call.\n"
        f"const {class_name}Schema = new mongoose.Schema({{\n"
        f"{schema_body}\n"
        "}, { timestamps: true });\n\n"
        f"// VENGAI:CUSTOM:{slug}_model:start\n"
        f"// Add custom virtuals, methods, hooks or indexes for {class_name}Schema here\n"
        f"// (e.g. {class_name}Schema.methods.someMethod = function () {{ ... }};).\n"
        "// This block is preserved across future regenerations.\n"
        f"// VENGAI:CUSTOM:{slug}_model:end\n\n"
        f"module.exports = mongoose.model('{class_name}', {class_name}Schema);\n"
    )
    return GeneratedFile(
        path=f"backend/models/{slug}.js",
        language="javascript",
        content=content,
        description=f"Deterministic Mongoose model for {name}",
    )


def _crud_block_express(table: dict) -> list[str]:
    name = table.get("name", "Item")
    class_name = _pascal(name)
    table_slug = _table_slug_plural(name)

    return [
        f"// {name}",
        f"router.get('/{table_slug}', async (req, res) => {{",
        f"  const items = await {class_name}.find();",
        "  res.json(items);",
        "});",
        "",
        f"router.post('/{table_slug}', async (req, res) => {{",
        f"  const item = await {class_name}.create(req.body);",
        "  res.status(201).json(item);",
        "});",
        "",
        f"router.get('/{table_slug}/:id', async (req, res) => {{",
        f"  const item = await {class_name}.findById(req.params.id);",
        f'  if (!item) return res.status(404).json({{ error: "{class_name} not found" }});',
        "  res.json(item);",
        "});",
        "",
        f"router.put('/{table_slug}/:id', async (req, res) => {{",
        f"  const item = await {class_name}.findByIdAndUpdate(req.params.id, req.body, {{ new: true }});",
        f'  if (!item) return res.status(404).json({{ error: "{class_name} not found" }});',
        "  res.json(item);",
        "});",
        "",
        f"router.delete('/{table_slug}/:id', async (req, res) => {{",
        f"  const item = await {class_name}.findByIdAndDelete(req.params.id);",
        f'  if (!item) return res.status(404).json({{ error: "{class_name} not found" }});',
        "  res.status(204).end();",
        "});",
        "",
    ]


def generate_routes_file_express(tables: list[dict]) -> GeneratedFile:
    lines = [
        "const express = require('express');",
        "const router = express.Router();",
        "",
    ]
    for table in tables:
        name = table.get("name", "Item")
        lines.append(f"const {_pascal(name)} = require('../models/{_slug(name)}');")
    lines.append("")

    for table in tables:
        lines += _crud_block_express(table)

    lines += [
        "// VENGAI:CUSTOM:extra_routes:start",
        "// Add custom, non-CRUD endpoints here — this block is preserved across regenerations.",
        "// Example: router.get('/reports/summary', async (req, res) => { ... });",
        "// VENGAI:CUSTOM:extra_routes:end",
        "",
        "module.exports = router;",
    ]
    return GeneratedFile(
        path="backend/routes/api.js",
        language="javascript",
        content="\n".join(lines) + "\n",
        description="Deterministic CRUD routes for every database table",
    )


# ═══════════════════════════════════════════════
#  Vue frontend
# ═══════════════════════════════════════════════
def _field_input_line_vue(field: str) -> str:
    slug = _slug(field)
    return (
        '        <input class="border rounded px-2 py-1 text-sm" placeholder="' + field + '" '
        'v-model="form.' + slug + '" />'
    )


def _row_cell_line_vue(field: str) -> str:
    return '            <td class="p-2">{{ item.' + _slug(field) + " }}</td>"


# Mongoose documents key on _id, not id — a real difference from the
# SQLAlchemy side this screen has to render/act on correctly, not paper
# over with the same "id" everywhere.
_SCREEN_TEMPLATE_VUE = """<script setup>
import { ref, onMounted } from 'vue';

const items = ref([]);
const form = ref({});

const load = () => {
  fetch('/api/__TABLE_SLUG__')
    .then((res) => res.json())
    .then((data) => { items.value = data; })
    .catch(() => { items.value = []; });
};

onMounted(load);

const handleCreate = async () => {
  await fetch('/api/__TABLE_SLUG__', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(form.value),
  });
  form.value = {};
  load();
};

const handleDelete = async (id) => {
  await fetch(`/api/__TABLE_SLUG__/${id}`, { method: 'DELETE' });
  load();
};
</script>

<template>
  <div class="p-6">
    <h1 class="text-xl font-semibold mb-4">__DISPLAY_NAME__</h1>

    <form @submit.prevent="handleCreate" class="flex gap-2 mb-4 flex-wrap">
__FIELD_INPUTS__
      <button type="submit" class="bg-black text-white px-3 py-1 rounded text-sm">Add</button>
    </form>

    <table class="w-full text-sm border-collapse">
      <thead>
        <tr class="border-b">
__HEADER_CELLS__
          <th class="text-left p-2"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item._id" class="border-b">
__ROW_CELLS__
          <td class="p-2">
            <button @click="handleDelete(item._id)" class="text-red-600 text-xs">Delete</button>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- VENGAI:CUSTOM:__SLOT_NAME__:start -->
    <!-- Add custom UI for __DISPLAY_NAME__ here — this block is preserved across regenerations. -->
    <!-- VENGAI:CUSTOM:__SLOT_NAME__:end -->
  </div>
</template>
"""


def generate_screen_file_vue(table: dict) -> GeneratedFile:
    name = table.get("name", "Item")
    class_name = _pascal(name)
    slug = _slug(name)
    table_slug = _table_slug_plural(name)
    fields = _real_fields(table) or ["name"]
    component_name = f"{class_name}Screen"

    content = (
        _SCREEN_TEMPLATE_VUE
        .replace("__TABLE_SLUG__", table_slug)
        .replace("__DISPLAY_NAME__", name)
        .replace("__SLOT_NAME__", f"{slug}_screen")
        .replace("__FIELD_INPUTS__", "\n".join(_field_input_line_vue(f) for f in fields))
        .replace("__HEADER_CELLS__", "\n".join(_header_cell_line(f) for f in fields))
        .replace("__ROW_CELLS__", "\n".join(_row_cell_line_vue(f) for f in fields))
    )
    return GeneratedFile(
        path=f"frontend/src/screens/{component_name}.vue",
        language="javascript",
        content=content,
        description=f"Deterministic CRUD screen for {name}",
    )


# ───────────────────────────────────────────────
#  Dispatch — which generator functions a pairing uses
# ───────────────────────────────────────────────
_MODEL_GENERATORS = {
    "fastapi": generate_model_file_fastapi,
    "express": generate_model_file_express,
}
_ROUTES_GENERATORS = {
    "fastapi": generate_routes_file_fastapi,
    "express": generate_routes_file_express,
}
_SCREEN_GENERATORS = {
    "react": generate_screen_file_react,
    "vue": generate_screen_file_vue,
}


# ───────────────────────────────────────────────
#  Orchestration — builds the same codegen_data shape codegen_runner.finalize() does
# ───────────────────────────────────────────────
def build_deterministic_codegen_data(project: Project, stack_info: dict) -> dict:
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
    model_gen = _MODEL_GENERATORS[backend_key]
    routes_gen = _ROUTES_GENERATORS[backend_key]
    screen_gen = _SCREEN_GENERATORS[frontend_key]

    model_files = [model_gen(t) for t in tables]
    routes_file = routes_gen(tables)
    screen_files = [screen_gen(t) for t in tables]
    real_files = model_files + [routes_file] + screen_files

    validation_warnings: list[dict] = []
    for f in real_files:
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
    for adapter in (backend_adapter, frontend_adapter):
        if adapter.manifest_files:
            wiring_files += adapter.manifest_files(wiring_ctx)
        if adapter.entry_point_files:
            wiring_files += adapter.entry_point_files(wiring_ctx)

    backend_commands = backend_adapter.setup_commands(project.name) if backend_adapter.setup_commands else None
    frontend_commands = frontend_adapter.setup_commands(project.name) if frontend_adapter.setup_commands else None
    wiring_files.append(
        build_readme_setup(
            project.name,
            backend_commands,
            frontend_commands,
            [
                "This project was generated DETERMINISTICALLY from your Architecture's database "
                "tables — no AI call was made, so it costs nothing and is instant to (re)generate.",
                "Every model/route/screen file has one or more `VENGAI:CUSTOM:<name>:start` / "
                "`:end` marked sections. Edit freely inside those — they are preserved across "
                "future regenerations. Everything outside a marked section is regenerated fresh "
                "every time and should not be hand-edited.",
                "Scope: standard CRUD per table only. For custom, non-CRUD endpoints, use the "
                "VENGAI:CUSTOM:extra_routes section in the routes file.",
            ],
        )
    )

    frd = (project.requirements_data or {}).get("frd", {}) or {}
    features_text = " ".join(frd.get("key_features", []) or [])
    stories_text = " ".join(frd.get("user_stories", []) or [])
    native_capabilities = detect_native_capabilities(f"{features_text} {stories_text}")

    old_codegen_data = project.codegen_data or {}
    old_files = (old_codegen_data.get("codegen") or {}).get("files", [])
    merged_files = merge_preserving_custom_code(old_files, real_files + wiring_files)

    generated_files = [f.model_dump() for f in merged_files]
    apply_package_json_name(generated_files, project.name)

    summary = (
        f"Generated {len(real_files)} real implementation files deterministically from "
        f"{len(tables)} database table(s) — no AI call was made."
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
    "react": "React", "vue": "Vue", "fastapi": "FastAPI", "express": "Express",
}


def supported_stacks_label() -> str:
    """Human-readable list for error messages/UI, e.g. 'React + FastAPI or Vue + Express (REST)'."""
    parts = [
        f"{_DISPLAY_LABELS.get(fe, fe)} + {_DISPLAY_LABELS.get(be, be)}"
        for fe, be, _api in sorted(SUPPORTED_STACKS)
    ]
    return " or ".join(parts) + " (REST)"
