# ═══════════════════════════════════════════════════════════════
#  VengaiCode — O3DE (Open 3D Engine) Codegen (game frontend)
#  ai/codegen/o3de.py — Like Godot (app/ai/codegen/godot.py), O3DE pairs
#  with stack_matrix.py's "none" backend sentinel, so it never fit the
#  FrontendAdapter registry shape and is dispatched from its own branch
#  in codegen.py.
#
#  2026-07-25 REWRITE: the previous version of this module was broken —
#  generate_screen() ignored the "o3de_script" language it was called
#  with and hardcoded a JavaScript/.jsx prompt+output path (a leftover
#  from a web-framework adapter that was never actually adapted for
#  O3DE), and the wiring step asked the AI to freeform-invent "O3DE
#  project/workspace config files" disconnected from any real O3DE
#  format. Neither produced anything a real O3DE Editor could open.
#
#  This rewrite emits REAL O3DE content, verified against O3DE's own
#  open-source repo (github.com/o3de/o3de) rather than guessed:
#    - project.json: real field set, cross-checked against
#      AutomatedTesting/project.json in the o3de/o3de repo. (The OLD
#      scaffold's "ProjectName.project"/"ProjectName.workspace" XML
#      files do not exist in real O3DE at all — there is no .project/
#      .workspace file format; this was fabricated.)
#    - Levels/Main/Main.prefab: real prefab JSON shape (ContainerEntity
#      + Entities, each entity a Components dict keyed by
#      "Component_[id]"), cross-checked against a real, working
#      reference (AutomatedTesting/Levels/DefaultLevel/DefaultLevel.prefab
#      in the o3de/o3de repo) for exact component $type strings —
#      including which components carry a "{UUID} ClassName" $type
#      (TransformComponent, ScriptEditorComponent — anything with a
#      distinct runtime/editor pair) vs. a bare class name (the
#      Editor-only bookkeeping components: EditorLockComponent,
#      EditorVisibilityComponent, etc.). ScriptEditorComponent's real
#      UUID ({B5FC8679-FA2A-4C7C-AC42-DCC279EA613A}) and its real
#      serialized field name ("ScriptAsset") were confirmed from the
#      engine's own source (AzToolsFramework/ToolsComponents/
#      ScriptEditorComponent.cpp's Reflect()), not invented.
#    - Scripts/*.lua: real Lua component-script skeleton (Properties
#      table, OnActivate/OnDeactivate, `return Table` at the end,
#      self.entityId, EBus `.Connect(self, self.entityId)` /
#      `TickBus.Connect(self)` patterns, Debug.Log) cross-checked
#      against O3DE's own docs AND a real example script shipped in
#      AutomatedTesting/test1.lua.
#
#  HONEST REMAINING GAPS (documented instead of glossed over):
#    1. A hand-authored ScriptAsset reference can supply the correct
#       relative path ("assetHint") but NOT a correct "assetId.guid" —
#       that GUID is assigned by O3DE's own Asset Processor the first
#       time it processes a source file, and can't be computed outside
#       the real toolchain. Every generated Script component ships with
#       the canonical null GUID ({00000000-0000-0000-0000-000000000000})
#       as an honest "unresolved — needs one manual re-link" marker
#       rather than a fabricated-but-wrong value. README_O3DE_SETUP.md
#       (see manifest_files()) tells the user exactly what to do about
#       it (open the entity in the Editor, browse to the script file
#       once — O3DE then fixes and re-saves the reference itself).
#    2. O3DE's core Lua bindings have no built-in HTTP/REST client (no
#       "HttpRequestor"-style Gem ships in the base engine, confirmed by
#       checking the real Gems/ directory listing) — unlike Godot's
#       HTTPRequest node. Generated scripts implement local game
#       state/logic only; backend connectivity is called out as a
#       documented gap in-prompt rather than hallucinated.
#    3. O3DE UI (menus, HUD) is authored in the separate LyShine UI
#       Editor as a .uicanvas asset, not buildable from a Lua script the
#       way Godot's Control nodes are — generated scripts implement the
#       underlying state/behavior a screen represents; wiring an actual
#       visual UI Canvas to call into it is a manual Editor step.
#    4. No O3DE engine/Editor is available in this dev environment to
#       open-and-verify any of this live. Treat the prefab's exact
#       required-component set as the least-verified piece — it matches
#       one real reference level, but O3DE may tolerate a smaller set.
# ═══════════════════════════════════════════════════════════════

