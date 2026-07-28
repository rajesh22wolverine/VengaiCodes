# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Platform Settings Model
#  models/settings.py — Admin-managed key/value platform config
# ═══════════════════════════════════════════════════════════════

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, JSON, String
from sqlalchemy.sql import func

from app.core.database import Base


class PlatformSetting(Base):
    """A single admin-configurable platform setting, keyed by name."""

    __tablename__ = "platform_settings"

    key: str = Column(String(100), primary_key=True)
    value: dict = Column(JSON, default=dict, nullable=False)
    updated_by: Optional[str] = Column(String(36), nullable=True)
    # Admin user ID who last changed this setting
    updated_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<PlatformSetting key={self.key} value={self.value}>"
