# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Code Generation API Routes (Sprint 6, updated)
#  api/v1/codegen.py — Generate a REAL, working implementation from
#  approved architecture — one dedicated AI call per model/route/
#  screen file (each gets its own full token budget instead of many
#  files sharing one small JSON response), then a final wiring pass
#  (main.py, App.jsx, package.json, etc.) that stitches them into an
#  installable, startable project.
# ═══════════════════════════════════════════════════════════════

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.codegen import godot, o3de
from app.ai.codegen.backend import BACKEND_ADAPTERS
from app.ai.codegen.frontend import FRONTEND_ADAPTERS
from app.ai.codegen.readme import build_readme_setup
from app.ai.codegen.types import ModelCtx, RoutesCtx, ScreenCtx, WiringCtx
from app.ai.codegen_shared import (
    GROQ_WIRING_MAX_TOKENS,
    GeneratedFile,
    apply_package_json_name,
    detect_native_capabilities,
    parse_ai_json,
)
from app.ai.orchestrator import AIError, generate_text
from app.ai.stack_matrix import get_project_stack
from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.project import Project, SDLCPhase
from app.models.user import User

# Backend-specific setup caveats that don't belong in any one adapter's
# deterministic setup_commands() (those are literal shell commands, not
# prose) but are still worth surfacing in README_SETUP.md.
_BACKEND_SETUP_NOTES: dict[str, list[str]] = {
    "express": [
        "Requires a local or hosted MongoDB instance — set MONGODB_URI in a .env file "
        "(defaults to mongodb://localhost:27017/app)."
    ],
}

logger = logging.getLogger("vengaicode.codegen")
router = APIRouter()


# ─── Schemas ───
class GenerateCodeRequest(BaseModel):
    project_id: str


class CodeGenResult(BaseModel):
    summary: str
    files: list[GeneratedFile]


class StackUsed(BaseModel):
    codegen_target: str  # "react_fastapi" | "vue_express" | "o3de"
    source: str  # "selected_stack" | "downgraded_selection" | "legacy_o3de_detection" | "fallback_default"
    fallback_reason: str | None = None


class GenerateCodeResponse(BaseModel):
    success: bool = True
    codegen: CodeGenResult
    stack_used: StackUsed


class ApproveCodeRequest(BaseModel):
    project_id: str
    approved: bool = True


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