import json
import random
import uuid

from app.ai.codegen.types import FileResult, ScreenCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, _slug, generate_text_validated

# Real UUIDs confirmed from O3DE engine source (see module header) —
# these identify the COMPONENT CLASS, not any particular instance.
_TRANSFORM_COMPONENT_UUID = "{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0}"
_SCRIPT_EDITOR_COMPONENT_UUID = "{B5FC8679-FA2A-4C7C-AC42-DCC279EA613A}"

# Canonical "unresolved" asset reference — see gap #1 in the header.
_NULL_ASSET_ID = {"guid": "{00000000-0000-0000-0000-000000000000}", "subId": 0}


def _new_numeric_id(rng: random.Random) -> int:
    """A fresh unique-within-this-file numeric id, shaped like the ones
    O3DE's own Editor assigns (unsigned, up to ~19-20 digits) — real
    files don't reuse a scheme we need to replicate, only uniqueness
    within the file matters."""
    return rng.getrandbits(63)


async def generate_screen(ctx: ScreenCtx) -> FileResult:
    screen_name = ctx.screen.get("name", "Screen")
    script_table_name = f"{_pascal(screen_name)}Behavior"
    file_slug = _slug(screen_name)

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real O3DE (Open 3D Engine) Lua component script implementing the game logic for the "{screen_name}" feature of this game.

Game: {ctx.project_name}
{ctx.requirements_text}
Feature purpose: {ctx.screen.get('purpose', '')}

Requirements — follow O3DE's REAL Lua component script structure exactly, nothing invented:
- Structure:
  local {script_table_name} =
  {{
      Properties =
      {{
          -- real, meaningful tunables for this feature (or leave empty if none apply)
      }}
  }}

  function {script_table_name}:OnActivate()
      -- real setup logic
  end

  function {script_table_name}:OnDeactivate()
      -- real teardown logic (disconnect any bus handlers created in OnActivate)
  end

  return {script_table_name}
- For per-frame updates: `self.tickBusHandler = TickBus.Connect(self)` in OnActivate, implement
  `function {script_table_name}:OnTick(deltaTime, timePoint) ... end`, and
  `self.tickBusHandler:Disconnect()` + `self.tickBusHandler = nil` in OnDeactivate.
- For entity-scoped EBus notifications: `SomeBus.Connect(self, self.entityId)` (note the extra
  `self.entityId` argument, unlike the global TickBus), disconnected the same way.
- Use `Debug.Log("...")` for any diagnostic/state-change output.
- Implement REAL, working state and logic for this feature and the requirements text above using
  plain Lua tables/variables — no placeholders, no TODOs, no stub functions.
- Do NOT call any HTTP/REST/network API — O3DE's core Lua bindings have no built-in HTTP client.
  If this feature would normally talk to a backend, implement the local game-state/logic side only
  and add exactly one comment noting that real backend connectivity needs a custom Gem (out of
  scope here) — do not invent an HTTP function that doesn't exist in O3DE.
- Do NOT try to construct a visual UI/menu from this script — O3DE UI Canvases are authored in the
  separate UI Editor, not from Lua. Implement the underlying state/behavior this feature represents;
  assume a human wires an actual UI Canvas to call into this script's Properties/functions later.
- This file MUST be self-contained: do not `require` any other generated script file.

Return ONLY the raw Lua code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "lua", GROQ_FILE_MAX_TOKENS, user=ctx.user, db=ctx.db)
    return GeneratedFile(
        path=f"frontend/Scripts/{file_slug}.lua",
        language="lua",
        content=content,
        description=f"O3DE Lua behavior script implementing {screen_name}",
    ), issue


