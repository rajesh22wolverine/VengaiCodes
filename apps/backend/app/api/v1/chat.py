# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Chat API Routes
#  api/v1/chat.py — One continuous chat thread per project, available
#  on every phase screen. Handles both general Q&A and requirement
#  change requests.
#
#  On a requirement_change message: merges the AI's updated FRD into
#  requirements_data, unapprove requirements + wipe phases_completed,
#  and reset current_phase back to REQUIREMENTS. The frontend then
#  hard-navigates the user back to the Requirements screen — see
#  ChatPanel.tsx's handling of `redirect_to`.
# ═══════════════════════════════════════════════════════════════

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIError, generate_text
from app.api.v1.auth import get_current_active_user
from app.api.v1.requirements import RequirementsDocument, parse_ai_json
from app.core.database import get_db
from app.models.project import Project, SDLCPhase
from app.models.user import User

logger = logging.getLogger("vengaicode.chat")
router = APIRouter()

MAX_HISTORY_MESSAGES = 8


# ─── Schemas ───
class SendMessageRequest(BaseModel):
    message: str
    phase: str


def build_chat_prompt(phase: str, frd: dict, history: list, message: str) -> str:
    history_text = ""
    for msg in history[-MAX_HISTORY_MESSAGES:]:
        speaker = "User" if msg["role"] == "user" else "Baby Tiger"
        history_text += f"{speaker}: {msg['content']}\n"

    return f"""You are Baby Tiger 🐯, VengaiCode's AI assistant. You appear in a chat \
panel available on every phase of building this app, so the user can ask questions \
or ask to change their requirements at any point — even after later phases (design, \
architecture, code, tests) were already built from the original requirements.

The user is currently on the "{phase}" phase.

Current approved requirements (FRD):
{json.dumps(frd, indent=2)}

Recent conversation:
{history_text or "(none yet)"}

User's new message: "{message}"

Decide ONE of two things:
1. QUESTION — the user is just asking something or commenting (e.g. "why did you \
pick this tech stack?", "how long will this take?"). Just reply conversationally.
2. REQUIREMENT_CHANGE — the user wants to add, remove, or change something about \
what the app should DO (a feature, a platform, target users, monetization, etc.), \
not just about the current phase's output.

If it's a REQUIREMENT_CHANGE, produce the FULL updated FRD — keep every field the \
same except what the user's message actually asked to change.

Respond with ONLY this JSON, no markdown, no extra text:
{{
  "intent": "question" or "requirement_change",
  "reply": "a short, friendly reply to show the user (1-3 sentences). If it's a \
requirement_change, mention that you're sending them back to Requirements to \
review the update.",
  "updated_requirements": null, or if requirement_change, the FULL FRD object with \
EXACTLY these fields: {{
    "overview": "...", "problem_statement": "...", "target_users": "...",
    "key_features": ["..."], "platforms": ["..."], "monetization": "...",
    "reference_apps": ["..."], "user_stories": ["..."], "tech_recommendations": "..."
  }}
}}"""


async def _get_owned_project(db: AsyncSession, project_id: str, user: User) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


@router.get("/{project_id}/messages", summary="Get the project's chat history")
async def get_messages(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    return {"success": True, "messages": project.chat_messages or []}


@router.post("/{project_id}/message", summary="Send a chat message")
async def send_message(
    project_id: str,
    payload: SendMessageRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)

    if not project.requirements_data or not project.requirements_data.get("frd"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chat needs an initial requirements document first — finish the wizard.",
        )

    messages = list(project.chat_messages or [])
    now = datetime.now(timezone.utc).isoformat()

    user_message = {
        "id": uuid.uuid4().hex,
        "phase": payload.phase,
        "role": "user",
        "content": payload.message,
        "intent": None,
        "created_at": now,
    }
    messages.append(user_message)

    frd = project.requirements_data["frd"]
    prompt = build_chat_prompt(payload.phase, frd, messages[:-1], payload.message)

    try:
        ai_result = await generate_text(prompt)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse chat response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger got confused there. Please try rephrasing! 🐯",
        )

    intent = parsed.get("intent", "question")
    reply_text = parsed.get("reply", "")
    redirect_to = None

    if intent == "requirement_change" and parsed.get("updated_requirements"):
        try:
            updated_frd = RequirementsDocument(**parsed["updated_requirements"])
        except Exception as e:
            logger.error(f"AI returned an invalid updated FRD: {e}")
            intent = "question"
            reply_text = reply_text or (
                "I tried to update your requirements but something went wrong — "
                "could you try rephrasing the change?"
            )
        else:
            project.requirements_data = {
                "frd": updated_frd.model_dump(),
                "user_approved": False,
                "generated_at": now,
            }
            # Downstream phases were built on the now-outdated requirements —
            # they need to be redone once the user re-approves requirements.
            project.phases_completed = []
            project.current_phase = SDLCPhase.REQUIREMENTS
            project.progress_percent = project.get_progress_percent()
            redirect_to = f"/project/{project_id}/requirements"

    assistant_message = {
        "id": uuid.uuid4().hex,
        "phase": payload.phase,
        "role": "assistant",
        "content": reply_text,
        "intent": intent,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    messages.append(assistant_message)
    project.chat_messages = messages

    await db.commit()

    return {
        "success": True,
        "message": assistant_message,
        "intent": intent,
        "requirements_updated": redirect_to is not None,
        "redirect_to": redirect_to,
    }