@router.post(
    "/generate",
    response_model=GenerateCodeResponse,
    summary="Generate a real, working implementation from approved architecture",
)
async def generate_code(
    payload: GenerateCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the approved architecture, UI/UX design, and original requirements
    and generates a real implementation — one dedicated AI call per model,
    routes file, and screen (each with the full requirements context and its
    own token budget), then a final wiring pass that stitches everything into
    an installable, startable project.
    """
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.architecture_data or not project.architecture_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Architecture must be approved before generating code.",
        )

    architecture = (project.architecture_data or {}).get("architecture", {})
    uiux = (project.uiux_data or {}).get("design", {})
    requirements = project.requirements_data or {}
    requirements_text = _requirements_context(requirements)

    tables = architecture.get("database_tables", [])
    endpoints = architecture.get("api_endpoints", [])
    screens = uiux.get("screens", []) or [{"name": "Home", "purpose": "Landing screen"}]

    stack_info = get_project_stack(project)
    is_o3de = stack_info["frontend_framework"] == "o3de"
    is_godot = stack_info["frontend_framework"] == "godot"

    frd = requirements.get("frd", {}) or {}
    native_capabilities = detect_native_capabilities(
        " ".join(frd.get("key_features", []) or []) + " " + " ".join(frd.get("user_stories", []) or [])
    ) if not (is_o3de or is_godot) else []

    validation_warnings: list[dict] = []

    def _track(file_and_issue: tuple[GeneratedFile, str | None]) -> GeneratedFile:
        file, issue = file_and_issue
        if issue:
            validation_warnings.append({"path": file.path, "reason": issue})
        return file

    try:
        if is_o3de:
            # O3DE has no separate backend (stack_matrix's "none" sentinel)
            # and isn't part of the frontend/backend adapter registries —
            # see app/ai/codegen/o3de.py for why.
            model_files: list[GeneratedFile] = []
            routes_files: list[GeneratedFile] = []
            screen_files = [
                _track(await o3de.generate_screen(ScreenCtx(
                    project_name=project.name,
                    screen=screen,
                    endpoints=endpoints,
                    requirements_text=requirements_text,
                    native_capabilities=[],
                    language="o3de_script",
                )))
                for screen in screens
            ]

            wiring_prompt = o3de.build_wiring_prompt(
                project.name, ", ".join(f.path for f in screen_files) or "(none)"
            )
            wiring_result = await generate_text(wiring_prompt, max_tokens=GROQ_WIRING_MAX_TOKENS)
            wiring_parsed = parse_ai_json(wiring_result["text"])
            real_files = screen_files
            generated_files = [f.model_dump() for f in real_files] + wiring_parsed.get("files", [])
            summary = wiring_parsed.get(
                "summary", f"Generated {len(real_files)} real implementation files plus wiring/config."
            )
        elif is_godot:
            # Godot has no separate backend either (same "none" sentinel as
            # O3DE), but unlike O3DE its wiring/manifest files are built
            # deterministically (no AI call) — see godot.py's manifest_files/
            # entry_point_files, same pattern as the Compose/Flutter adapters.
            model_files = []
            routes_files = []
            screen_files = [
                _track(await godot.generate_screen(ScreenCtx(
                    project_name=project.name,
                    screen=screen,
                    endpoints=endpoints,
                    requirements_text=requirements_text,
                    native_capabilities=[],
                    language="gdscript",
                )))
                for screen in screens
            ]

            wiring_files = godot.manifest_files(project.name) + godot.entry_point_files(screen_files)
            wiring_files.append(build_readme_setup(
                project.name, None, godot.setup_commands(project.name), None,
            ))
            real_files = screen_files
            generated_files = [f.model_dump() for f in real_files + wiring_files]
            summary = f"Generated {len(real_files)} real Godot scene files plus wiring/config."
        else:
            frontend_adapter = FRONTEND_ADAPTERS[stack_info["frontend_framework"]]
            backend_adapter = BACKEND_ADAPTERS[stack_info["backend_framework"]]

            model_files = [
                _track(await backend_adapter.generate_model(ModelCtx(
                    project_name=project.name,
                    table=table,
                    requirements_text=requirements_text,
                    language=stack_info["backend_language"],
                )))
                for table in tables
            ]

            routes_files = []
            if endpoints:
                routes_results = await backend_adapter.generate_routes(RoutesCtx(
                    project_name=project.name,
                    endpoints=endpoints,
                    tables=tables,
                    requirements_text=requirements_text,
                    api_style=stack_info["api_style"],
                    language=stack_info["backend_language"],
                ))
                routes_files = [_track(r) for r in routes_results]

            screen_files = [
                _track(await frontend_adapter.generate_screen(ScreenCtx(
                    project_name=project.name,
                    screen=screen,
                    endpoints=endpoints,
                    requirements_text=requirements_text,
                    native_capabilities=native_capabilities,
                    language=stack_info["frontend_language"],
                )))
                for screen in screens
            ]

            # Deterministic wiring — no AI call. See manifests/ and each
            # adapter's manifest_files/entry_point_files: known-good,
            # version-pinned templates can't produce invalid manifest
            # syntax the way asking an LLM to freehand one can.
            wiring_ctx = WiringCtx(
                project_name=project.name,
                model_files=model_files,
                routes_files=routes_files,
                screen_files=screen_files,
                endpoints=endpoints,
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
            wiring_files.append(build_readme_setup(
                project.name,
                backend_commands,
                frontend_commands,
                _BACKEND_SETUP_NOTES.get(stack_info["backend_framework"]),
            ))

            # Deliberately NOT adding native-capability helper files here —
            # see the comment on NATIVE_CAPABILITY_DESCRIPTIONS in
            # codegen_shared.py. Each packaging workflow writes its own
            # platform-appropriate implementation of frontend/src/native/*.js
            # at build time instead.
            real_files = model_files + routes_files + screen_files
            generated_files = [f.model_dump() for f in real_files + wiring_files]
            summary = f"Generated {len(real_files)} real implementation files plus wiring/config."

        parsed = {"summary": summary, "files": generated_files}
        apply_package_json_name(parsed["files"], project.name)
        print("===== GENERATED FILES =====")
        for f in parsed.get("files", []):
            print(f["path"])
        if validation_warnings:
            print(f"===== VALIDATION WARNINGS ({len(validation_warnings)}) =====")
            for w in validation_warnings:
                print(f"{w['path']}: {w['reason']}")
        print("===========================")
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI codegen response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble writing your code. Please try again! 🐯",
        )

    codegen_result = CodeGenResult(**parsed)
    stack_used = StackUsed(**stack_info)

    project.codegen_data = {
        "codegen": codegen_result.model_dump(),
        "files_generated": len(codegen_result.files),
        "native_capabilities": native_capabilities,
        "validation_warnings": validation_warnings,
        "stack_used": stack_used.model_dump(),
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()

    return GenerateCodeResponse(codegen=codegen_result, stack_used=stack_used)


@router.get(
    "/{project_id}",
    summary="Get saved generated code",
)
async def get_code(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve previously generated code files."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.codegen_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No code generated yet.",
        )

    return {
        "success": True,
        "codegen": project.codegen_data.get("codegen"),
        "user_approved": project.codegen_data.get("user_approved", False),
        "generated_at": project.codegen_data.get("generated_at"),
        "stack_used": project.codegen_data.get("stack_used"),
    }


@router.post(
    "/approve",
    summary="Approve generated code and move to next phase",
)
async def approve_code(
    payload: ApproveCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves the generated code. Marks phase complete."""
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.codegen_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No generated code to approve.",
        )

    # Reassign whole dict — required for SQLAlchemy JSON column change tracking
    codegen_data = dict(project.codegen_data)
    codegen_data["user_approved"] = payload.approved
    codegen_data["approved_at"] = datetime.now(timezone.utc).isoformat()
    project.codegen_data = codegen_data

    if payload.approved:
        phases = project.phases_completed or []
        if "code_generation" not in phases:
            phases.append("code_generation")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.current_phase = SDLCPhase.TESTING

    await db.commit()

    return {
        "success": True,
        "message": "Code approved! Next: Testing 🐯" if payload.approved else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }
