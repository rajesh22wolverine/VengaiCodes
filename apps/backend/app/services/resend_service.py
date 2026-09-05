# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Resend Email Service
#  services/resend_service.py — Sends transactional email via Resend.
#  Sign up: https://resend.com (free tier available)
#
#  DELIBERATELY LIMITED: delivery is allowlisted to settings.ADMIN_EMAIL.
#  /auth/forgot-password previously only print()ed the OTP, so nobody
#  could actually reset a password — and in production that printed
#  every reset code into the host's logs in plaintext next to the
#  account's email address. This restores real delivery for the admin
#  account (so the operator can always get back in) without switching
#  on email for the whole user base, which needs a verified sending
#  domain, bounce handling and unsubscribe plumbing first.
#
#  To open it up to everyone later, drop the _is_allowed_recipient()
#  check in send_password_reset_email() — nothing else is admin-specific.
# ═══════════════════════════════════════════════════════════════

import logging

import httpx

from app.config import settings

logger = logging.getLogger("vengaicode.resend")

RESEND_BASE_URL = "https://api.resend.com"


class ResendError(Exception):
    """Raised when the Resend API call fails."""
    pass


def _is_allowed_recipient(email: str) -> bool:
    """Only the configured admin address receives real email for now.

    Compared case-insensitively: addresses are stored as the user typed
    them at signup, so an admin who registered "Rajesh@..." must still
    match an ADMIN_EMAIL of "rajesh@...".
    """
    allowed = (settings.ADMIN_EMAIL or "").strip().lower()
    return bool(allowed) and email.strip().lower() == allowed


async def send_password_reset_email(to_email: str, otp: str) -> bool:
    """
    Email a password-reset OTP. Returns True when a message was actually
    handed to Resend, False when delivery was skipped.

    Skipping is normal and not an error: a non-admin recipient, or no
    RESEND_API_KEY configured. The caller must not change its response
    based on the result — /auth/forgot-password answers identically
    whether or not the account exists, and leaking "we sent you mail"
    would undo that.
    """
    if not _is_allowed_recipient(to_email):
        # Unchanged behaviour for regular users: no email goes out. The
        # OTP row still exists, so a reset is possible if the code is
        # delivered another way.
        logger.info("Password reset requested for a non-admin address — email skipped")
        return False

    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured — password reset email not sent")
        if not settings.is_production:
            # Local dev convenience only. Never in production: this is a
            # live credential and host logs are widely readable.
            logger.warning(f"[DEV MODE] Password reset OTP for {to_email}: {otp}")
        return False

    payload = {
        "from": settings.EMAIL_FROM,
        "to": [to_email],
        "subject": "Your VengaiCode password reset code",
        "text": (
            f"Your VengaiCode password reset code is: {otp}\n\n"
            "It expires shortly and can be used once.\n\n"
            "If you did not request a password reset, ignore this email "
            "and your password will stay unchanged."
        ),
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{RESEND_BASE_URL}/emails",
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as e:
        # Never surface this to the caller: /auth/forgot-password must
        # stay indistinguishable for existing and non-existing accounts.
        logger.error(f"Resend request failed: {e}")
        return False

    if response.status_code >= 400:
        # 403 here almost always means EMAIL_FROM's domain is not
        # verified in Resend. Until it is, only resend.dev test
        # addresses can be sent from.
        logger.error(
            f"Resend rejected the password reset email: "
            f"{response.status_code} {response.text[:300]}"
        )
        return False

    logger.info("Password reset email sent to the admin address")
    return True
