# ═══════════════════════════════════════════════════════════════
#  VengaiCode — MSG91 SMS Service
#  services/msg91_service.py — Sends OTP and notification SMS
#  to Indian mobile numbers via MSG91 API
#  Sign up: https://msg91.com (free tier available)
# ═══════════════════════════════════════════════════════════════

import logging

import httpx

from app.config import settings

logger = logging.getLogger("vengaicode.msg91")

MSG91_BASE_URL = "https://control.msg91.com/api/v5"


class MSG91Error(Exception):
    """Raised when MSG91 API call fails."""
    pass


async def send_otp_sms(mobile: str, otp: str) -> bool:
    """
    Send an OTP SMS via MSG91 using their OTP template.

    mobile: Indian mobile number in format +91XXXXXXXXXX
    otp: 6-digit OTP code

    Returns True on success, raises MSG91Error on failure.
    """
    if not settings.MSG91_API_KEY:
        logger.warning(
            "MSG91_API_KEY not configured — OTP SMS not sent. "
            f"[DEV MODE] OTP for {mobile}: {otp}"
        )
        # In development without MSG91 configured, log the OTP so devs
        # can still test the flow. Never do this in production.
        if settings.is_production:
            raise MSG91Error("SMS service not configured")
        return True

    # MSG91 expects mobile without '+' prefix
    clean_mobile = mobile.replace("+", "")

    payload = {
        "template_id": settings.MSG91_TEMPLATE_ID,
        "recipients": [
            {
                "mobiles": clean_mobile,
                "OTP": otp,
            }
        ],
    }

    headers = {
        "authkey": settings.MSG91_API_KEY,
        "Content-Type": "application/json",
        "accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{MSG91_BASE_URL}/otp",
                json=payload,
                headers=headers,
            )

        if response.status_code != 200:
            logger.error(
                f"MSG91 OTP send failed: status={response.status_code} "
                f"body={response.text}"
            )
            raise MSG91Error(f"MSG91 returned status {response.status_code}")

        data = response.json()
        if data.get("type") == "error":
            raise MSG91Error(data.get("message", "Unknown MSG91 error"))

        logger.info(f"OTP SMS sent to {mobile[:6]}***")
        return True

    except httpx.RequestError as e:
        logger.error(f"MSG91 request failed: {e}")
        raise MSG91Error(f"Failed to reach MSG91: {e}")


async def send_notification_sms(mobile: str, message: str) -> bool:
    """
    Send a general notification SMS (not OTP) via MSG91 flow API.

    mobile: Indian mobile number in format +91XXXXXXXXXX
    message: SMS body text
    """
    if not settings.MSG91_API_KEY:
        logger.warning(
            f"MSG91_API_KEY not configured — notification SMS not sent to {mobile}"
        )
        if settings.is_production:
            raise MSG91Error("SMS service not configured")
        return True

    clean_mobile = mobile.replace("+", "")

    payload = {
        "sender": settings.MSG91_SENDER_ID,
        "route": "4",  # Transactional route
        "country": "91",
        "sms": [
            {
                "message": message,
                "to": [clean_mobile],
            }
        ],
    }

    headers = {
        "authkey": settings.MSG91_API_KEY,
        "Content-Type": "application/json",
        "accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{MSG91_BASE_URL}/flow",
                json=payload,
                headers=headers,
            )

        if response.status_code != 200:
            logger.error(
                f"MSG91 notification send failed: status={response.status_code} "
                f"body={response.text}"
            )
            raise MSG91Error(f"MSG91 returned status {response.status_code}")

        logger.info(f"Notification SMS sent to {mobile[:6]}***")
        return True

    except httpx.RequestError as e:
        logger.error(f"MSG91 request failed: {e}")
        raise MSG91Error(f"Failed to reach MSG91: {e}")


async def verify_msg91_config() -> dict:
    """
    Health check — verify MSG91 is configured.
    Used by /health/detailed endpoint.
    """
    if not settings.MSG91_API_KEY:
        return {"configured": False, "message": "MSG91_API_KEY not set"}

    if not settings.MSG91_TEMPLATE_ID:
        return {
            "configured": False,
            "message": "MSG91_TEMPLATE_ID not set — OTP SMS will fail",
        }

    return {"configured": True, "sender_id": settings.MSG91_SENDER_ID}
