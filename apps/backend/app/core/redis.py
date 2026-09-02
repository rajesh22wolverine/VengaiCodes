# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Redis Core
#  core/redis.py — Async Redis client for caching, OTP storage,
#  rate limiting, and licence verification caching
# ═══════════════════════════════════════════════════════════════

import functools
import json
import logging
import time
from typing import Any, Callable, Optional, TypeVar

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger("vengaicode.redis")

T = TypeVar("T")


# ───────────────────────────────────────────────
#  Redis Client — Singleton
# ───────────────────────────────────────────────
# socket_connect_timeout/socket_timeout matter a lot here: rate_limit_check()
# runs on every single request (RateLimitMiddleware) and is_token_blocklisted()
# on every authenticated one (auth.get_current_user) — with no explicit
# timeout, a Redis that's down (e.g. no local Docker container running in
# dev) makes redis-py fall back to the OS TCP connect timeout, which can be
# several seconds *per call*, on *every* request. 1s is generous for a
# same-host/same-VPC Redis and still fails fast when there's none to find.
_REDIS_SOCKET_TIMEOUT = 1.0


def _build_redis_client() -> aioredis.Redis:
    """
    Build the Redis client.
    Prefers Upstash (production) if configured, falls back to
    local docker-compose Redis (development).
    """
    if settings.UPSTASH_REDIS_URL and settings.UPSTASH_REDIS_TOKEN:
        # Upstash REST-compatible Redis URL — production
        return aioredis.from_url(
            settings.UPSTASH_REDIS_URL,
            password=settings.UPSTASH_REDIS_TOKEN,
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_connect_timeout=_REDIS_SOCKET_TIMEOUT,
            socket_timeout=_REDIS_SOCKET_TIMEOUT,
        )

    # Local development Redis (docker-compose)
    return aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        socket_connect_timeout=_REDIS_SOCKET_TIMEOUT,
        socket_timeout=_REDIS_SOCKET_TIMEOUT,
    )


redis_client: aioredis.Redis = _build_redis_client()


# ───────────────────────────────────────────────
#  Circuit breaker — every helper below already fails open (a Redis outage
#  should never break the app, just degrade caching/rate-limiting/OTP
#  locking), but retrying a doomed connection on every single request still
#  pays the full socket timeout each time. Once a call fails, skip Redis
#  entirely for a cooldown window instead of re-attempting per request.
# ───────────────────────────────────────────────
_REDIS_DOWN_COOLDOWN_SECONDS = 30.0
_redis_unavailable_until = 0.0


def _redis_known_down() -> bool:
    return time.monotonic() < _redis_unavailable_until


def _mark_redis_down(reason: str) -> None:
    global _redis_unavailable_until
    already_down = _redis_known_down()
    _redis_unavailable_until = time.monotonic() + _REDIS_DOWN_COOLDOWN_SECONDS
    if not already_down:
        logger.warning(
            f"Redis unreachable ({reason}) — skipping Redis for the next "
            f"{_REDIS_DOWN_COOLDOWN_SECONDS:.0f}s instead of retrying every call"
        )


async def check_connection() -> bool:
    """
    Real connectivity check for app startup — PING the server and, on
    failure, immediately arm the circuit breaker so the very first request
    doesn't have to pay its own timeout to discover what startup already
    knows. Returns True if Redis answered.
    """
    try:
        await redis_client.ping()
        return True
    except Exception as e:
        _mark_redis_down(str(e))
        return False


def _redis_guarded(default: T) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Wrap a Redis-backed helper so it (a) short-circuits to `default`
    immediately, with no network attempt, while Redis is known down, and
    (b) arms that cooldown itself the first time a call fails — every
    wrapped function keeps its own fail-open default exactly as before,
    this only changes how quickly repeated failures stop costing a full
    socket timeout.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if _redis_known_down():
                return default
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                _mark_redis_down(str(e))
                return default

        return wrapper

    return decorator


# ───────────────────────────────────────────────
#  JSON Helpers — get/set Python objects directly
# ───────────────────────────────────────────────
@_redis_guarded(default=None)
async def cache_get_json(key: str) -> Optional[Any]:
    """Get a JSON value from cache, returns None if missing or invalid."""
    raw = await redis_client.get(key)
    if raw is None:
        return None
    return json.loads(raw)


