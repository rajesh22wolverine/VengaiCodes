# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Requirements API Routes (Sprint 3)
#  api/v1/requirements.py — Generate FRD from wizard conversation
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

logger = logging.getLogger("vengaicode.requirements")
router = APIRouter()


# ─── Schemas ───
class GenerateRequirementsRequest(BaseModel):
    project_id: str


class RequirementsDocument(BaseModel):
    overview: str
    problem_statement: str
    target_users: str
    key_features: list[str]
    platforms: list[str]
    monetization: str
    reference_apps: list[str]
    user_stories: list[str]
    tech_recommendations: str


class GenerateRequirementsResponse(BaseModel):
    success: bool = True
    requirements: RequirementsDocument


class ApproveRequirementsRequest(BaseModel):
    project_id: str
    approved: bool = True


# ─── Prompt builder ───
def build_frd_prompt(project_name: str, raw_idea: str, conversation: list) -> str:
    convo_text = ""
    for msg in conversation:
        role = "User" if msg["role"] == "user" else "Baby Tiger"
        convo_text += f"{role}: {msg['content']}\n"

    return f"""You are Baby Tiger 🐯, VengaiCode's AI assistant. Based on this conversation with a user about their app idea, generate a structured Functional Requirements Document (FRD).

Project: {project_name}
Original idea: {raw_idea}

Full conversation:
{convo_text}

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "overview": "2-3 sentence summary of the app",
  "problem_statement": "1-2 sentences on what problem this solves",
  "target_users": "1-2 sentences describing who will use this",
  "key_features": ["feature 1", "feature 2", "feature 3"],
  "platforms": ["platform1", "platform2"],
  "monetization": "1 sentence on the business model",
  "reference_apps": ["app1", "app2"],
  "user_stories": [
    "As a [user type], I want to [action] so that [benefit]",
    "As a [user type], I want to [action] so that [benefit]",
    "As a [user type], I want to [action] so that [benefit]"
  ],
  "tech_recommendations": "1-2 sentences suggesting a simple, open-source tech approach suitable for this app's complexity"
}}

Respond with ONLY the JSON object, nothing else."""


def parse_ai_json(text: str) -> dict:
    """Extract and parse JSON from AI response, handling markdown code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


@router.post(
    "/generate",
    response_model=GenerateRequirementsResponse,
    summary="Generate FRD from wizard conversation",
)
async def generate_requirements(
    payload: GenerateRequirementsRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the completed wizard conversation and generates a structured
    Functional Requirements Document using AI.
    """
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    if project.understanding_score < 100.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete the wizard conversation first (understanding score must reach 100%).",
        )

    conversation = project.ai_conversation_history or []

    try:
        prompt = build_frd_prompt(project.name, project.raw_idea or project.name, conversation)
        ai_result = await generate_text(prompt)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI FRD response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble organizing your requirements. Please try again! 🐯",
        )

    requirements = RequirementsDocument(**parsed)

    # Save to project
    project.requirements_data = {
        "frd": requirements.model_dump(),
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()

    return GenerateRequirementsResponse(requirements=requirements)


@router.get(
    "/{project_id}",
    summary="Get saved requirements document",
)
async def get_requirements(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a previously generated requirements document."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.requirements_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No requirements document generated yet.",
        )

    return {
        "success": True,
        "requirements": project.requirements_data.get("frd"),
        "user_approved": project.requirements_data.get("user_approved", False),
        "generated_at": project.requirements_data.get("generated_at"),
    }


@router.post(
    "/approve",
    summary="Approve requirements and move to next phase",
)
async def approve_requirements(
    payload: ApproveRequirementsRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    User approves the generated FRD. Marks requirements phase complete
    and unlocks progression to UI/UX phase (Sprint 4).
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

    if not project.requirements_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No requirements document to approve.",
        )

    project.requirements_data["user_approved"] = payload.approved
    project.requirements_data["approved_at"] = datetime.now(timezone.utc).isoformat()

    if payload.approved:
        phases = project.phases_completed or []
        if "requirements" not in phases:
            phases.append("requirements")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.status = "in_progress"

    await db.commit()

    return {
        "success": True,
        "message": "Requirements approved! Ready for the next phase 🐯" if payload.approved else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }
