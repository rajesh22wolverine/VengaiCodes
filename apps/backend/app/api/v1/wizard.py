# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Wizard API Routes (Sprint 2)
#  api/v1/wizard.py — 8-layer question engine
# ═══════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIError, generate_text
from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.project import Project, SDLCPhase, AppCategory
from app.models.user import User

logger = logging.getLogger("vengaicode.wizard")
router = APIRouter()


# ─── Schemas ───
class WizardMessageRequest(BaseModel):
    project_id: str
    user_message: str
    current_layer: int = 1


class WizardMessageResponse(BaseModel):
    success: bool = True
    ai_response: str
    next_layer: int
    understanding_score: float
    is_complete: bool
    layer_label: str


# ─── Layer definitions ───
LAYERS = {
    1: {
        "label": "Core Idea",
        "prompt_suffix": "Ask ONE clear question about the core purpose of their app and who will use it. Be friendly and encouraging. Keep it short.",
    },
    2: {
        "label": "Problem",
        "prompt_suffix": "Ask ONE question about what specific problem this app solves. Be conversational.",
    },
    3: {
        "label": "Key Features",
        "prompt_suffix": "Ask ONE question about the 3 most important features they want. Give a brief example to help them think.",
    },
    4: {
        "label": "Platforms / Game Type",
        "prompt_suffix": "Ask ONE question about which platforms they want — Web, Mobile (Android/iOS), Desktop (Windows/Mac), or all of them. If this app should be a game, also ask what type of game it should be and which device(s) it should target. If they want a high-end open-source game engine, mention Open 3D Engine (O3DE) as an option.",
    },
    5: {
        "label": "Target Users",
        "prompt_suffix": "Ask ONE question about who exactly will use this app — age, location, technical level.",
    },
    6: {
        "label": "Monetization",
        "prompt_suffix": "Ask ONE question about how they plan to make money — free, paid, subscription, ads, or commission.",
    },
    7: {
        "label": "References",
        "prompt_suffix": "Ask ONE question about any existing apps they like or want to be similar to.",
    },
    8: {
        "label": "App Name",
        "prompt_suffix": "Ask ONE question about what they'd like to name their app — a working title is fine, Baby Tiger can help refine it later. This is the last question!",
    },
}


def build_prompt(
    project_name: str,
    raw_idea: str,
    conversation_history: list,
    current_layer: int,
    user_message: str,
) -> str:
    layer = LAYERS.get(current_layer, LAYERS[8])

    history_text = ""
    for msg in conversation_history[-6:]:  # Last 6 messages for context
        role = "User" if msg["role"] == "user" else "Baby Tiger"
        history_text += f"{role}: {msg['content']}\n"

    return f"""You are Baby Tiger 🐯, VengaiCode's friendly AI assistant. You help non-technical users build apps by asking smart questions.

Project: {project_name}
User's idea: {raw_idea}
Current question layer: {current_layer}/8 ({layer['label']})

Conversation so far:
{history_text}
User just said: {user_message}

Your task: {layer['prompt_suffix']}

Rules:
- Be warm, encouraging and conversational
- Ask ONLY ONE question at a time
- Keep your response under 3 sentences
- Use simple language (no technical jargon)
- Add a relevant emoji occasionally
- If this is layer 8, end with "I think I understand your app well now! Let me create your requirements document 🐯"

Your response:"""


@router.post(
    "/message",
    response_model=WizardMessageResponse,
    summary="Send a message to Baby Tiger wizard",
)
async def wizard_message(
    payload: WizardMessageRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Multi-turn conversation with Baby Tiger.
    Each message advances through the 8 question layers.
    Returns AI response + understanding score progress.
    """
    # Get project
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

    # Get conversation history
    history = project.ai_conversation_history or []

    # Add user message to history
    history.append({
        "role": "user",
        "content": payload.user_message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "layer": payload.current_layer,
    })

    # Detect game intent and mark project category if appropriate
    user_text = payload.user_message.lower()
    if project.category != AppCategory.GAME and any(
        term in user_text
        for term in ["game", "gameplay", "fps", "rpg", "puzzle", "platformer", "strategy", "simulation", "adventure", "match-3", "o3de", "open 3d engine", "open3dengine"]
    ):
        project.category = AppCategory.GAME

    # Capture the user-suggested app name from the final wizard question
    if payload.current_layer == 8:
        suggested_name = payload.user_message.strip()
        if suggested_name:
            project.name = suggested_name[:255]

    # Determine next layer
    next_layer = min(payload.current_layer + 1, 8)
    is_complete = payload.current_layer >= 8

    # Calculate understanding score (each layer = 12.5%)
    understanding_score = min((payload.current_layer / 8) * 100, 100)

    # Build prompt and call AI
    try:
        prompt = build_prompt(
            project_name=project.name,
            raw_idea=project.raw_idea or project.name,
            conversation_history=history,
            current_layer=payload.current_layer,
            user_message=payload.user_message,
        )
        ai_result = await generate_text(prompt)
        ai_response = ai_result["text"]
    except AIError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # Add AI response to history
    history.append({
        "role": "ai",
        "content": ai_response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "layer": payload.current_layer,
    })

    # Update project
    project.ai_conversation_history = history
    project.understanding_score = understanding_score
    if is_complete:
        project.current_phase = SDLCPhase.REQUIREMENTS
        project.progress_percent = 14.0  # Phase 1 of 7 complete

    await db.commit()

    layer_label = LAYERS.get(payload.current_layer, {}).get("label", "")

    return WizardMessageResponse(
        ai_response=ai_response,
        next_layer=next_layer,
        understanding_score=understanding_score,
        is_complete=is_complete,
        layer_label=layer_label,
    )


@router.get(
    "/{project_id}/history",
    summary="Get wizard conversation history",
)
async def get_wizard_history(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the full conversation history for a project."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    return {
        "success": True,
        "project_id": project_id,
        "project_name": project.name,
        "raw_idea": project.raw_idea,
        "conversation": project.ai_conversation_history or [],
        "understanding_score": project.understanding_score,
        "current_layer": len([
            m for m in (project.ai_conversation_history or [])
            if m.get("role") == "user"
        ]) + 1,
    }