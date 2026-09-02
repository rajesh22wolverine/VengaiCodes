# ═══════════════════════════════════════════════════════════════
#  VengaiCode — User AI Config Database Model
#  models/ai_config.py — Per-user "bring your own AI model" settings
#  Lets a user swap VengaiCode's default Ollama/Groq AI for their own
#  key (Groq/OpenAI) or a self-hosted endpoint (e.g. a local llama.cpp
#  server), without touching VengaiCode's own AI billing/quota.
# ═══════════════════════════════════════════════════════════════

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class UserAIConfig(Base):
    """
    A single AI provider configuration — either owned by a user (their own
    BYO key/endpoint) or, when `user_id IS NULL`, a platform-wide default
    that VengaiCode itself manages (via the admin AI Models screen). Both
    kinds live in the same "bag" that `app.ai.orchestrator.get_effective_bag()`
    assembles per user: platform defaults plus that user's own configs,
    orderable together — see User.ai_bag_order for the per-user ordering
    override.
    """
    __tablename__ = "user_ai_configs"
    __table_args__ = (
        Index("ix_user_ai_configs_user_id", "user_id"),
    )

    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )

    # NOTE: index=True intentionally omitted here — it's already covered by
    # the explicit Index() in __table_args__ above. Keeping both causes
    # "index already exists" crashes on SQLite (see User model for the
    # same fix / explanation).
    #
    # NULL means "platform-wide default" — admin-managed, visible to every
    # user's bag. A regular user's own queries filter to `user_id ==
    # user.id`, which already naturally excludes these rows; admin routes
    # filter to `user_id IS NULL`. On Postgres this column was originally
    # NOT NULL — app.main.init_db() relaxes it at startup (see there).
    user_id: Optional[str] = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )

    # "groq" | "openai" | "anthropic" | "custom" | "portable" — all but
    # "anthropic" speak the same OpenAI-compatible /chat/completions
    # request shape, so one generic call path in orchestrator.py serves
    # them. "portable" is a custom endpoint backed by a locally-launched
    # inference engine (e.g. a model found on a USB drive).
    provider_type: str = Column(String(20), nullable=False)

    base_url: str = Column(String(500), nullable=False)
    # Known default per provider_type for groq/openai; user-supplied
    # for "custom" (e.g. http://127.0.0.1:10086/v1 for a local server).

    api_key_encrypted: Optional[str] = Column(String(1000), nullable=True)
    # Encrypted via app.core.crypto.encrypt_secret(). Nullable — local
    # self-hosted servers usually require no key.

    model_name: str = Column(String(255), nullable=False)

    label: str = Column(String(100), nullable=False)
    # User-facing name, e.g. "My local Qwen (USB)"

    is_active: bool = Column(Boolean, default=True, nullable=False)
    # Despite the name (kept as-is to avoid a column rename/migration),
    # this now means "included in the bag" — many rows may be True at
    # once. Toggling it off pauses a config without deleting it.

    order_index: Optional[int] = Column(Integer, nullable=True)
    # Admin-controlled baseline order among platform defaults
    # (user_id IS NULL) only — a user's own rows ignore this and fall
    # back to created_at for their natural (pre-customization) order.
    # See app.ai.orchestrator.get_effective_bag().

    priority: Optional[str] = Column(String(10), nullable=True)
    # Deprecated — superseded by User.ai_bag_order. Left in place
    # (unread/unwritten by new code) rather than dropped, since this
    # codebase has no migration path for dropping columns.

    created_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        user = f"{self.user_id[:8]}..." if self.user_id else "platform-default"
        return (
            f"<UserAIConfig id={self.id[:8]}... user={user} "
            f"provider={self.provider_type} active={self.is_active}>"
        )
