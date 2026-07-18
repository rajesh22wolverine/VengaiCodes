# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Marketplace API Routes
#  api/v1/marketplace.py — Browse and list apps
#
#  First slice: browse + list only, no payments. `price` is stored
#  and returned but nothing charges it yet — see marketplace.py
#  model docstring and the commented-out `payments` router in
#  router.py for what's intentionally deferred.
# ═══════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.marketplace import ListingCategory, ListingStatus, MarketplaceApp
from app.models.user import User

logger = logging.getLogger("vengaicode.marketplace")
router = APIRouter()


# ─── Schemas ───
class CreateListingRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    tagline: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    category: ListingCategory = ListingCategory.OTHER
    tech_stack: list[str] = Field(default_factory=list)
    price: float = Field(default=0.0, ge=0)
    icon_url: Optional[str] = None
    screenshot_urls: list[str] = Field(default_factory=list)
    external_url: Optional[str] = None


class UpdateListingRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    tagline: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, min_length=1)
    category: Optional[ListingCategory] = None
    tech_stack: Optional[list[str]] = None
    price: Optional[float] = Field(None, ge=0)
    icon_url: Optional[str] = None
    screenshot_urls: Optional[list[str]] = None
    external_url: Optional[str] = None
    status: Optional[ListingStatus] = None


def _serialize(listing: MarketplaceApp, seller: Optional[User] = None) -> dict:
    return {
        "id": listing.id,
        "seller_id": listing.seller_id,
        "seller_username": seller.username if seller else None,
        "name": listing.name,
        "tagline": listing.tagline,
        "description": listing.description,
        "category": listing.category.value,
        "tech_stack": listing.tech_stack or [],
        "price": listing.price,
        "icon_url": listing.icon_url,
        "screenshot_urls": listing.screenshot_urls or [],
        "external_url": listing.external_url,
        "status": listing.status.value,
        "view_count": listing.view_count,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
        "updated_at": listing.updated_at.isoformat() if listing.updated_at else None,
        "published_at": listing.published_at.isoformat() if listing.published_at else None,
    }


@router.post("/apps", summary="Create a new marketplace listing (draft)")
async def create_listing(
    payload: CreateListingRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Creates a listing in draft status. Any authenticated user can list —
    full seller verification (User.can_sell()) is gated behind
    seller_verified/revenue_sharing_agreed, which assume a real payments
    flow that isn't built yet. Revisit this gate once payments land.
    """
    listing = MarketplaceApp(
        seller_id=user.id,
        name=payload.name,
        tagline=payload.tagline,
        description=payload.description,
        category=payload.category,
        tech_stack=payload.tech_stack,
        price=payload.price,
        icon_url=payload.icon_url,
        screenshot_urls=payload.screenshot_urls,
        external_url=payload.external_url,
        status=ListingStatus.DRAFT,
    )
    db.add(listing)

    if not user.is_seller:
        user.is_seller = True

    await db.commit()
    await db.refresh(listing)

    return {"success": True, "listing": _serialize(listing, user)}


@router.get("/apps", summary="Browse published marketplace listings")
async def browse_listings(
    category: Optional[ListingCategory] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Public browse — only published listings, newest first."""
    query = select(MarketplaceApp).where(MarketplaceApp.status == ListingStatus.PUBLISHED)

    if category:
        query = query.where(MarketplaceApp.category == category)
    if search:
        like = f"%{search}%"
        query = query.where(
            or_(
                MarketplaceApp.name.ilike(like),
                MarketplaceApp.tagline.ilike(like),
                MarketplaceApp.description.ilike(like),
            )
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    query = (
        query.order_by(MarketplaceApp.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    listings = result.scalars().all()

    seller_ids = {l.seller_id for l in listings}
    sellers_by_id: dict[str, User] = {}
    if seller_ids:
        sellers_result = await db.execute(select(User).where(User.id.in_(seller_ids)))
        sellers_by_id = {u.id: u for u in sellers_result.scalars().all()}

    return {
        "success": True,
        "listings": [_serialize(l, sellers_by_id.get(l.seller_id)) for l in listings],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/apps/mine", summary="Get the current user's own listings (any status)")
async def get_my_listings(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MarketplaceApp)
        .where(MarketplaceApp.seller_id == user.id)
        .order_by(MarketplaceApp.created_at.desc())
    )
    listings = result.scalars().all()
    return {"success": True, "listings": [_serialize(l, user) for l in listings]}


@router.get("/apps/{listing_id}", summary="Get a single listing's details")
async def get_listing(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == listing_id))
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")

    listing.view_count = (listing.view_count or 0) + 1
    await db.commit()
    await db.refresh(listing)

    seller_result = await db.execute(select(User).where(User.id == listing.seller_id))
    seller = seller_result.scalar_one_or_none()

    return {"success": True, "listing": _serialize(listing, seller)}


@router.put("/apps/{listing_id}", summary="Update your own listing")
async def update_listing(
    listing_id: str,
    payload: UpdateListingRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == listing_id))
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")
    if listing.seller_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You don't own this listing."
        )

    updates = payload.model_dump(exclude_unset=True)
    was_published = listing.status == ListingStatus.PUBLISHED

    for field, value in updates.items():
        setattr(listing, field, value)

    if not was_published and listing.status == ListingStatus.PUBLISHED:
        listing.published_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(listing)

    return {"success": True, "listing": _serialize(listing, user)}


@router.delete("/apps/{listing_id}", summary="Delete your own listing")
async def delete_listing(
    listing_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == listing_id))
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")
    if listing.seller_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You don't own this listing."
        )

    await db.delete(listing)
    await db.commit()

    return {"success": True}
