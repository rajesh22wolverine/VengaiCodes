# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Figma Connection Database Model
#  models/figma_connection.py — Per-user Figma personal access token,
#  letting the UI/UX phase import a Figma frame as a page design.
#  Mirrors models/ai_config.py's UserAIConfig shape/conventions.
# ═══════════════════════════════════════════════════════════════

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.sql import func

from app.core.database import Base


class FigmaConnection(Base):
    """
    A user's connected Figma account — one row per user. The token is a
    free Figma "personal access token" the user generates themselves
    (Figma → Settings → Personal access tokens), not an OAuth grant.
    """
    __tablename__ = "figma_connections"

    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )

    user_id: str = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    token_encrypted: str = Column(String(1000), nullable=False)
    # Encrypted via app.core.crypto.encrypt_secret() — same helper used
    # for BYO AI provider keys.

    figma_handle: str = Column(String(255), nullable=False)
    figma_email: Optional[str] = Column(String(255), nullable=True)
    # Both from GET /v1/me at connect time — display only, never used
    # for auth (the token is).

    connected_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<FigmaConnection user={self.user_id[:8]}... handle={self.figma_handle}>"
