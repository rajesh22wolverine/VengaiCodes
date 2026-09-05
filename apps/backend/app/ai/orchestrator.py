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

from app.config import DECOMMISSIONED_GROQ_MODELS, settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.database import AsyncSessionLocal
from app.models.ai_config import UserAIConfig
from app.models.user import User

logger = logging.getLogger("vengaicode.ai")


class AIError(Exception):
    """Raised when both Ollama and Groq fail to respond."""
    pass


class AIQuotaExceededError(AIError):
    """Raised when a user has exhausted their plan's platform AI token
    quota and no BYO/self-hosted config in their bag can serve the
    request instead. Subclasses AIError so every existing
    `except AIError: raise HTTPException(503, str(e))` call site across
    the API already catches and surfaces this correctly."""
    pass


def _quota_exceeded_message(user: User) -> str:
    return (
        "You've used all of your plan's AI tokens for now. Upgrade your "
        "plan, or add your own AI key/self-hosted model in Settings to "
        "keep generating — Baby Tiger needs more fuel! 🐯⛽"
    )


async def _call_ollama(
    prompt: str, model: str | None = None, base_url: str | None = None
) -> tuple[str, float, dict]:
    """Call an Ollama instance — settings.OLLAMA_HOST by default, or a bag
    entry's own base_url (e.g. a platform default pointed at a different
    host)."""
    model = model or settings.OLLAMA_CHAT_MODEL
    host = base_url or settings.OLLAMA_HOST
    start = time.perf_counter()

    async with httpx.AsyncClient(timeout=settings.OLLAMA_TIMEOUT) as client:
        response = await client.post(
            f"{host}/api/generate",
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
    usage = _usage_from_ollama(data)
    return data.get("response", "").strip(), duration_ms, usage


def _usage_from_ollama(data: dict) -> dict:
    """Ollama's /api/generate response echoes prompt_eval_count/eval_count
    (its own names for prompt/completion tokens) in the same JSON body."""
    prompt_tokens = data.get("prompt_eval_count")
    completion_tokens = data.get("eval_count")
    total_tokens = (
        (prompt_tokens or 0) + (completion_tokens or 0)
        if prompt_tokens is not None or completion_tokens is not None
        else None
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _usage_from_openai_style(data: dict) -> dict:
    """Shared by Groq/OpenAI/BYO custom endpoints — the OpenAI-compatible
    `usage` object, when a provider echoes one. A keyless local server that
    omits it legitimately yields all-None here, not zeros — "unknown" and
    "actually zero" must stay distinguishable for quota metering."""
    usage_raw = data.get("usage") or {}
    return {
        "prompt_tokens": usage_raw.get("prompt_tokens"),
        "completion_tokens": usage_raw.get("completion_tokens"),
        "total_tokens": usage_raw.get("total_tokens"),
    }


def _usage_from_anthropic(data: dict) -> dict:
    """Anthropic's Messages API uses input_tokens/output_tokens (different
    key names than the OpenAI-compatible shape) and reports no combined
    total, so it's computed here."""
    usage_raw = data.get("usage") or {}
    input_tokens = usage_raw.get("input_tokens")
    output_tokens = usage_raw.get("output_tokens")
    total_tokens = (
        (input_tokens or 0) + (output_tokens or 0)
        if input_tokens is not None or output_tokens is not None
        else None
    )
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


# Reasoning models spend reasoning tokens from the SAME max_tokens budget
# as the reply. Measured against deepseek/deepseek-v4-pro via OpenRouter on
# a real codegen prompt at max_tokens=6000: completion_tokens=2952, of which
# completion_tokens_details.reasoning_tokens=2782 — leaving ~170 tokens for
# the actual source file. When reasoning happens to consume the whole
# budget the provider returns "content": null, which crashed on .strip()
# and dropped the request through to the next entry in the bag: a paid
# frontier model silently demoted to whatever came next (here, a local 3B).
#
# Scoped to "custom" providers on purpose — see _call_user_ai_config().
# Groq enforces a per-model max_completion_tokens and 400s above it, so the
# named-provider paths keep sending exactly what the caller asked for.
# Headroom is a ceiling, not a reservation: providers bill tokens produced.
REASONING_TOKEN_HEADROOM = 8000


async def _call_openai_compatible(
    base_url: str,
    api_key: Optional[str],
    model: str,
    prompt: str,
    max_tokens: int | None = None,
    timeout: float = 180.0,
    token_headroom: int = 0,
) -> tuple[str, float, dict]:
    """
    Call any OpenAI-compatible /chat/completions endpoint. Shared by Groq,
    OpenAI, and BYO custom endpoints (e.g. a self-hosted llama.cpp server) —
    they all speak the same request/response shape.

    Retries on 429 (rate limited) with backoff — honors the provider's
    Retry-After header when present, since Groq's shared/free tier trips
    this under normal load and a transient rate-limit shouldn't surface
    as a hard failure to the user.

    `token_headroom` is added to max_tokens for endpoints that may spend
    part of the budget on reasoning before answering — see
    REASONING_TOKEN_HEADROOM.
    """
    start = time.perf_counter()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": settings.AI_TEMPERATURE,
        "max_tokens": (max_tokens or settings.AI_MAX_TOKENS) + token_headroom,
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

    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content")

    # A reasoning model that spent the whole budget thinking returns
    # content: null with the reasoning in a separate field. Calling
    # .strip() on that raised an AttributeError which the bag loop caught
    # as a generic "config failed", so the request quietly moved on to the
    # next model instead of reporting a budget problem. Say what happened.
    if content is None or not content.strip():
        usage_raw = data.get("usage") or {}
        reasoning = (usage_raw.get("completion_tokens_details") or {}).get("reasoning_tokens")
        raise AIError(
            f"{model} returned no content "
            f"(finish_reason={choice.get('finish_reason')}, "
            f"completion_tokens={usage_raw.get('completion_tokens')}, "
            f"reasoning_tokens={reasoning}). If reasoning_tokens is close to "
            f"completion_tokens the model spent its whole max_tokens budget "
            f"thinking — raise REASONING_TOKEN_HEADROOM."
        )

    text = content.strip()
    usage = _usage_from_openai_style(data)
    return text, duration_ms, usage


async def _call_groq(prompt: str, max_tokens: int | None = None) -> tuple[str, float, dict]:
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


# Thinking is ON BY DEFAULT on claude-opus-5, claude-sonnet-5 and the
# Fable family, and thinking tokens are spent from the SAME max_tokens
# budget as the reply that follows them. So a caller asking for a
# 6000-token source file (GROQ_FILE_MAX_TOKENS) actually gets a file
# truncated by however much the model thought first — which
# validate_generated_content() then rejects and retries, at double the
# cost, straight into the same truncation. Give the reply its full
# requested budget by adding headroom for the thinking in front of it.
# Anthropic bills tokens actually produced, so headroom that goes
# unused is free — this is a ceiling, not a reservation.
ANTHROPIC_THINKING_HEADROOM = 8000


async def _call_anthropic(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int | None = None,
    timeout: float = 420.0,
) -> tuple[str, float, dict]:
    """
    Call Anthropic's Messages API — a different shape from the OpenAI-
    compatible providers: x-api-key header (not Bearer), /messages path
    (not /chat/completions), and a content[] response array.

    The timeout is much longer than the Groq path's: this is a
    non-streaming request, and a 6000-token file plus the thinking
    ahead of it is minutes of generation on an Opus-class model, not
    seconds.
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
                "max_tokens": (
                    (max_tokens or settings.AI_MAX_TOKENS) + ANTHROPIC_THINKING_HEADROOM
                ),
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    if response.status_code != 200:
        logger.error(f"{base_url} error: {response.status_code} {response.text}")
        response.raise_for_status()

    data = response.json()
    duration_ms = (time.perf_counter() - start) * 1000

    # content[] is not always [text]. Models that think by default
    # (claude-opus-5, claude-sonnet-5, the Fable family) put a thinking
    # block first, so content[0]["text"] raises a KeyError that reaches
    # the user as a generic "your AI config failed" — which reads like a
    # bad API key. Collect every text block instead, and say plainly when
    # there are none (a refusal, or max_tokens hit during thinking).
    text = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ).strip()

    if not text:
        raise AIError(
            f"Anthropic ({model}) returned no text "
            f"(stop_reason={data.get('stop_reason')}). The model may have "
            f"refused the request, or hit its max_tokens cap while thinking."
        )

    usage = _usage_from_anthropic(data)
    return text, duration_ms, usage


async def _call_user_ai_config(
    config: UserAIConfig, prompt: str, max_tokens: int | None = None
) -> tuple[str, float, dict]:
    """Call one bag entry — a platform default (config.user_id is None) or
    a user's own saved BYO config (their key, or their custom endpoint)."""
    if config.provider_type == "ollama":
        return await _call_ollama(prompt, config.model_name, base_url=config.base_url)

    api_key = decrypt_secret(config.api_key_encrypted) if config.api_key_encrypted else None

    if config.provider_type == "anthropic":
        if not api_key:
            raise AIError("Anthropic requires an API key")
        return await _call_anthropic(config.base_url, api_key, config.model_name, prompt, max_tokens)

    # "custom" is where the aggregators and reasoning models live
    # (OpenRouter, DeepSeek, Moonshot, ...), and they bill only what they
    # produce, so the headroom is free when unused. The named providers are
    # left alone: Groq in particular rejects a max_tokens above the model's
    # own max_completion_tokens with a 400.
    headroom = REASONING_TOKEN_HEADROOM if config.provider_type == "custom" else 0
    return await _call_openai_compatible(
        config.base_url,
        api_key,
        config.model_name,
        prompt,
        max_tokens,
        token_headroom=headroom,
    )


def _task_type_ok(config: UserAIConfig, task_type: Optional[str]) -> bool:
    """NULL config.task_type ("untagged") matches every request — the
    state of every UserAIConfig row before task-aware routing existed, so
    filtering is a no-op until someone opts a specific config into a
    bucket. A config explicitly tagged "codegen" or "general" only
    matches a request asking for that same bucket, so a coder fine-tune
    never serves a chat prompt and vice versa."""
    return config.task_type is None or config.task_type == (task_type or "general")


def _leading_own_count(bag: list[UserAIConfig]) -> int:
    """How many entries at the start of `bag` are the user's own configs
    (user_id is not None), before the first platform default. Used as the
    "stop and raise here, don't silently spill into platform defaults"
    boundary — derived from the bag's actual shape rather than from
    whether User.ai_bag_order happens to be set, so a backfilled bag
    order (see backfill_legacy_bag_orders()) still protects a BYO chain
    exactly like the un-backfilled natural order does."""
    count = 0
    for config in bag:
        if config.user_id is None:
            break
        count += 1
    return count


async def get_effective_bag(
    user: User, db: AsyncSession, task_type: Optional[str] = None
) -> tuple[list[UserAIConfig], int]:
    """
    Assemble a user's effective AI model "bag" — platform-wide defaults
    (user_id IS NULL, admin-managed via /admin/ai-configs) plus that
    user's own BYO configs, merged into one ordered list generate_text()
    tries in turn. Returns (bag, own_boundary) — own_boundary is the
    length of the leading run of the user's own configs before the first
    platform default (see _leading_own_count()); generate_text() uses it
    to stop and raise once that run is exhausted instead of silently
    spilling into the platform defaults that follow.

    `task_type` ("codegen" | "general" | None) narrows both the user's
    own configs and the platform defaults to ones tagged for that task,
    or untagged (see _task_type_ok()), before any of the ordering logic
    below runs. Filtering can only narrow the bag, never error — an
    empty result just means generate_text() falls through to its
    hardcoded Ollama-then-Groq safety net, same as an unseeded bag today.

    Natural order (no explicit User.ai_bag_order override):
      1. The user's own configs, in their *legacy* effective order — a
         priority chain (primary/secondary/tertiary) if they set one,
         evaluated across ALL their rows regardless of is_active (exactly
         as before the bag existed — is_active never gated the priority
         chain); else their single is_active config; else nothing. Kept
         bit-for-bit the same as the pre-bag lookup so the existing
         priority dropdown in Settings keeps working unmodified.
      2. Platform defaults (is_active True only), sorted by order_index
         (nulls last) then created_at.

    A user's own configs are tried first — deliberately: a user who set
    up their own key/endpoint chose to route away from the platform
    default, so it shouldn't be demoted behind it.

    If User.ai_bag_order is set (a full personal reorder — not built into
    the UI yet, but usable via PUT /ai/configs/bag-order), it wins
    instead. Any bag member missing from that list (e.g. a platform
    default the admin added after the user last reordered) is appended
    after, in the natural order above, rather than hidden.
    """
    own_result = await db.execute(select(UserAIConfig).where(UserAIConfig.user_id == user.id))
    own = [c for c in own_result.scalars().all() if _task_type_ok(c, task_type)]

    priority_rank = {"primary": 0, "secondary": 1, "tertiary": 2}
    chain = sorted((c for c in own if c.priority), key=lambda c: priority_rank[c.priority])
    own_ordered = chain if chain else [c for c in own if c.is_active][:1]

    platform_result = await db.execute(
        select(UserAIConfig).where(
            UserAIConfig.user_id.is_(None), UserAIConfig.is_active.is_(True)
        )
    )
    platform_defaults = sorted(
        (c for c in platform_result.scalars().all() if _task_type_ok(c, task_type)),
        key=lambda c: (c.order_index is None, c.order_index or 0, c.created_at),
    )

    natural_order = [*own_ordered, *platform_defaults]

    if not user.ai_bag_order:
        return natural_order, _leading_own_count(natural_order)

    by_id = {c.id: c for c in natural_order}
    ordered = [by_id[cid] for cid in user.ai_bag_order if cid in by_id]
    already_placed = {c.id for c in ordered}
    ordered.extend(c for c in natural_order if c.id not in already_placed)
    return ordered, _leading_own_count(ordered)


async def seed_default_ai_configs() -> None:
    """
    One-time, idempotent seed of the platform-default AI bag from env
    config — so the merged bag (see get_effective_bag()) reproduces today's
    hardcoded Ollama-then-Groq fallback out of the box, and both become
    admin-manageable/reorderable via /admin/ai-configs instead of only
    living in settings.py. Additive only: skipped entirely once a
    platform-default row of that provider_type already exists, so it
    never overwrites anything an admin has since edited or removed.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserAIConfig.provider_type, UserAIConfig.base_url).where(
                UserAIConfig.user_id.is_(None)
            )
        )
        existing_rows = result.all()
        existing_types = {row[0] for row in existing_rows}
        existing_base_urls = {row[1] for row in existing_rows}

        # Ollama is a LOCAL inference server. On a cloud host (Render et al)
        # there is nothing listening on OLLAMA_HOST, so seeding it there just
        # puts a guaranteed-dead entry near the front of every user's bag:
        # every AI call would burn its connection timeout before falling
        # through to a provider that actually answers. Skip it in production
        # and let the cloud bag be cloud providers only.
        #
        # Seeding is additive-only, so an Ollama row seeded before this check
        # existed stays put — deactivate it in Admin -> AI Models.
        if settings.is_production and "ollama" not in existing_types:
            logger.info("Skipping Ollama platform default — no local inference server in production")
        elif "ollama" not in existing_types:
            db.add(
                UserAIConfig(
                    user_id=None,
                    provider_type="ollama",
                    base_url=settings.OLLAMA_HOST,
                    model_name=settings.OLLAMA_CHAT_MODEL,
                    label="Platform default (Ollama, local)",
                    is_active=True,
                    order_index=0,
                )
            )
            logger.info("✅ Seeded platform-default Ollama AI config into the bag")

        if "groq" not in existing_types and settings.GROQ_API_KEY:
            db.add(
                UserAIConfig(
                    user_id=None,
                    provider_type="groq",
                    base_url=settings.GROQ_BASE_URL,
                    api_key_encrypted=encrypt_secret(settings.GROQ_API_KEY),
                    model_name=settings.GROQ_DEFAULT_MODEL,
                    label="Platform default (Groq)",
                    is_active=True,
                    order_index=1,
                )
            )
            logger.info("✅ Seeded platform-default Groq AI config into the bag")

        # OpenRouter rides the generic OpenAI-compatible path, so it's
        # seeded as provider_type "custom" — which means the
        # existing_types check the two blocks above use can't identify it
        # (any unrelated "custom" platform row would mask it, and two
        # OpenRouter rows would look identical to it). Key its idempotency
        # on the base_url instead, which is what actually distinguishes it.
        if (
            settings.OPENROUTER_API_KEY
            and settings.OPENROUTER_BASE_URL not in existing_base_urls
        ):
            db.add(
                UserAIConfig(
                    user_id=None,
                    provider_type="custom",
                    base_url=settings.OPENROUTER_BASE_URL,
                    api_key_encrypted=encrypt_secret(settings.OPENROUTER_API_KEY),
                    model_name=settings.OPENROUTER_DEFAULT_MODEL,
                    label="Platform default (OpenRouter)",
                    is_active=True,
                    # Negative on purpose: it sorts ahead of the Ollama (0)
                    # and Groq (1) rows WITHOUT rewriting them, keeping this
                    # function additive-only as documented above. Seeding it
                    # last would seed it dead — get_effective_bag() would put
                    # it behind an Ollama that isn't running in production,
                    # so every call would eat that connection failure first
                    # and the key would rarely be reached. Drag to reorder in
                    # Admin -> AI Models, which renumbers every row from 0.
                    order_index=-1,
                )
            )
            logger.info("✅ Seeded platform-default OpenRouter AI config into the bag")

        await db.commit()


async def retire_decommissioned_groq_models() -> None:
    """
    Repoint platform-default Groq bag rows that are pinned to a model
    Groq has since shut down.

    seed_default_ai_configs() only ever *inserts*, and it skips entirely
    once a platform-default row of that provider_type exists — so once
    the bag has been seeded, the model id lives in the database and
    bumping GROQ_DEFAULT_MODEL in config.py (or in Render's env) changes
    nothing. That is exactly how a live deploy ends up serving 404
    "model_not_found" out of every generation phase: the row still holds
    the id that was current on the day it was seeded.

    Only platform-default rows (user_id IS NULL) are touched. A user's
    own BYO row is their key and their model choice — if they pinned a
    retired model, that config fails and the bag moves on to the next
    entry, which is the intended behaviour; silently rewriting someone
    else's config is not.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserAIConfig).where(
                UserAIConfig.user_id.is_(None),
                UserAIConfig.provider_type == "groq",
                UserAIConfig.model_name.in_(DECOMMISSIONED_GROQ_MODELS.keys()),
            )
        )
        rows = result.scalars().all()

        for config in rows:
            retired = config.model_name
            config.model_name = DECOMMISSIONED_GROQ_MODELS[retired]
            logger.warning(
                f"⚠️  Platform AI config '{config.label}' pointed at "
                f"decommissioned Groq model '{retired}' — repointed to "
                f"'{config.model_name}'"
            )

        if rows:
            await db.commit()


async def backfill_legacy_bag_orders() -> None:
    """
    One-time convenience migration for users who already had their own
    UserAIConfig row(s) — priority chain or single is_active — before the
    bag existed. get_effective_bag()'s *natural* order already reproduces
    their old effective order bit-for-bit on every call without this (it
    recomputes the chain/single-active lookup fresh each time), so this
    isn't required for correctness. What it does buy: once a future
    drag-to-reorder UI reads/writes ai_bag_order, an existing user's first
    visit starts from their historical order instead of an unset field
    that UI would otherwise have to special-case.

    Only touches users who (a) own at least one UserAIConfig row and (b)
    have never set ai_bag_order — never overwrites a real customization.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserAIConfig).where(UserAIConfig.user_id.is_not(None))
        )
        own_by_user: dict[str, list[UserAIConfig]] = {}
        for config in result.scalars().all():
            own_by_user.setdefault(config.user_id, []).append(config)

        if not own_by_user:
            return

        users_result = await db.execute(
            select(User).where(User.id.in_(own_by_user.keys()), User.ai_bag_order.is_(None))
        )
        users = users_result.scalars().all()
        if not users:
            return

        priority_rank = {"primary": 0, "secondary": 1, "tertiary": 2}
        backfilled = 0
        for user in users:
            configs = own_by_user[user.id]
            chain = sorted((c for c in configs if c.priority), key=lambda c: priority_rank[c.priority])
            if chain:
                ordered_ids = [c.id for c in chain]
            else:
                active = [c for c in configs if c.is_active][:1]
                ordered_ids = [c.id for c in active] if active else None

            if ordered_ids:
                user.ai_bag_order = ordered_ids
                backfilled += 1

        if backfilled:
            await db.commit()
            logger.info(f"✅ Backfilled ai_bag_order for {backfilled} user(s) with a pre-bag AI config")


async def generate_text(
    prompt: str,
    model: str | None = None,
    max_tokens: int | None = None,
    user: Optional[User] = None,
    db: Optional[AsyncSession] = None,
    task_type: Optional[str] = None,
) -> dict:
    """
    Generate text by walking the caller's effective AI model "bag" — see
    get_effective_bag(). In natural (uncustomized) order that's the user's
    own config(s) first — a priority chain if they set one, else their
    single is_active config (legacy behavior, unchanged) — then the
    platform defaults (Ollama, then Groq: seeded at startup by
    seed_default_ai_configs(), admin-manageable via /admin/ai-configs).

    A user's own config(s) failing does NOT fall through into the
    platform defaults unless the user has explicitly customized their bag
    order (User.ai_bag_order) to interleave them — by default it raises
    AIError once their own chain is exhausted, same as before the bag
    existed. Silently falling back would spend VengaiCode's own Groq
    quota on a request the user deliberately routed elsewhere, and would
    hide the real problem with their config.

    If the bag is entirely empty (e.g. seeding hasn't run yet), falls
    back to a hardcoded Ollama-then-Groq call as a last-resort safety net.

    `max_tokens` only applies to Groq-shaped calls — Ollama's local
    models are bounded by their own context window, not a per-request
    token cap.

    `task_type` ("codegen" | "general" | None) narrows the bag to configs
    tagged for that task, or untagged ones — see get_effective_bag() and
    UserAIConfig.task_type. None (the default, used by every caller that
    hasn't opted in) behaves exactly as before this parameter existed.

    Platform-default calls (bag_config.user_id is None) are metered
    against `user.ai_tokens_used`/`ai_tokens_limit` — a user's own BYO key
    or self-hosted endpoint is never metered, since VengaiCode isn't
    paying for that inference. See User.has_ai_quota_remaining().
    """
    # ── Walk the effective bag (own config(s), then platform defaults) ──
    if user is not None and db is not None:
        bag, own_boundary = await get_effective_bag(user, db, task_type=task_type)

        if bag:
            errors: list[str] = []
            any_non_quota_failure = False
            for i, bag_config in enumerate(bag):
                is_platform = bag_config.user_id is None

                if is_platform and not user.has_ai_quota_remaining():
                    errors.append(f"{bag_config.label}: platform AI token quota exhausted")
                    if i + 1 == own_boundary:
                        raise AIQuotaExceededError(_quota_exceeded_message(user))
                    continue

                try:
                    text, duration_ms, usage = await _call_user_ai_config(
                        bag_config, prompt, max_tokens
                    )
                    if is_platform and usage.get("total_tokens") is not None:
                        user.ai_tokens_used += usage["total_tokens"]
                        await db.commit()
                    source = "byo" if bag_config.user_id is not None else "platform"
                    return {
                        "text": text,
                        "source": f"{source}:{bag_config.provider_type}",
                        "duration_ms": duration_ms,
                        "model": bag_config.model_name,
                        "usage": usage,
                    }
                except Exception as e:
                    any_non_quota_failure = True
                    logger.warning(
                        f"AI config '{bag_config.label}' failed: {e} — trying next in the bag"
                    )
                    errors.append(f"{bag_config.label}: {e}")

                if i + 1 == own_boundary:
                    # Exhausted the user's own chain without a customized
                    # bag order — stop here rather than silently spending
                    # platform quota (see docstring).
                    raise AIError(
                        "None of your configured AI models responded (tried in order: "
                        f"{', '.join(errors)}). Check they're running and reachable, or switch "
                        "back to VengaiCode's default AI in Settings."
                    )

            if not any_non_quota_failure and errors:
                # Every remaining entry was skipped purely for quota
                # reasons, never a real provider failure — surface the
                # quota message, not the generic "unavailable" one.
                raise AIQuotaExceededError(_quota_exceeded_message(user))

            raise AIError(
                "Both local AI (Ollama) and cloud AI (Groq) are unavailable. "
                "Baby Tiger can't think right now! 🐯💭 Please check your "
                "Ollama installation or Groq API key configuration."
            )

    # ── Try Ollama first ──
    try:
        text, duration_ms, usage = await _call_ollama(prompt, model)
        return {
            "text": text,
            "source": "ollama",
            "duration_ms": duration_ms,
            "model": model or settings.OLLAMA_CHAT_MODEL,
            "usage": usage,
        }
    except Exception as e:
        print(f"[DEBUG] Ollama failed: {e}", flush=True)
        logger.warning(f"Ollama unavailable: {e} — trying Groq fallback")

    # ── Fallback to Groq ──
    try:
        text, duration_ms, usage = await _call_groq(prompt, max_tokens)
        return {
            "text": text,
            "source": "groq",
            "duration_ms": duration_ms,
            "model": settings.GROQ_DEFAULT_MODEL,
            "usage": usage,
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