def _new_component(rng: random.Random, components: dict, type_str: str, **fields) -> None:
    """Adds one component to `components`, generating exactly ONE id shared
    by the `Component_[id]` key and the nested "Id" field — real O3DE
    prefabs always match the two (confirmed against DefaultLevel.prefab).
    A previous version of this module called _new_numeric_id() separately
    for the key and the "Id" field, so they'd almost never match — a real
    bug caught by ruff's F601 check (repeated dict-key-literal pattern)
    during a pre-commit/CI wiring pass, not by manual review."""
    component_id = _new_numeric_id(rng)
    components[f"Component_[{component_id}]"] = {"$type": type_str, "Id": component_id, **fields}


def _entity_json(rng: random.Random, name: str, script_asset_hint: str | None) -> tuple[str, dict]:
    """One O3DE prefab entity: real Transform + (optionally) a Lua Script
    component. Component set and $type shapes (which get a "{UUID} Name"
    type string vs. a bare class name) mirror DefaultLevel.prefab — see
    module header."""
    entity_id = _new_numeric_id(rng)
    components: dict = {}
    _new_component(rng, components, "EditorLockComponent")
    _new_component(rng, components, "EditorVisibilityComponent")
    _new_component(rng, components, "EditorInspectorComponent")
    _new_component(rng, components, f"{_TRANSFORM_COMPONENT_UUID} TransformComponent", **{"Parent Entity": ""})

    if script_asset_hint:
        _new_component(
            rng,
            components,
            f"{_SCRIPT_EDITOR_COMPONENT_UUID} ScriptEditorComponent",
            # HONEST GAP #1 (see module header): assetId is the canonical
            # null/unresolved GUID — a real one can only be assigned by
            # O3DE's own Asset Processor, not computed here. assetHint is
            # the real relative path, so the Editor's "browse to file"
            # re-link is a one-click fix, not a guess.
            ScriptAsset={
                "assetId": dict(_NULL_ASSET_ID),
                "assetHint": script_asset_hint,
            },
        )

    entity_key = f"Entity_[{entity_id}]"
    return entity_key, {
        "Id": entity_key,
        "Name": name,
        "Components": components,
    }


def _level_prefab(project_name: str, screen_files: list[GeneratedFile]) -> dict:
    """Deterministic (no AI call) real O3DE level prefab wiring one entity
    per generated Lua script — mirrors godot.py's manifest_files() being
    deterministic while generate_screen() is the only AI-driven part."""
    rng = random.Random()
    container_id = _new_numeric_id(rng)
    container_key = f"Entity_[{container_id}]"

    entities: dict[str, dict] = {}
    child_order: list[str] = []
    for f in screen_files or []:
        # frontend/Scripts/<slug>.lua -> <slug>
        slug = f.path.rsplit("/", 1)[-1].removesuffix(".lua")
        entity_key, entity = _entity_json(rng, name=_pascal(slug), script_asset_hint=f"Scripts/{slug}.lua")
        entities[entity_key] = entity
        child_order.append(entity_key)

    if not entities:
        # Every generated project has at least one screen upstream, but
        # keep this function safe to call standalone (e.g. from tests)
        # without producing an empty, order-less level.
        entity_key, entity = _entity_json(rng, name="Main", script_asset_hint=None)
        entities[entity_key] = entity
        child_order.append(entity_key)

    container_components: dict = {}
    _new_component(rng, container_components, "EditorInspectorComponent")
    _new_component(rng, container_components, "EditorEntitySortComponent", **{"Child Entity Order": child_order})
    _new_component(
        rng, container_components, f"{_TRANSFORM_COMPONENT_UUID} TransformComponent", **{"Parent Entity": ""}
    )
    _new_component(rng, container_components, "EditorPrefabComponent")
    _new_component(rng, container_components, "EditorLockComponent")
    _new_component(rng, container_components, "EditorVisibilityComponent")

    return {
        "ContainerEntity": {
            "Id": container_key,
            "Name": "Level",
            "Components": container_components,
        },
        "Entities": entities,
    }


