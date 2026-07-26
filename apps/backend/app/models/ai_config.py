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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.sql import func

from app.core.database import Base


class UserAIConfig(Base):
    """
    A single saved AI provider configuration owned by a user.
    A user may have several (e.g. one for their Groq key, one for a
    local server); at most one is `is_active` at a time — that's the
    one the orchestrator uses instead of the platform default.
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
    user_id: str = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
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

    is_active: bool = Column(Boolean, default=False, nullable=False)
    # Only one True per user_id — enforced in the API layer, not the DB.

    priority: Optional[str] = Column(String(10), nullable=True)
    # "primary" | "secondary" | "tertiary" | None — an optional fallback
    # order across a user's own configs. At most one config per slot per
    # user_id, enforced in the API layer. When any config has a priority
    # set, orchestrator.generate_text() tries them in order instead of
    # just the single is_active one; when none do, is_active alone still
    # decides which config is used (unchanged legacy behavior).

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
        return (
            f"<UserAIConfig id={self.id[:8]}... user={self.user_id[:8]}... "
            f"provider={self.provider_type} active={self.is_active}>"
        )
