# ═══════════════════════════════════════════════════════════════
#  VengaiCode — AI Schemas (Minimal Sprint 1 Version)
#  schemas/ai.py — Request/response shapes for the AI proof-of-concept
# ═══════════════════════════════════════════════════════════════

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """
    Minimal AI request — send a prompt, get a response.
    This is the seed of the 8-layer question engine (Sprint 2+).
    """
    prompt: str = Field(..., min_length=1, max_length=4000)


class AskResponse(BaseModel):
    """Response from the AI orchestrator."""
    success: bool = True
    text: str
    source: str  # "ollama" | "groq"
    model: str
    duration_ms: float


class AIStatusResponse(BaseModel):
    """AI availability — which backends are reachable right now."""
    success: bool = True
    ollama: bool
    groq: bool
    ollama_models: list[str] = []
