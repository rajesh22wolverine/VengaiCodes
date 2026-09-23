# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Notifications API Routes
#  api/v1/notifications.py — List/read endpoints backing the
#  notification bell already built into both clients. Real rows now
#  (see app/models/notification.py + services/notifications.py) —
#  this used to be a hardcoded-empty placeholder.
# ═══════════════════════════════════════════════════════════════

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.notification import Notification
from app.models.user import User

router = APIRouter()


@router.get(
    "",
    summary="List notifications for current user",
)
async def list_notifications(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Most recent 50 notifications, newest first, plus the unread count."""
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    notifications = result.scalars().all()

    unread_count = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
    ).scalar_one()

    return {
        "success": True,
        "notifications": [
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "type": n.type,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "link": n.link,
            }
            for n in notifications
        ],
        "unread_count": unread_count,
    }


@router.post(
    "/{notification_id}/read",
    summary="Mark a notification as read",
)
async def mark_notification_read(
    notification_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found."
        )

    notification.is_read = True
    await db.commit()

    return {"success": True, "notification_id": notification_id, "is_read": True}
