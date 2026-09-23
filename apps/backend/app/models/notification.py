# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Notification Database Model
#  models/notification.py — One row per in-app notification. Backs the
#  notification bell already built into apps/desktop's TopBar (and the
#  matching Redux slice on both clients) — that frontend has existed
#  since Sprint 10 pointing at a "Notification model (Sprint 10)" that
#  was never actually created; GET /notifications returned a hardcoded
#  empty list until this model + the real endpoints/emitters that use
#  it (services/notifications.py) were added.
# ═══════════════════════════════════════════════════════════════

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class Notification(Base):
    """
    A single notification for one user. `type` is a free-form string
    (not a DB enum) matching the frontend's AppNotification.type union
    ("info" | "success" | "warning" | "error" | "tiger_stamp" |
    "marketplace" | "admin") — kept as a plain string, same convention
    as GenerationJob.status, so a new category never needs a migration.
    """

    __tablename__ = "notifications"

    id: str = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True
    )

    user_id: str = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    title: str = Column(String(255), nullable=False)
    message: str = Column(Text, nullable=False)
    type: str = Column(String(20), nullable=False, default="info")

    is_read: bool = Column(Boolean, default=False, nullable=False)

    # Optional in-app route the frontend can navigate to on tap/click
    # (e.g. "/project/{id}/codegen") — never a full URL, always relative,
    # same spirit as MarketplaceApp.external_url being the one field
    # that's ever a real external link.
    link: Optional[str] = Column(String(500), nullable=True)

    created_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<Notification user={self.user_id[:8]}... type={self.type} read={self.is_read}>"
