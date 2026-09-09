# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Code Generation Runner
#  ai/codegen_runner.py — Code generation expressed as a list of
#  resumable steps (one AI call each) instead of one long function.
#
#  This is the same generation the API used to do inline: one dedicated
#  AI call per model/routes/screen file so each gets its own full token
#  budget, then a deterministic wiring pass. The only thing that changed
#  is WHERE it runs — services/generation_jobs.py drives these steps in
#  the background and saves after every one, because the run time grows
#  with the project (tables + screens) while an HTTP timeout doesn't.
#
#  Every step re-derives its context from the project row rather than
#  carrying it in the job, so a run that resumes in a different process
#  (after a redeploy, say) needs nothing but the step index.
# ═══════════════════════════════════════════════════════════════

import hashlib
import json
import logging
from datetime import datetime, timezone

from app.ai.codegen import godot, o3de
from app.ai.codegen.backend import BACKEND_ADAPTERS
from app.ai.codegen.frontend import FRONTEND_ADAPTERS
from app.ai.codegen.readme import build_readme_setup
from app.ai.codegen.types import ModelCtx, RoutesCtx, ScreenCtx, WiringCtx
from app.ai.codegen_shared import (
    GeneratedFile,
    apply_package_json_name,
    detect_native_capabilities,
    get_ordered_pages,
)
from app.ai.stack_matrix import get_project_stack
from app.models.project import Project
from app.services.generation_jobs import PhaseRunner, StepCtx

logger = logging.getLogger("vengaicode.codegen")

PHASE = "code_generation"

# Backend-specific setup caveats that don't belong in any one adapter's
# deterministic setup_commands() (those are literal shell commands, not
# prose) but are still worth surfacing in README_SETUP.md.
_BACKEND_SETUP_NOTES: dict[str, list[str]] = {
    "express": [
        "Requires a local or hosted MongoDB instance — set MONGODB_URI in a .env file "
        "(defaults to mongodb://localhost:27017/app)."
    ],
}

# What the AI-generated files are grouped under in the job's saved
# state. The wiring pass needs them kept apart (a backend model file and
# a screen file are not interchangeable inputs to a manifest builder).
_GROUPS = ("model", "routes", "screen")


class CodegenError(RuntimeError):
    """A failure with a message meant for the user, not a stack trace."""


def _requirements_context(requirements: dict) -> str:
    frd = requirements.get("frd", {}) if requirements else {}
    if not frd:
        return ""

    features = frd.get("key_features", [])
    stories = frd.get("user_stories", [])
    features_text = "\n".join(f"- {f}" for f in features)
    stories_text = "\n".join(f"- {s}" for s in stories)

    return f"""
Problem this app solves: {frd.get('problem_statement', '')}
Target users: {frd.get('target_users', '')}

Key features (implement the REAL logic for each of these — not a stub):
{features_text}

User stories (the code must actually satisfy these, not just render placeholder UI):
{stories_text}
"""


def build_context(project: Project) -> dict:
    """Everything the steps generate from, derived from the project row.

    Cheap and deterministic (dict lookups plus get_ordered_pages), so
    every step recomputes it instead of the job carrying a snapshot."""
    architecture = (project.architecture_data or {}).get("architecture", {})
    uiux = (project.uiux_data or {}).get("design", {})
    requirements = project.requirements_data or {}

    stack_info = get_project_stack(project)
    is_o3de = stack_info["frontend_framework"] == "o3de"
    is_godot = stack_info["frontend_framework"] == "godot"

    frd = requirements.get("frd", {}) or {}
    native_capabilities = (
        detect_native_capabilities(
            " ".join(frd.get("key_features", []) or [])
            + " "
            + " ".join(frd.get("user_stories", []) or [])
        )
        if not (is_o3de or is_godot)
        else []
    )

    return {
        "stack_info": stack_info,
        "is_o3de": is_o3de,
        "is_godot": is_godot,
        "tables": architecture.get("database_tables", []),
        "endpoints": architecture.get("api_endpoints", []),
        "screens": get_ordered_pages(project.uiux_data)
        or [{"name": "Home", "purpose": "Landing screen"}],
        "requirements_text": _requirements_context(requirements),
        "design_style": uiux.get("design_style"),
        "color_palette": uiux.get("color_palette"),
        "typography": uiux.get("typography"),
        "native_capabilities": native_capabilities,
    }


