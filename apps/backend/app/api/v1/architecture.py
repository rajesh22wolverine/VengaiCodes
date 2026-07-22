# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Architecture API Routes (Sprint 5)
#  api/v1/architecture.py — Generate tech stack, schema, API list
#  from approved requirements + UI/UX design
# ═══════════════════════════════════════════════════════════════

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIError, generate_text
from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.project import Project, SDLCPhase
from app.models.user import User

logger = logging.getLogger("vengaicode.architecture")
router = APIRouter()


# ─── Schemas ───
class GenerateArchitectureRequest(BaseModel):
    project_id: str


class TechStack(BaseModel):
    frontend: str
    backend: str
    database: str
    hosting: str


class DatabaseTable(BaseModel):
    name: str
    purpose: str
    key_fields: list[str]


class APIEndpoint(BaseModel):
    method: str
    path: str
    purpose: str


class ArchitectureDesign(BaseModel):
    architecture_summary: str
    tech_stack: TechStack
    database_tables: list[DatabaseTable]
    api_endpoints: list[APIEndpoint]
    third_party_services: list[str]


class GenerateArchitectureResponse(BaseModel):
    success: bool = True
    architecture: ArchitectureDesign


class ApproveArchitectureRequest(BaseModel):
    project_id: str
    approved: bool = True


# ─── Prompt builder ───
def build_stack_directive(selected_stack: dict | None) -> str:
    """
    Renders the user's explicit UI/backend/API pick (from the Stack step,
    /api/v1/stack) as a directive for the architecture prompt, so the pick
    actually reaches what the AI proposes instead of being ignored.
    """
    if not selected_stack:
        return ""

    directive = (
        f"\nThe user has EXPLICITLY chosen this tech stack — use EXACTLY this, "
        f"do not substitute a different framework or language:\n"
        f"- Frontend: {selected_stack.get('frontend_framework')} "
        f"({selected_stack.get('frontend_language')})\n"
        f"- Backend: {selected_stack.get('backend_framework')} "
        f"({selected_stack.get('backend_language')})\n"
        f"- API style: {selected_stack.get('api_style')}\n"
    )
    if not selected_stack.get("buildable_now", True):
        directive += (
            "Note: this stack is valid but not yet buildable by VengaiCode's code "
            "generator — the user has already been told code generation will "
            "substitute the closest buildable stack, so still describe the "
            "architecture in terms of their chosen stack here.\n"
        )
    return directive


def build_architecture_prompt(
    project_name: str, requirements: dict, uiux: dict, selected_stack: dict | None = None
) -> str:
    features = ", ".join(requirements.get("key_features", []))
    platforms = ", ".join(requirements.get("platforms", []))
    screen_names = ", ".join(s.get("name", "") for s in uiux.get("screens", []))
    tech_hint = requirements.get("tech_recommendations", "")
    stack_directive = build_stack_directive(selected_stack)

    return f"""You are Baby Tiger 🐯, VengaiCode's AI architecture assistant. Based on this app's approved requirements and UI/UX design, propose a simple, open-source technical architecture.

App: {project_name}
Overview: {requirements.get('overview', '')}
Key features: {features}
Platforms: {platforms}
Screens: {screen_names}
Complexity hint: {tech_hint}
{stack_directive}
If the app is a game, favor Godot Engine for the tech stack — it's fully open-source, capable of high-end 2D/3D games, and VengaiCode can build it into a real installable APK automatically. Only suggest Open 3D Engine (O3DE) instead if the user explicitly asked for an AAA-grade engine by name — O3DE has no automated build pipeline here, so it stays a downloadable project template the user builds themselves. If the app is not a game, favor simple open-source web or mobile technologies.

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "architecture_summary": "2-3 sentences describing the overall technical approach",
  "tech_stack": {{
    "frontend": "framework/library choice + 1 sentence why it fits",
    "backend": "framework/language choice + 1 sentence why it fits",
    "database": "database choice + 1 sentence why it fits",
    "hosting": "suggested free/open-source hosting approach"
  }},
  "database_tables": [
    {{"name": "table_name", "purpose": "1 sentence", "key_fields": ["field1", "field2", "field3"]}}
  ],
  "api_endpoints": [
    {{"method": "GET", "path": "/resource", "purpose": "1 sentence"}}
  ],
  "third_party_services": ["service1 (why needed)", "service2 (why needed)"]
}}

Generate 3-6 database tables and 6-10 core API endpoints covering the key features.
Favor simple, well-known, open-source technology suitable for the app's complexity.
Use realistic REST conventions for API endpoint paths and methods.

Respond with ONLY the JSON object, nothing else."""


def parse_ai_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


@router.post(
    "/generate",
    response_model=GenerateArchitectureResponse,
    summary="Generate architecture from approved requirements + UI/UX",
)
async def generate_architecture(
    payload: GenerateArchitectureRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the approved requirements + UI/UX design and generates a
    technical architecture — tech stack, database schema, API endpoints.
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

    if not project.uiux_data or not project.uiux_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="UI/UX design must be approved before generating architecture.",
        )

    frd = (project.requirements_data or {}).get("frd", {})
    uiux = (project.uiux_data or {}).get("design", {})

    try:
        prompt = build_architecture_prompt(project.name, frd, uiux, project.selected_stack)
        ai_result = await generate_text(prompt)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI architecture response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble planning your architecture. Please try again! 🐯",
        )

    architecture = ArchitectureDesign(**parsed)

    project.architecture_data = {
        "architecture": architecture.model_dump(),
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()

    return GenerateArchitectureResponse(architecture=architecture)


@router.get(
    "/{project_id}",
    summary="Get saved architecture design",
)
async def get_architecture(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a previously generated architecture design."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.architecture_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No architecture generated yet.",
        )

    return {
        "success": True,
        "architecture": project.architecture_data.get("architecture"),
        "user_approved": project.architecture_data.get("user_approved", False),
        "generated_at": project.architecture_data.get("generated_at"),
    }


@router.post(
    "/approve",
    summary="Approve architecture and move to next phase",
)
async def approve_architecture(
    payload: ApproveArchitectureRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves the generated architecture. Marks phase complete."""
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.architecture_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No architecture to approve.",
        )

    # Reassign the whole dict — required for SQLAlchemy JSON column
    # change tracking (in-place mutation is not detected)
    architecture_data = dict(project.architecture_data)
    architecture_data["user_approved"] = payload.approved
    architecture_data["approved_at"] = datetime.now(timezone.utc).isoformat()
    project.architecture_data = architecture_data

    if payload.approved:
        phases = project.phases_completed or []
        if "architecture" not in phases:
            phases.append("architecture")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.current_phase = SDLCPhase.API_BUILDER

    await db.commit()

    return {
        "success": True,
        "message": "Architecture approved! Next: API Builder 🐯" if payload.approved else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }
