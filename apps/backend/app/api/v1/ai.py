# ═══════════════════════════════════════════════════════════════
#  VengaiCode — AI API Routes (Minimal Sprint 1 Version)
#  api/v1/ai.py — Proof-of-concept: prompt in, AI text out
#
#  This is the seed of Phase 5's full code generation engine.
#  For now: proves Ollama-first/Groq-fallback works end-to-end,
#  and gives the desktop app something real to call.
# ═══════════════════════════════════════════════════════════════

from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.orchestrator import AIError, check_ai_availability, generate_text
from app.api.v1.auth import get_current_active_user
from app.models.user import User
from app.schemas.ai import AIStatusResponse, AskRequest, AskResponse
from app.schemas.auth import ErrorResponse

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
#  GET /ai/status — check which AI backends are available
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/status",
    response_model=AIStatusResponse,
    summary="Check AI backend availability (Ollama / Groq)",
)
async def ai_status(user: User = Depends(get_current_active_user)):
    """
    Returns whether local Ollama and/or cloud Groq are reachable,
    and which models Ollama currently has installed.

    Desktop app can use this to show "Baby Tiger is using: Local AI 🐯"
    vs "Cloud AI ☁️" in the UI.
    """
    info = await check_ai_availability()
    return AIStatusResponse(**info)


# ═══════════════════════════════════════════════════════════════
#  POST /ai/ask — send a prompt, get a response
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/ask",
    response_model=AskResponse,
    responses={503: {"model": ErrorResponse}},
    summary="Ask Baby Tiger anything — proof of concept for AI engine",
)
async def ask(
    payload: AskRequest,
    user: User = Depends(get_current_active_user),
):
    """
    Send a prompt to the AI engine and get a text response.

    Tries local Ollama first (free, private). Falls back to Groq
    cloud API if Ollama is unavailable or too slow.

    This is intentionally minimal — Sprint 2+ will replace this
    with the full 7-layer question engine, understanding score,
    and Smart Parallel Generation pipeline. This endpoint exists
    to prove the AI plumbing works end-to-end right now.
    """
    try:
        result = await generate_text(payload.prompt)
    except AIError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    return AskResponse(
        text=result["text"],
        source=result["source"],
        model=result["model"],
        duration_ms=result["duration_ms"],
    )