# ───────────────────────────────────────────────
#  Plan
# ───────────────────────────────────────────────
def fingerprint(project: Project) -> str:
    """Identifies the inputs a run was planned from. A different
    architecture, design or stack means a half-finished run's files
    belong to a different app and must not be resumed into this one."""
    ctx = build_context(project)
    material = json.dumps(
        {
            "stack": ctx["stack_info"],
            "tables": ctx["tables"],
            "endpoints": ctx["endpoints"],
            "screens": ctx["screens"],
            "requirements": ctx["requirements_text"],
            "name": project.name,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def steps(project: Project, state: dict) -> list[dict]:
    """The full step list. Fixed for codegen — every table, routes file
    and screen is known from the approved architecture up front, so
    `state` isn't consulted."""
    ctx = build_context(project)
    plan: list[dict] = []

    # O3DE and Godot have no separate backend (stack_matrix's "none"
    # sentinel) and aren't in the adapter registries — see
    # ai/codegen/o3de.py — so they generate screens only.
    if not (ctx["is_o3de"] or ctx["is_godot"]):
        for i, table in enumerate(ctx["tables"]):
            plan.append(
                {
                    "kind": "model",
                    "index": i,
                    "label": f"Data model: {table.get('name', 'table')}",
                }
            )
        if ctx["endpoints"]:
            plan.append({"kind": "routes", "index": 0, "label": "API routes"})

    for i, screen in enumerate(ctx["screens"]):
        plan.append(
            {
                "kind": "screen",
                "index": i,
                "label": f"Screen: {screen.get('name', 'screen')}",
            }
        )

    return plan


# ───────────────────────────────────────────────
#  One step
# ───────────────────────────────────────────────
def _record(state: dict, group: str, results) -> None:
    """Append a step's output to the run's saved state, keeping any
    validation warning the adapter reported alongside the file."""
    files = list(state.get(group, []))
    warnings = list(state.get("warnings", []))

    for file, issue in results:
        files.append(file.model_dump())
        if issue:
            warnings.append({"path": file.path, "reason": issue})

    state[group] = files
    state["warnings"] = warnings


async def run_step(ctx: StepCtx) -> None:
    c = build_context(ctx.project)
    step = ctx.step
    kind = step["kind"]
    index = step["index"]

    try:
        if kind == "model":
            adapter = BACKEND_ADAPTERS[c["stack_info"]["backend_framework"]]
            result = await adapter.generate_model(
                ModelCtx(
                    project_name=ctx.project.name,
                    table=c["tables"][index],
                    requirements_text=c["requirements_text"],
                    language=c["stack_info"]["backend_language"],
                    user=ctx.user,
                    db=ctx.db,
                )
            )
            _record(ctx.state, "model", [result])

        elif kind == "routes":
            adapter = BACKEND_ADAPTERS[c["stack_info"]["backend_framework"]]
            results = await adapter.generate_routes(
                RoutesCtx(
                    project_name=ctx.project.name,
                    endpoints=c["endpoints"],
                    tables=c["tables"],
                    requirements_text=c["requirements_text"],
                    api_style=c["stack_info"]["api_style"],
                    language=c["stack_info"]["backend_language"],
                    user=ctx.user,
                    db=ctx.db,
                )
            )
            _record(ctx.state, "routes", results)

        elif kind == "screen":
            # O3DE/Godot screens are scripts in a fixed engine language
            # and have no native-capability shims; every other frontend
            # takes the stack's language and the detected capabilities.
            if c["is_o3de"]:
                generate_screen, language = o3de.generate_screen, "lua"
            elif c["is_godot"]:
                generate_screen, language = godot.generate_screen, "gdscript"
            else:
                adapter = FRONTEND_ADAPTERS[c["stack_info"]["frontend_framework"]]
                generate_screen = adapter.generate_screen
                language = c["stack_info"]["frontend_language"]

            result = await generate_screen(
                ScreenCtx(
                    project_name=ctx.project.name,
                    screen=c["screens"][index],
                    endpoints=c["endpoints"],
                    requirements_text=c["requirements_text"],
                    native_capabilities=c["native_capabilities"],
                    language=language,
                    user=ctx.user,
                    db=ctx.db,
                    design_style=c["design_style"],
                    color_palette=c["color_palette"],
                    typography=c["typography"],
                )
            )
            _record(ctx.state, "screen", [result])

        else:
            raise CodegenError(f"Unknown code generation step: {kind}")

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        # Same failure the route used to turn into a 502 — the model
        # returned something that isn't the JSON we asked for.
        logger.error(f"Failed to parse AI codegen response ({kind}): {e}")
        raise CodegenError(
            "Baby Tiger had trouble writing your code. Please try again! 🐯"
        ) from e


# ───────────────────────────────────────────────
#  Finish
# ───────────────────────────────────────────────
def _files(state: dict, group: str) -> list[GeneratedFile]:
    return [GeneratedFile(**f) for f in state.get(group, [])]


async def finalize(project: Project, state: dict) -> None:
    """Turn the AI-generated files into a complete project: add the
    deterministic wiring/manifest files, then save onto the project.

    Wiring is built here, not as steps, because it involves no AI call —
    known-good, version-pinned templates can't produce invalid manifest
    syntax the way asking a model to freehand one can (see manifests/
    and each adapter's manifest_files/entry_point_files)."""
    c = build_context(project)
    stack_info = c["stack_info"]

    model_files = _files(state, "model")
    routes_files = _files(state, "routes")
    screen_files = _files(state, "screen")
    validation_warnings = list(state.get("warnings", []))

    if c["is_o3de"]:
        # project.json and the level prefab are real O3DE formats a
        # freeform AI JSON call can't be trusted to reproduce — see
        # o3de.py's header.
        wiring_files = o3de.manifest_files(project.name, screen_files)
        wiring_files.append(
            build_readme_setup(project.name, None, o3de.setup_commands(project.name), None)
        )
        real_files = screen_files
        summary = (
            f"Generated {len(real_files)} real O3DE Lua behavior scripts "
            "plus project/level wiring."
        )
    elif c["is_godot"]:
        wiring_files = godot.manifest_files(project.name) + godot.entry_point_files(
            screen_files
        )
        wiring_files.append(
            build_readme_setup(project.name, None, godot.setup_commands(project.name), None)
        )
        real_files = screen_files
        summary = f"Generated {len(real_files)} real Godot scene files plus wiring/config."
    else:
        frontend_adapter = FRONTEND_ADAPTERS[stack_info["frontend_framework"]]
        backend_adapter = BACKEND_ADAPTERS[stack_info["backend_framework"]]

        wiring_ctx = WiringCtx(
            project_name=project.name,
            model_files=model_files,
            routes_files=routes_files,
            screen_files=screen_files,
            endpoints=c["endpoints"],
            tables=c["tables"],
        )
        wiring_files = []
        for adapter in (backend_adapter, frontend_adapter):
            if adapter.manifest_files:
                wiring_files += adapter.manifest_files(wiring_ctx)
            if adapter.entry_point_files:
                wiring_files += adapter.entry_point_files(wiring_ctx)

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
                _BACKEND_SETUP_NOTES.get(stack_info["backend_framework"]),
            )
        )

        # Deliberately NOT adding native-capability helper files here —
        # see the comment on NATIVE_CAPABILITY_DESCRIPTIONS in
        # codegen_shared.py. Each packaging workflow writes its own
        # platform-appropriate frontend/src/native/*.js at build time.
        real_files = model_files + routes_files + screen_files
        summary = f"Generated {len(real_files)} real implementation files plus wiring/config."

    generated_files = [f.model_dump() for f in real_files + wiring_files]
    apply_package_json_name(generated_files, project.name)

    print("===== GENERATED FILES =====")
    for f in generated_files:
        print(f["path"])
    if validation_warnings:
        print(f"===== VALIDATION WARNINGS ({len(validation_warnings)}) =====")
        for w in validation_warnings:
            print(f"{w['path']}: {w['reason']}")
    print("===========================")

    project.codegen_data = {
        "codegen": {"summary": summary, "files": generated_files},
        "files_generated": len(generated_files),
        "native_capabilities": c["native_capabilities"],
        "validation_warnings": validation_warnings,
        # Only the three fields the UI reports on — the same subset the
        # response model has always stored, not the whole resolved stack.
        "stack_used": {
            "codegen_target": stack_info["codegen_target"],
            "source": stack_info["source"],
            "fallback_reason": stack_info.get("fallback_reason"),
        },
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


RUNNER = PhaseRunner(
    phase=PHASE,
    fingerprint=fingerprint,
    steps=steps,
    run_step=run_step,
    finalize=finalize,
)