def _project_json(project_name: str) -> dict:
    """Real O3DE project.json field set — cross-checked against
    AutomatedTesting/project.json in the o3de/o3de repo (see module
    header). gem_names is deliberately empty: which Gems a project needs
    is a real per-project decision normally made in O3DE's Project
    Manager GUI, not something safe to guess here."""
    safe_name = _pascal(project_name) or "GeneratedGame"
    return {
        "project_name": safe_name,
        "product_name": safe_name,
        "version": "1.0.0",
        "executable_name": f"{safe_name}Launcher",
        "modules": [],
        "project_id": "{" + str(uuid.uuid4()).upper() + "}",
        "display_name": project_name or safe_name,
        "icon_path": "preview.png",
        "external_subdirectories": [],
        "gem_names": [],
    }


_README_O3DE_SETUP = """# {project_name} — O3DE Project Setup

This is a real Open 3D Engine (O3DE) project scaffold: `project.json`,
one level (`Levels/Main/Main.prefab`) with one entity per generated
feature, and a real Lua behavior script per entity under `Scripts/`.

## What's automated vs. manual

VengaiCode's codegen wrote real, structurally-correct O3DE files, but
**cannot compile or open them** — that needs the real O3DE Editor, which
is tens of GB and isn't something that runs in this pipeline. What's
NOT automated (and is a normal part of using any hand-authored O3DE
project, not a bug in this generator):

1. **One-time script re-link.** Each entity's "Lua Script" component
   points at the right file (e.g. `Scripts/inventory.lua`) but can't
   carry a real Asset Processor-assigned ID ahead of time — open
   `Levels/Main/Main.prefab` in the Editor, select each entity, and
   use the Script component's "Script Asset" field to browse to its
   `.lua` file once. The Editor resolves and re-saves the reference
   itself from then on.
2. **UI.** O3DE UI Canvases (menus, HUD) are authored in the separate
   UI Editor — the generated Lua scripts implement each feature's
   underlying state/logic, not a visual UI. Wire a `.uicanvas` to call
   into them as needed.
3. **Backend connectivity.** O3DE's core Lua bindings have no built-in
   HTTP client, so any feature that would normally call your backend
   API only has its local game-state logic generated (flagged with a
   comment in the relevant script) — real network calls need a custom
   Gem.

## Getting it into the Editor

```
o3de register --project-path .
```
(Requires an O3DE engine install — see https://o3de.org/download —
and its `bin/` folder on your PATH, or run the full path to `o3de`/
`o3de.bat`.) Then open O3DE's Project Manager, find "{project_name}"
in your registered projects, and open it — this builds the project's
Editor the first time, which takes a while.

From there, use the Editor's own Export/Game Export workflow (or a
custom `o3de export-project --export-script ...`) to produce a
platform build — that step is intentionally NOT scripted here since
it depends on which platform and export settings you want, and O3DE's
own export tooling expects a project-specific export script.
"""


def manifest_files(project_name: str, screen_files: list[GeneratedFile]) -> list[GeneratedFile]:
    return [
        GeneratedFile(
            path="frontend/project.json",
            language="json",
            content=json.dumps(_project_json(project_name), indent=4),
            description="Real O3DE project descriptor",
        ),
        GeneratedFile(
            path="frontend/Levels/Main/Main.prefab",
            language="json",
            content=json.dumps(_level_prefab(project_name, screen_files), indent=4),
            description="O3DE level — one entity per generated feature, each wired to its Lua script",
        ),
        GeneratedFile(
            path="frontend/README_O3DE_SETUP.md",
            language="markdown",
            content=_README_O3DE_SETUP.format(project_name=project_name or "Generated Game"),
            description="Manual setup steps — least-automatable part of the O3DE pipeline",
        ),
    ]


def setup_commands(project_name: str) -> list[str]:
    return [
        "cd frontend",
        "# Requires a real O3DE engine install (https://o3de.org/download) with its bin/ on PATH.",
        "o3de register --project-path .",
        "# Then open O3DE's Project Manager and open this project from your registered list.",
        "# See README_O3DE_SETUP.md for the one-time script re-link step and other manual steps.",
    ]
