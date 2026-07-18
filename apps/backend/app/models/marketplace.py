# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Marketplace Database Model
#  models/marketplace.py — SQLAlchemy ORM model for marketplace listings
#
#  First slice: browse + list only, no payments yet. `price` is stored
#  for display/future use but nothing charges it — Razorpay checkout is
#  a separate follow-up (see commented-out `payments` router in
#  api/v1/router.py). Seller gating is intentionally light here (any
#  authenticated user can list) since User.can_sell()'s full checks
#  (seller_verified, revenue_sharing_agreed) assume a real payments/
#  verification flow that doesn't exist yet.
# ═══════════════════════════════════════════════════════════════

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Column, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text, JSON, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ListingStatus(str, PyEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ListingCategory(str, PyEnum):
    PRODUCTIVITY = "productivity"
    DEVELOPER_TOOLS = "developer_tools"
    BUSINESS = "business"
    EDUCATION = "education"
    GAMES = "games"
    SOCIAL = "social"
    FINANCE = "finance"
    HEALTH = "health"
    OTHER = "other"


class MarketplaceApp(Base):
    """A seller-listed app in the VengaiCode marketplace."""

    __tablename__ = "marketplace_apps"
    __table_args__ = (
        Index("ix_marketplace_apps_seller_id", "seller_id"),
        Index("ix_marketplace_apps_status", "status"),
        Index("ix_marketplace_apps_category", "category"),
        Index("ix_marketplace_apps_created_at", "created_at"),
    )

    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )

    seller_id: str = Column(String(36), ForeignKey("users.id"), nullable=False)

    name: str = Column(String(255), nullable=False)
    tagline: str = Column(String(255), nullable=False)
    description: str = Column(Text, nullable=False)

    category: ListingCategory = Column(
        Enum(ListingCategory), default=ListingCategory.OTHER, nullable=False
    )
    tech_stack: list = Column(JSON, default=list, nullable=False)
    # ["React", "FastAPI", "PostgreSQL", ...]

    # 0 = free listing. Not charged anywhere yet — display-only until
    # checkout/payments is built.
    price: float = Column(Float, default=0.0, nullable=False)

    icon_url: Optional[str] = Column(String(1000), nullable=True)
    screenshot_urls: list = Column(JSON, default=list, nullable=False)
    external_url: Optional[str] = Column(String(1000), nullable=True)
    # Link to the live app, demo, or repo — these are general app
    # listings, not necessarily VengaiCode-generated projects.

    status: ListingStatus = Column(
        Enum(ListingStatus), default=ListingStatus.DRAFT, nullable=False
    )
    view_count: int = Column(Integer, default=0, nullable=False)

    created_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    published_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)

    # ── Relationships ──
    seller = relationship("User", back_populates="marketplace_apps")

    def __repr__(self) -> str:
        return f"<MarketplaceApp id={self.id[:8]}... name={self.name} status={self.status}>"
