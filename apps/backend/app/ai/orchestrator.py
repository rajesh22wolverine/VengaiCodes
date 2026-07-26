# ═══════════════════════════════════════════════════════════════
#  VengaiCode — AI Orchestrator
#  ai/orchestrator.py — Ollama (local) first, Groq (cloud) fallback
# ═══════════════════════════════════════════════════════════════

import asyncio
import logging
import time
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.crypto import decrypt_secret
from app.models.ai_config import UserAIConfig
from app.models.user import User

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


async def _call_openai_compatible(
    base_url: str,
    api_key: Optional[str],
    model: str,
    prompt: str,
    max_tokens: int | None = None,
    timeout: float = 60.0,
) -> tuple[str, float]:
    """
    Call any OpenAI-compatible /chat/completions endpoint. Shared by Groq,
    OpenAI, and BYO custom endpoints (e.g. a self-hosted llama.cpp server) —
    they all speak the same request/response shape.

    Retries on 429 (rate limited) with backoff — honors the provider's
    Retry-After header when present, since Groq's shared/free tier trips
    this under normal load and a transient rate-limit shouldn't surface
    as a hard failure to the user.
    """
    start = time.perf_counter()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": settings.AI_TEMPERATURE,
        "max_tokens": max_tokens or settings.AI_MAX_TOKENS,
    }

    max_attempts = 3
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(1, max_attempts + 1):
            response = await client.post(
                f"{base_url}/chat/completions", headers=headers, json=payload
            )

            if response.status_code != 429 or attempt == max_attempts:
                break

            try:
                delay = min(float(response.headers.get("retry-after", "")), 10.0)
            except ValueError:
                delay = attempt * 1.5
            logger.warning(
                f"{base_url} rate limited (429) — retrying in {delay:.1f}s "
                f"(attempt {attempt}/{max_attempts})"
            )
            await asyncio.sleep(delay)

    if response.status_code != 200:
        logger.error(f"{base_url} error: {response.status_code} {response.text}")
        response.raise_for_status()

    data = response.json()
    duration_ms = (time.perf_counter() - start) * 1000
    text = data["choices"][0]["message"]["content"].strip()
    return text, duration_ms


async def _call_groq(prompt: str, max_tokens: int | None = None) -> tuple[str, float]:
    """Call Groq cloud API using VengaiCode's own key."""
    if not settings.GROQ_API_KEY:
        raise AIError("Groq API key not configured")

    return await _call_openai_compatible(
        settings.GROQ_BASE_URL,
        settings.GROQ_API_KEY,
        settings.GROQ_DEFAULT_MODEL,
        prompt,
        max_tokens,
        timeout=settings.GROQ_TIMEOUT,
    )


async def _call_anthropic(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int | None = None,
    timeout: float = 60.0,
) -> tuple[str, float]:
    """
    Call Anthropic's Messages API — a different shape from the OpenAI-
    compatible providers: x-api-key header (not Bearer), /messages path
    (not /chat/completions), and a content[] response array.
    """
    start = time.perf_counter()

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens or settings.AI_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    if response.status_code != 200:
        logger.error(f"{base_url} error: {response.status_code} {response.text}")
        response.raise_for_status()

    data = response.json()
    duration_ms = (time.perf_counter() - start) * 1000
    text = data["content"][0]["text"].strip()
    return text, duration_ms


async def _call_user_ai_config(config: UserAIConfig, prompt: str, max_tokens: int | None = None) -> tuple[str, float]:
    """Call a user's own saved BYO AI config (their key, or their custom endpoint)."""
    api_key = decrypt_secret(config.api_key_encrypted) if config.api_key_encrypted else None

    if config.provider_type == "anthropic":
        if not api_key:
            raise AIError("Anthropic requires an API key")
        return await _call_anthropic(config.base_url, api_key, config.model_name, prompt, max_tokens)

    return await _call_openai_compatible(config.base_url, api_key, config.model_name, prompt, max_tokens)


async def generate_text(
    prompt: str,
    model: str | None = None,
    max_tokens: int | None = None,
    user: Optional[User] = None,
    db: Optional[AsyncSession] = None,
) -> dict:
    """
    Generate text using local Ollama first, falling back to Groq cloud —
    unless `user` has their own AI config(s), in which case those are
    used exclusively instead of the platform default.

    If the user has assigned a priority (primary/secondary/tertiary) to
    any of their configs, they're tried in that order, falling through
    to the next on failure. If none have a priority set, the single
    `is_active` config is used instead (legacy behavior, unchanged).

    Either way, a BYO config never falls back to the platform Ollama/Groq
    path on failure — it raises AIError directly once the chain (or the
    single active config) is exhausted. Silently falling back would spend
    VengaiCode's own Groq quota on a request the user deliberately routed
    elsewhere, and would hide the real problem with their config.

    `max_tokens` only applies to the Groq fallback — Ollama's local models
    are bounded by their own context window, not a per-request token cap.
    """
    # ── Use the user's own AI config(s), if they have any ──
    if user is not None and db is not None:
        result = await db.execute(
            select(UserAIConfig).where(
                UserAIConfig.user_id == user.id, UserAIConfig.priority.is_not(None)
            )
        )
        priority_rank = {"primary": 0, "secondary": 1, "tertiary": 2}
        chain = sorted(result.scalars().all(), key=lambda c: priority_rank[c.priority])

        if chain:
            errors: list[str] = []
            for byo_config in chain:
                try:
                    text, duration_ms = await _call_user_ai_config(byo_config, prompt, max_tokens)
                    return {
                        "text": text,
                        "source": f"byo:{byo_config.provider_type}",
                        "duration_ms": duration_ms,
                        "model": byo_config.model_name,
                    }
                except Exception as e:
                    logger.warning(
                        f"BYO AI config '{byo_config.label}' ({byo_config.priority}) failed: {e} "
                        "— trying next in the fallback chain"
                    )
                    errors.append(f"{byo_config.label}: {e}")
            raise AIError(
                "None of your configured AI models responded (tried in order: "
                f"{', '.join(errors)}). Check they're running and reachable, or switch "
                "back to VengaiCode's default AI in Settings."
            )

        # No fallback chain set up — fall back to the legacy single-active lookup.
        result = await db.execute(
            select(UserAIConfig).where(
                UserAIConfig.user_id == user.id, UserAIConfig.is_active.is_(True)
            )
        )
        byo_config = result.scalar_one_or_none()
        if byo_config is not None:
            try:
                text, duration_ms = await _call_user_ai_config(byo_config, prompt, max_tokens)
                return {
                    "text": text,
                    "source": f"byo:{byo_config.provider_type}",
                    "duration_ms": duration_ms,
                    "model": byo_config.model_name,
                }
            except Exception as e:
                logger.error(f"BYO AI config '{byo_config.label}' failed: {e}")
                raise AIError(
                    f"Your configured AI model ('{byo_config.label}') didn't respond: {e}. "
                    "Check it's running and reachable, or switch back to VengaiCode's default AI in Settings."
                )

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
                # qwen/qwen3.6-27b is a reasoning-capable model — without
                # this, its <think>...</think> preamble lands in `content`
                # ahead of the JSON we expect, breaking parse_ai_json().
                "reasoning_format": "hidden",
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
