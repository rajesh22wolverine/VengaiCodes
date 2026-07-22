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


async def _call_groq(prompt: str, max_tokens: int | None = None) -> tuple[str, float]:
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
                "max_tokens": max_tokens or settings.AI_MAX_TOKENS,
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


async def generate_text(prompt: str, model: str | None = None, max_tokens: int | None = None) -> dict:
    """
    Generate text using local Ollama first, falling back to Groq cloud.
    `max_tokens` only applies to the Groq fallback — Ollama's local models
    are bounded by their own context window, not a per-request token cap.
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
        text, duration_ms = await _call_groq(prompt, max_tokens)
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


async def _call_groq_vision(prompt: str, image_base64: str, media_type: str) -> tuple[str, float]:
    """
    Call Groq's vision-capable model with an image + text prompt.
    No Ollama fallback for vision — text generate_text() already falls
    back to Groq, but local Ollama vision models are a separate,
    noticeably weaker capability we're not wiring up here.
    """
    if not settings.GROQ_API_KEY:
        raise AIError("Groq API key not configured")

    model = settings.GROQ_VISION_MODEL
    start = time.perf_counter()

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            f"{settings.GROQ_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{image_base64}"
                                },
                            },
                        ],
                    }
                ],
                "temperature": settings.AI_TEMPERATURE,
                "max_tokens": settings.AI_MAX_TOKENS,
            },
        )

    if response.status_code != 200:
        logger.error(f"Groq vision error: {response.status_code} {response.text}")
        response.raise_for_status()

    data = response.json()
    duration_ms = (time.perf_counter() - start) * 1000
    text = data["choices"][0]["message"]["content"].strip()
    return text, duration_ms


async def generate_vision(prompt: str, image_base64: str, media_type: str = "image/png") -> dict:
    """
    Generate text from a prompt + image using Groq's vision model.
    Unlike generate_text(), this has no local (Ollama) path — kept
    single-provider and simple; revisit if local vision models are
    needed later.
    """
    try:
        text, duration_ms = await _call_groq_vision(prompt, image_base64, media_type)
        return {
            "text": text,
            "source": "groq",
            "duration_ms": duration_ms,
            "model": settings.GROQ_VISION_MODEL,
        }
    except AIError:
        raise
    except Exception as e:
        logger.error(f"Groq vision failed: {e}")
        raise AIError(
            "Baby Tiger couldn't look at your design right now! 🐯👀 "
            "Please check your Groq API key configuration and try again."
        )


async def transcribe_audio(audio_bytes: bytes, filename: str, content_type: str) -> dict:
    """
    Transcribe a voice note using Groq's hosted Whisper model.
    No Ollama fallback — local Whisper isn't wired up here.
    """
    if not settings.GROQ_API_KEY:
        raise AIError("Groq API key not configured")

    try:
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.GROQ_BASE_URL}/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                data={"model": settings.GROQ_WHISPER_MODEL},
                files={"file": (filename, audio_bytes, content_type)},
            )

        if response.status_code != 200:
            logger.error(f"Groq transcription error: {response.status_code} {response.text}")
            response.raise_for_status()

        data = response.json()
        duration_ms = (time.perf_counter() - start) * 1000
        return {
            "text": data.get("text", "").strip(),
            "source": "groq",
            "duration_ms": duration_ms,
            "model": settings.GROQ_WHISPER_MODEL,
        }
    except AIError:
        raise
    except Exception as e:
        logger.error(f"Groq transcription failed: {e}")
        raise AIError(
            "Baby Tiger couldn't hear your voice note! 🐯🎙️ Please check your "
            "Groq API key configuration and try again."
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
