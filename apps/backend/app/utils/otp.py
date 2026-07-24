# ═══════════════════════════════════════════════════════════════
#  VengaiCode — OTP Utilities
#  utils/otp.py — Generate, hash, store, and verify OTP codes
#  Uses PyOTP for generation, Redis for attempt tracking
# ═══════════════════════════════════════════════════════════════

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.redis import (
    increment_otp_attempts,
    is_otp_resend_locked,
    reset_otp_attempts,
    set_otp_resend_lock,
)
from app.models.user import OTPRecord

logger = logging.getLogger("vengaicode.otp")


# ───────────────────────────────────────────────
#  OTP Generation
# ───────────────────────────────────────────────
def generate_otp() -> str:
    """Generate a 6-digit numeric OTP using PyOTP's random secret."""
    # Use a fresh random secret each time -> truly random 6-digit code
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret, digits=6, interval=settings.MSG91_OTP_EXPIRE_MINUTES * 60)
    return totp.now()


def hash_otp(otp: str) -> str:
    """Hash an OTP for storage — never store plain OTP codes."""
    return hashlib.sha256(otp.encode()).hexdigest()


def verify_otp_hash(otp: str, otp_hash: str) -> bool:
    """Verify a plain OTP against its stored hash."""
    return hash_otp(otp) == otp_hash


# ───────────────────────────────────────────────
#  Create & Store OTP Record
# ───────────────────────────────────────────────
async def create_otp_record(
    db: AsyncSession,
    target: str,
    otp_type: str,
    purpose: str,
    user_id: Optional[str] = None,
) -> Tuple[str, OTPRecord]:
    """
    Generate a new OTP, hash it, and store the record in the database.

    Returns (plain_otp, otp_record) — plain_otp is sent to user via
    SMS/email, never stored.

    Raises ValueError if resend is rate-limited.
    """
    # Check resend lock — prevents spam
    if await is_otp_resend_locked(target, purpose):
        raise ValueError(
            "Please wait before requesting another OTP. "
            "You can request a new one in a moment."
        )

    plain_otp = generate_otp()
    otp_hash = hash_otp(plain_otp)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.MSG91_OTP_EXPIRE_MINUTES
    )

    # Invalidate any previous unused OTPs for this target+purpose
    result = await db.execute(
        select(OTPRecord).where(
            OTPRecord.target == target,
            OTPRecord.purpose == purpose,
            OTPRecord.is_used == False,  # noqa: E712
        )
    )
    for old_record in result.scalars().all():
        old_record.is_used = True

    otp_record = OTPRecord(
        target=target,
        otp_type=otp_type,
        otp_hash=otp_hash,
        purpose=purpose,
        max_attempts=3,
        expires_at=expires_at,
        user_id=user_id,
    )
    db.add(otp_record)
    await db.commit()
    await db.refresh(otp_record)

    # Lock resend for 60 seconds
    await set_otp_resend_lock(target, purpose, seconds=60)

    return plain_otp, otp_record


# ───────────────────────────────────────────────
#  Verify OTP
# ───────────────────────────────────────────────
async def verify_otp_code(
    db: AsyncSession,
    target: str,
    otp: str,
    purpose: str,
) -> Tuple[bool, str]:
    """
    Verify an OTP code against the latest unused record for target+purpose.

    Returns (success: bool, message: str).
    """
    result = await db.execute(
        select(OTPRecord)
        .where(
            OTPRecord.target == target,
            OTPRecord.purpose == purpose,
            OTPRecord.is_used == False,  # noqa: E712
        )
        .order_by(OTPRecord.created_at.desc())
        .limit(1)
    )
    otp_record = result.scalar_one_or_none()

    if otp_record is None:
        return False, "No OTP request found. Please request a new OTP."

    if otp_record.is_expired():
        return False, "This OTP has expired. Please request a new one."

    if otp_record.is_exhausted():
        return False, "Too many incorrect attempts. Please request a new OTP."

    # Track attempts in Redis (fast) and DB (durable) — DB's otp_record.attempts
    # below is what remaining-attempts logic actually reads.
    await increment_otp_attempts(
        target, purpose, ttl_seconds=settings.MSG91_OTP_EXPIRE_MINUTES * 60
    )
    otp_record.attempts += 1

    if not verify_otp_hash(otp, otp_record.otp_hash):
        await db.commit()
        remaining = otp_record.max_attempts - otp_record.attempts
        if remaining <= 0:
            return False, "Too many incorrect attempts. Please request a new OTP."
        return False, f"Incorrect OTP. {remaining} attempt(s) remaining."

    # Success
    otp_record.is_used = True
    otp_record.used_at = datetime.now(timezone.utc)
    await db.commit()

    await reset_otp_attempts(target, purpose)

    return True, "OTP verified successfully! 🐯"
