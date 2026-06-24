# ═══════════════════════════════════════════════════════════════
#  VengaiCode — AI Orchestrator
#  ai/orchestrator.py — Ollama (local) first, Groq (cloud) fallback
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
    """Call local Ollama instance."""
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


async def _call_groq(prompt: str) -> tuple[str, float]:
    """Call Groq cloud API."""
    if not settings.GROQ_API_KEY:
        raise AIError("Groq API key not configured")

    model = settings.GROQ_DEFAULT_MODEL
    start = time.perf_counter()

    print(f"[DEBUG] Calling Groq with model={model}, key={settings.GROQ_API_KEY[:10]}...", flush=True)

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.GROQ_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": settings.AI_TEMPERATURE,
                "max_tokens": settings.AI_MAX_TOKENS,
            },
        )

    print(f"[DEBUG] Groq response status: {response.status_code}", flush=True)

    if response.status_code != 200:
        print(f"[DEBUG] Groq error body: {response.text}", flush=True)
        response.raise_for_status()

    data = response.json()
    duration_ms = (time.perf_counter() - start) * 1000
    text = data["choices"][0]["message"]["content"].strip()
    return text, duration_ms


async def generate_text(prompt: str, model: str | None = None) -> dict:
    """
    Generate text using local Ollama first, falling back to Groq cloud.
    """
    # ── Try Ollama first ──
    try:
        text, duration_ms = await _call_ollama(prompt, model)
        return {
            "text": text,
            "source": "ollama",
            "duration_ms": duration_ms,
            "model": model or settings.OLLAMA_CHAT_MODEL,
        }
    except Exception as e:
        print(f"[DEBUG] Ollama failed: {e}", flush=True)
        logger.warning(f"Ollama unavailable: {e} — trying Groq fallback")

    # ── Fallback to Groq ──
    try:
        text, duration_ms = await _call_groq(prompt)
        return {
            "text": text,
            "source": "groq",
            "duration_ms": duration_ms,
            "model": settings.GROQ_DEFAULT_MODEL,
        }
    except AIError:
        raise
    except Exception as e:
        print(f"[DEBUG] Groq failed: {type(e).__name__}: {e}", flush=True)
        logger.error(f"Groq failed: {e}")
        raise AIError(
            "Both local AI (Ollama) and cloud AI (Groq) are unavailable. "
            "Baby Tiger can't think right now! 🐯💭 Please check your "
            "Ollama installation or Groq API key configuration."
        )


async def check_ai_availability() -> dict:
    """Health check — which AI sources are currently reachable."""
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