@_redis_guarded(default=False)
async def cache_set_json(key: str, value: Any, ttl_seconds: int) -> bool:
    """Set a JSON value in cache with TTL. Returns True on success."""
    await redis_client.set(key, json.dumps(value, default=str), ex=ttl_seconds)
    return True


@_redis_guarded(default=False)
async def cache_delete(key: str) -> bool:
    """Delete a key from cache."""
    await redis_client.delete(key)
    return True


# ───────────────────────────────────────────────
#  OTP Storage Helpers
#  Used by otp.py — stores OTP attempt counters and lockouts
# ───────────────────────────────────────────────
def otp_attempts_key(target: str, purpose: str) -> str:
    return f"otp:attempts:{purpose}:{target}"


def otp_resend_lock_key(target: str, purpose: str) -> str:
    return f"otp:resend_lock:{purpose}:{target}"


@_redis_guarded(default=False)
async def is_otp_resend_locked(target: str, purpose: str) -> bool:
    """Check if user must wait before requesting another OTP."""
    key = otp_resend_lock_key(target, purpose)
    return bool(await redis_client.exists(key))  # Redis down — allow resend


@_redis_guarded(default=None)
async def set_otp_resend_lock(target: str, purpose: str, seconds: int = 60) -> None:
    """Lock OTP resend for N seconds (default 60s between resends)."""
    key = otp_resend_lock_key(target, purpose)
    await redis_client.set(key, "1", ex=seconds)  # Redis down — skip lock, no harm


@_redis_guarded(default=1)
async def increment_otp_attempts(target: str, purpose: str, ttl_seconds: int) -> int:
    """Increment and return OTP verification attempt count."""
    key = otp_attempts_key(target, purpose)
    attempts = await redis_client.incr(key)
    if attempts == 1:
        await redis_client.expire(key, ttl_seconds)
    return attempts  # Redis down — treat as first attempt


@_redis_guarded(default=None)
async def reset_otp_attempts(target: str, purpose: str) -> None:
    """Reset OTP attempt counter after successful verification."""
    key = otp_attempts_key(target, purpose)
    await redis_client.delete(key)  # Redis down — nothing to reset


# ───────────────────────────────────────────────
#  Rate Limiting Helpers
#  Used by middleware/rate_limit.py
# ───────────────────────────────────────────────
async def rate_limit_check(
    identifier: str, max_calls: int, period_seconds: int
) -> tuple[bool, int]:
    """
    Sliding-window rate limit check using Redis INCR + EXPIRE.

    Returns (allowed: bool, remaining: int). Fails open — don't block
    requests if Redis is down. Not built on @_redis_guarded like the
    helpers above: its fail-open value is (True, max_calls), and max_calls
    is a per-call argument, not a fixed default the decorator could express.
    """
    if _redis_known_down():
        return True, max_calls

    key = f"ratelimit:{identifier}"
    try:
        current = await redis_client.incr(key)
        if current == 1:
            await redis_client.expire(key, period_seconds)

        if current > max_calls:
            return False, 0

        return True, max_calls - current
    except Exception as e:
        _mark_redis_down(str(e))
        return True, max_calls


# ───────────────────────────────────────────────
#  Session Token Blocklist (for logout)
# ───────────────────────────────────────────────
@_redis_guarded(default=None)
async def blocklist_token(token: str, ttl_seconds: int) -> None:
    await redis_client.set(f"blocklist:{token}", "1", ex=ttl_seconds)
    # Redis down — skip blocklisting, token expires naturally


@_redis_guarded(default=False)
async def is_token_blocklisted(token_jti: str) -> bool:
    return bool(await redis_client.exists(f"blocklist:{token_jti}"))
    # Redis down — treat token as valid, fail open


# ───────────────────────────────────────────────
#  Licence Verification Cache
#  Used by core/licence_engine.py
# ───────────────────────────────────────────────
async def cache_licence_status(licence_key: str, status: dict) -> None:
    """Cache licence verification result to reduce DB load on every app launch."""
    await cache_set_json(
        f"licence:{licence_key}", status, ttl_seconds=settings.CACHE_TTL_LICENCE
    )


async def get_cached_licence_status(licence_key: str) -> Optional[dict]:
    """Get cached licence verification result."""
    return await cache_get_json(f"licence:{licence_key}")
