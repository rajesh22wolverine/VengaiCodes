# ═══════════════════════════════════════════════════════════════
#  VengaiCode — AI Orchestrator (Minimal Sprint 1 Version)
#  ai/orchestrator.py — Calls Ollama (local) with Groq (cloud) fallback
#
#  This is the seed of the full Smart Parallel Generation engine.
#  For now: one function, one prompt in, one text response out.
#  Proves the local-AI-first / cloud-fallback architecture works.
# ═══════════════════════════════════════════════════════════════

import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger("vengaicode.ai")


class AIError(Exception):
    """Raised when both Ollama and Groq fail to respond."""
    pass


async def _call_ollama(prompt: str, model: str | None = None) -> tuple[str, float]:
    """
    Call local Ollama instance.
    Returns (response_text, duration_ms).
    Raises httpx errors on failure — caller handles fallback.
    """
    model = model or settings.OLLAMA_CHAT_MODEL
    start = time.perf_counter()

    async with httpx.AsyncClient(timeout=settings.OLLAMA_TIMEOUT) as client:
        response = await client.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": settings.AI_TEMPERATURE,
                },
            },
        )
    response.raise_for_status()
    data = response.json()

    duration_ms = (time.perf_counter() - start) * 1000
    return data.get("response", "").strip(), duration_ms


async def _call_groq(prompt: str, model: str | None = None) -> tuple[str, float]:
    """
    Call Groq cloud API (OpenAI-compatible chat completions).
    Returns (response_text, duration_ms).
    Raises httpx errors on failure.
    """
    if not settings.GROQ_API_KEY:
        raise AIError("Groq API key not configured — no fallback available")

    model = model or settings.GROQ_DEFAULT_MODEL
    start = time.perf_counter()

    async with httpx.AsyncClient(timeout=settings.GROQ_TIMEOUT) as client:
        response = await client.post(
            f"{settings.GROQ_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": settings.AI_TEMPERATURE,
                "max_tokens": settings.AI_MAX_TOKENS,
            },
        )
    response.raise_for_status()
    data = response.json()

    duration_ms = (time.perf_counter() - start) * 1000
    text = data["choices"][0]["message"]["content"].strip()
    return text, duration_ms


async def generate_text(prompt: str, model: str | None = None) -> dict:
    """
    Generate text using local Ollama first, falling back to Groq cloud
    if Ollama is unavailable or responds too slowly.

    Returns:
        {
            "text": str,
            "source": "ollama" | "groq",
            "duration_ms": float,
            "model": str,
        }

    Raises AIError if both sources fail.
    """
    # ── Try Ollama first (local, free, private) ──
    try:
        text, duration_ms = await _call_ollama(prompt, model)

        if duration_ms <= settings.AI_CRITICAL_RESPONSE_THRESHOLD_MS:
            return {
                "text": text,
                "source": "ollama",
                "duration_ms": duration_ms,
                "model": model or settings.OLLAMA_CHAT_MODEL,
            }

        logger.warning(
            f"Ollama responded in {duration_ms:.0f}ms "
            f"(over {settings.AI_CRITICAL_RESPONSE_THRESHOLD_MS}ms threshold) "
            f"— trying Groq fallback"
        )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
        logger.warning(f"Ollama unavailable ({e}) — trying Groq fallback")
        text = None

    # ── Fallback to Groq (cloud) ──
    try:
        text, duration_ms = await _call_groq(prompt, model=None)
        return {
            "text": text,
            "source": "groq",
            "duration_ms": duration_ms,
            "model": settings.GROQ_DEFAULT_MODEL,
        }
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
        logger.error(f"Groq also failed: {e}")
        print(f"[DEBUG] Groq error details: {e}", flush=True)
        if hasattr(e, 'response') and e.response is not None:
            print(f"[DEBUG] Groq response body: {e.response.text}", flush=True)
        raise AIError(
            "Both local AI (Ollama) and cloud AI (Groq) are unavailable. "
            "Baby Tiger can't think right now! 🐯💭 Please check your "
            "Ollama installation or Groq API key configuration."
        )
    except AIError:
        # Groq not configured at all, and Ollama already failed above
        raise AIError(
            "Local AI (Ollama) is unavailable and no cloud fallback (Groq) "
            "is configured. Please start Ollama or set GROQ_API_KEY."
        )


async def check_ai_availability() -> dict:
    """
    Health check — which AI sources are currently reachable.
    Used by /health/detailed and the AI status endpoint.
    """
    status_info = {"ollama": False, "groq": False, "ollama_models": []}

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.OLLAMA_HOST}/api/tags")
            if resp.status_code == 200:
                status_info["ollama"] = True
                status_info["ollama_models"] = [
                    m["name"] for m in resp.json().get("models", [])
                ]
    except Exception:
        pass

    status_info["groq"] = bool(settings.GROQ_API_KEY)

    return status_info
