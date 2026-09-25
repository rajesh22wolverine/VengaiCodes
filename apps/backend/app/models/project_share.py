# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Project Share Link Model
#  models/project_share.py — One row per "download link" a user made
#  for a project (Share via QR → Download link). The link lets anyone who
#  has it download the project's ZIP (code + documents) without signing
#  in, so it is a bearer secret: only a SHA-256 of its token is stored —
#  a copy of this table can't be turned back into working links — and
#  every link expires, and can be turned off early (revoked_at).
# ═══════════════════════════════════════════════════════════════

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class ProjectShareLink(Base):
    __tablename__ = "project_share_links"

    id: str = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    project_id: str = Column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: str = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # hex SHA-256 of the URL token — never the token itself.
    token_hash: str = Column(String(64), nullable=False, unique=True)

    created_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: datetime = Column(DateTime(timezone=True), nullable=False)
    revoked_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)

    download_count: int = Column(Integer, default=0, nullable=False)
    last_downloaded_at: Optional[datetime] = Column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_project_share_links_project", "project_id"),)

    def is_active(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        expires = self.expires_at
        # SQLite hands back naive datetimes (stored as UTC); compare like with like.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return self.revoked_at is None and expires > now

    def __repr__(self) -> str:
        return f"<ProjectShareLink project={self.project_id[:8]}... active={self.is_active()}>"
