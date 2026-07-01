# ═══════════════════════════════════════════════════════════════
#  VengaiCode — UI/UX Design API Routes (Sprint 4)
#  api/v1/uiux.py — Generate design system from approved requirements
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
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger("vengaicode.uiux")
router = APIRouter()


# ─── Schemas ───
class GenerateUIUXRequest(BaseModel):
    project_id: str


class ScreenDefinition(BaseModel):
    name: str
    purpose: str
    key_elements: list[str]


class ColorPalette(BaseModel):
    primary: str
    secondary: str
    accent: str
    background: str
    text: str


class UIUXDesign(BaseModel):
    design_style: str
    color_palette: ColorPalette
    typography: str
    screens: list[ScreenDefinition]
    components: list[str]
    navigation_pattern: str


class GenerateUIUXResponse(BaseModel):
    success: bool = True
    design: UIUXDesign


class ApproveUIUXRequest(BaseModel):
    project_id: str
    approved: bool = True


# ─── Prompt builder ───
def build_uiux_prompt(project_name: str, requirements: dict) -> str:
    features = ", ".join(requirements.get("key_features", []))
    platforms = ", ".join(requirements.get("platforms", []))

    return f"""You are Baby Tiger 🐯, VengaiCode's AI design assistant. Based on this app's approved requirements, design a UI/UX system.

App: {project_name}
Overview: {requirements.get('overview', '')}
Key features: {features}
Platforms: {platforms}
Target users: {requirements.get('target_users', '')}

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "design_style": "1 sentence describing the visual style (e.g. 'clean and minimal with rounded corners, energetic accent colors')",
  "color_palette": {{
    "primary": "#hexcode",
    "secondary": "#hexcode",
    "accent": "#hexcode",
    "background": "#hexcode",
    "text": "#hexcode"
  }},
  "typography": "1 sentence on font choice and why it fits (e.g. 'Inter for a modern, friendly, highly readable feel')",
  "screens": [
    {{"name": "Screen Name", "purpose": "1 sentence what this screen does", "key_elements": ["element1", "element2", "element3"]}}
  ],
  "components": ["reusable component 1", "reusable component 2", "reusable component 3"],
  "navigation_pattern": "1 sentence describing how users move between screens (e.g. 'bottom tab bar with 4 main sections')"
}}

Generate 4-6 screens covering the core user journey. Pick colors that suit the app's purpose and target users. Choose real, valid hex codes.

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
    response_model=GenerateUIUXResponse,
    summary="Generate UI/UX design system from approved requirements",
)
async def generate_uiux(
    payload: GenerateUIUXRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the approved requirements document and generates a UI/UX
    design system — colors, typography, screens, components.
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

    if not project.requirements_data or not project.requirements_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requirements must be approved before generating UI/UX design.",
        )

    frd = project.requirements_data.get("frd", {})

    try:
        prompt = build_uiux_prompt(project.name, frd)
        ai_result = await generate_text(prompt)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI UI/UX response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble designing your app. Please try again! 🐯",
        )

    design = UIUXDesign(**parsed)

    project.uiux_data = {
        "design": design.model_dump(),
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()

    return GenerateUIUXResponse(design=design)


@router.get(
    "/{project_id}",
    summary="Get saved UI/UX design",
)
async def get_uiux(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a previously generated UI/UX design system."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.uiux_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No UI/UX design generated yet.",
        )

    return {
        "success": True,
        "design": project.uiux_data.get("design"),
        "user_approved": project.uiux_data.get("user_approved", False),
        "generated_at": project.uiux_data.get("generated_at"),
    }


@router.post(
    "/approve",
    summary="Approve UI/UX design and move to next phase",
)
async def approve_uiux(
    payload: ApproveUIUXRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves the generated UI/UX design. Marks phase complete."""
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.uiux_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No UI/UX design to approve.",
        )

    project.uiux_data["user_approved"] = payload.approved
    project.uiux_data["approved_at"] = datetime.now(timezone.utc).isoformat()

    if payload.approved:
        phases = project.phases_completed or []
        if "uiux" not in phases:
            phases.append("uiux")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.current_phase = "architecture"

    await db.commit()

    return {
        "success": True,
        "message": "UI/UX design approved! Next: Architecture 🐯" if payload.approved else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }
