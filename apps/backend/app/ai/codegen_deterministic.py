# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Deterministic (Schema-Driven) Code Generation
#  ai/codegen_deterministic.py — An AI-less alternative to
#  codegen_runner.py for the React + FastAPI (REST) pairing: instead of
#  one AI call per model/routes/screen file, real CRUD models, routes
#  and screens are built directly from the approved Architecture's
#  database_tables via string templates. Zero AI calls, zero cost,
#  instant, and can never produce invalid syntax the way a freeform LLM
#  response can.
#
#  Scope, on purpose: standard CRUD only. A table's fields become real
#  columns and a real REST CRUD surface (list/create/get/update/delete)
#  plus a matching list-and-form React screen. Anything beyond CRUD —
#  bespoke business logic, non-obvious relationships, custom endpoints —
#  belongs in the VENGAI:CUSTOM slots this module leaves in every file
#  it writes, which are the one thing regeneration never touches (see
#  extract_custom_slots/reinject_custom_slots below). This is the
#  concrete version of the "named slots AI/human fills in, deterministic
#  generator owns everything else" split.
#
#  Reuses the EXACT same wiring helpers the AI path uses
#  (FRONTEND_ADAPTERS["react"].manifest_files/entry_point_files,
#  BACKEND_ADAPTERS["fastapi"].manifest_files/entry_point_files,
#  build_readme_setup, apply_package_json_name) rather than
#  reimplementing package.json/requirements.txt/main.py/App.jsx — those
#  are already deterministic templates with zero AI involvement, so
#  there is nothing to gain by duplicating them, and every reason not to
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
#  required NO changes to any of those three files.
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

# The one pairing this module knows how to generate. Deliberately narrow
# rather than attempting all 8x13 adapter combinations at once — see the
# scoping discussion this feature was built from. Extending to a second
# pairing means adding a second (frontend, backend) branch below, not
# rewriting this module.
SUPPORTED_STACK = ("react", "fastapi", "rest")


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
# working String column a user can widen by hand; it just won't be the
# tightest possible type on the first pass.
_TYPE_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"email"), "String(255)"),
    (re.compile(r"url|link|href|website"), "String(500)"),
    (re.compile(r"price|amount|total|cost|rating|score|percent|rate|weight|latitude|longitude"), "Float"),
    (re.compile(r"count|quantity|qty|number|num|age|year|stock|inventory|duration"), "Integer"),
    (re.compile(r"^is_|^has_"), "Boolean"),
    (re.compile(r"_at$|_date$|^date|^time|timestamp"), "DateTime(timezone=True)"),
    (re.compile(r"description|bio|notes|content|body|summary|address"), "Text"),
]


def _infer_sa_type(field_name: str) -> str:
    lowered = field_name.lower()
    for pattern, sa_type in _TYPE_RULES:
        if pattern.search(lowered):
            return sa_type
    return "String(255)"


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
    return [f for f in (table.get("key_fields") or []) if _slug(f) != "id"]


# ───────────────────────────────────────────────
#  Custom-code preservation ("named slots")
# ───────────────────────────────────────────────
# Line-based, not a single clever regex, deliberately — a file mixes
# comment styles (# in Python, // and {/* */} in JSX) and a line-based
# scan only needs to find the marker TEXT, never parse the comment
# syntax around it, so it works identically regardless of language.
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
#  Model file (backend/models/{slug}.py)
# ───────────────────────────────────────────────
def generate_model_file(table: dict) -> GeneratedFile:
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


# ───────────────────────────────────────────────
#  Routes file (backend/routes/api.py — one combined file, all tables)
# ───────────────────────────────────────────────
def _crud_block(table: dict) -> list[str]:
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


def generate_routes_file(tables: list[dict]) -> GeneratedFile:
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
        lines += _crud_block(table)
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


# ───────────────────────────────────────────────
#  Screen file (frontend/src/screens/{Name}Screen.jsx)
# ───────────────────────────────────────────────
def _field_input_line(field: str) -> str:
    slug = _slug(field)
    return (
        '          <input className="border rounded px-2 py-1 text-sm" placeholder="' + field + '" '
        "value={form." + slug + " || ''} "
        "onChange={(e) => setForm({ ...form, " + slug + ": e.target.value })} />"
    )


def _header_cell_line(field: str) -> str:
    return '              <th className="text-left p-2">' + field + "</th>"


def _row_cell_line(field: str) -> str:
    return '                <td className="p-2">{item.' + _slug(field) + "}</td>"


_SCREEN_TEMPLATE = """import { useEffect, useState } from 'react';

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


def generate_screen_file(table: dict) -> GeneratedFile:
    name = table.get("name", "Item")
    class_name = _pascal(name)
    slug = _slug(name)
    table_slug = _table_slug_plural(name)
    fields = _real_fields(table) or ["name"]
    component_name = f"{class_name}Screen"

    content = (
        _SCREEN_TEMPLATE
        .replace("__COMPONENT__", component_name)
        .replace("__TABLE_SLUG__", table_slug)
        .replace("__DISPLAY_NAME__", name)
        .replace("__SLOT_NAME__", f"{slug}_screen")
        .replace("__FIELD_INPUTS__", "\n".join(_field_input_line(f) for f in fields))
        .replace("__HEADER_CELLS__", "\n".join(_header_cell_line(f) for f in fields))
        .replace("__ROW_CELLS__", "\n".join(_row_cell_line(f) for f in fields))
    )
    return GeneratedFile(
        path=f"frontend/src/screens/{component_name}.jsx",
        language="javascript",
        content=content,
        description=f"Deterministic CRUD screen for {name}",
    )


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

    model_files = [generate_model_file(t) for t in tables]
    routes_file = generate_routes_file(tables)
    screen_files = [generate_screen_file(t) for t in tables]
    real_files = model_files + [routes_file] + screen_files

    validation_warnings: list[dict] = []
    for f in real_files:
        issue = validate_generated_content(f.language, f.content)
        if issue:
            validation_warnings.append({"path": f.path, "reason": issue})

    frontend_adapter = FRONTEND_ADAPTERS[stack_info["frontend_framework"]]
    backend_adapter = BACKEND_ADAPTERS[stack_info["backend_framework"]]
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
                "VENGAI:CUSTOM:extra_routes section in backend/routes/api.py.",
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
        stack_info.get("frontend_framework") == SUPPORTED_STACK[0]
        and stack_info.get("backend_framework") == SUPPORTED_STACK[1]
        and stack_info.get("api_style") == SUPPORTED_STACK[2]
    )
