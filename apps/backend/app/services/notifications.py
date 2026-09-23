# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Notification Creation Helper
#  services/notifications.py — One function every real event that
#  should surface in a user's notification bell calls. Deliberately
#  does NOT commit: every call site already has its own commit at the
#  end of its own transaction (an admin action, a finished generation
#  job), so this just adds the row and lets that commit include it —
#  same pattern AdminAction logging (api/v1/admin.py's _log_action)
#  already uses.
# ═══════════════════════════════════════════════════════════════

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


async def create_notification(
    db: AsyncSession,
    user_id: str,
    title: str,
    message: str,
    type: str = "info",
    link: Optional[str] = None,
) -> Notification:
    notification = Notification(
        user_id=user_id, title=title, message=message, type=type, link=link
    )
    db.add(notification)
    return notification
