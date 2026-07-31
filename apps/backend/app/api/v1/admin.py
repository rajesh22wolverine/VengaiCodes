# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Admin API Routes
#  api/v1/admin.py — User moderation, marketplace moderation,
#  audit log, and platform settings. Every route requires an
#  is_admin=True account (see require_admin in auth.py).
#
#  Disputes, Revenue, and Licences are intentionally NOT here yet —
#  there's no Transaction/Purchase model anywhere in the backend
#  (Razorpay is configured but never wired up), so those sections
#  have no real data to manage until a payments system exists.
# ═══════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_admin
from app.core.database import get_db
from app.models.marketplace import ListingCategory, ListingStatus, MarketplaceApp
from app.models.project import Project
from app.models.settings import PlatformSetting
from app.models.user import (
    AdminAction,
    RestrictionLevel,
    User,
    UserStatus,
    UserTier,
)
from app.schemas.auth import UserResponse

logger = logging.getLogger("vengaicode.admin")
router = APIRouter()


# ─── Helpers ───
def _jsonable(value):
    if value is None:
        return None
    if hasattr(value, "value"):  # enum
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _user_snapshot(user: User) -> dict:
    return {
        "status": _jsonable(user.status),
        "tier": _jsonable(user.tier),
        "is_admin": user.is_admin,
        "restriction_level": _jsonable(user.restriction_level),
        "restriction_reason": user.restriction_reason,
        "is_vip": user.is_vip,
        "is_free_extended": user.is_free_extended,
        "free_extended_until": _jsonable(user.free_extended_until),
    }


def _serialize_project(project: Project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "status": _jsonable(project.status),
        "current_phase": _jsonable(project.current_phase),
        "progress_percent": project.progress_percent,
        "category": _jsonable(project.category),
        "platforms": project.platforms,
        "is_published": project.is_published,
        "created_at": _jsonable(project.created_at),
        "updated_at": _jsonable(project.updated_at),
        "completed_at": _jsonable(project.completed_at),
    }


def _serialize_listing(listing: MarketplaceApp, seller: Optional[User] = None) -> dict:
    return {
        "id": listing.id,
        "seller_id": listing.seller_id,
        "seller_username": seller.username if seller else None,
        "name": listing.name,
        "tagline": listing.tagline,
        "category": listing.category.value,
        "price": listing.price,
        "status": listing.status.value,
        "is_featured": listing.is_featured,
        "view_count": listing.view_count,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
        "published_at": listing.published_at.isoformat() if listing.published_at else None,
    }


async def _log_action(
    db: AsyncSession,
    admin: User,
    request: Request,
    target_user_id: str,
    action_type: str,
    action_details: dict,
    reason: str,
    previous_state: dict,
    new_state: dict,
) -> None:
    db.add(
        AdminAction(
            admin_id=admin.id,
            target_user_id=target_user_id,
            action_type=action_type,
            action_details={k: _jsonable(v) for k, v in action_details.items()},
            reason=reason,
            previous_state=previous_state,
            new_state=new_state,
            ip_address=request.client.host if request.client else None,
        )
    )


# ═══════════════════════════════════════════════════════════════
#  Users
# ═══════════════════════════════════════════════════════════════
@router.get("/users", summary="List/search users")
async def list_users(
    search: Optional[str] = Query(None, max_length=200),
    status_filter: Optional[UserStatus] = Query(None, alias="status"),
    tier: Optional[UserTier] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).where(User.deleted_at.is_(None))

    if search:
        like = f"%{search}%"
        query = query.where(
            or_(
                User.username.ilike(like),
                User.email.ilike(like),
                User.full_name.ilike(like),
            )
        )
    if status_filter:
        query = query.where(User.status == status_filter)
    if tier:
        query = query.where(User.tier == tier)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    query = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    users = result.scalars().all()

    project_counts: dict[str, int] = {}
    if users:
        user_ids = [u.id for u in users]
        counts_result = await db.execute(
            select(Project.user_id, func.count())
            .where(Project.user_id.in_(user_ids), Project.deleted_at.is_(None))
            .group_by(Project.user_id)
        )
        project_counts = dict(counts_result.all())

    return {
        "success": True,
        "users": [
            {**UserResponse.from_db(u).model_dump(), "projects_count": project_counts.get(u.id, 0)}
            for u in users
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/users/{user_id}", summary="Get a single user's full detail")
async def get_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    actions_result = await db.execute(
        select(AdminAction)
        .where(AdminAction.target_user_id == user_id)
        .order_by(AdminAction.created_at.desc())
        .limit(20)
    )
    recent_actions = [
        {
            "id": a.id,
            "admin_id": a.admin_id,
            "action_type": a.action_type,
            "reason": a.reason,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in actions_result.scalars().all()
    ]

    projects_result = await db.execute(
        select(Project)
        .where(Project.user_id == user_id, Project.deleted_at.is_(None))
        .order_by(Project.created_at.desc())
    )
    projects = [_serialize_project(p) for p in projects_result.scalars().all()]

    return {
        "success": True,
        "user": UserResponse.from_db(user).model_dump(),
        "recent_actions": recent_actions,
        "projects": projects,
    }


class AdminUserUpdateRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)
    status: Optional[UserStatus] = None
    restriction_level: Optional[RestrictionLevel] = None
    restriction_reason: Optional[str] = Field(None, max_length=2000)
    tier: Optional[UserTier] = None
    is_vip: Optional[bool] = None
    is_free_extended: Optional[bool] = None
    free_extended_until: Optional[datetime] = None


_STATUS_ACTION_MAP = {
    UserStatus.BANNED: "ban",
    UserStatus.SUSPENDED: "suspend",
    UserStatus.ACTIVE: "unsuspend",
    UserStatus.WARNED: "warn",
    UserStatus.PENDING_VERIFICATION: "status_change",
}


@router.patch("/users/{user_id}", summary="Update a user's status/tier/restrictions/VIP")
async def admin_update_user(
    user_id: str,
    payload: AdminUserUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Every mutation here is written to admin_actions for accountability."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    updates = payload.model_dump(exclude_unset=True, exclude={"reason"})
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update.")

    previous_state = _user_snapshot(user)
    action_types: list[str] = []

    if "status" in updates:
        action_types.append(_STATUS_ACTION_MAP.get(updates["status"], "status_change"))
    if "tier" in updates:
        action_types.append("upgrade_tier")
    if "is_vip" in updates:
        action_types.append("vip_grant" if updates["is_vip"] else "vip_revoke")
        user.vip_granted_by = admin.id if updates["is_vip"] else user.vip_granted_by
        user.vip_granted_at = (
            datetime.now(timezone.utc) if updates["is_vip"] else user.vip_granted_at
        )
    if "is_free_extended" in updates:
        action_types.append("extend_free" if updates["is_free_extended"] else "revoke_free_extension")
        user.free_extended_by = admin.id if updates["is_free_extended"] else user.free_extended_by
        user.free_extended_reason = payload.reason if updates["is_free_extended"] else user.free_extended_reason
    if "restriction_level" in updates:
        action_types.append("restrict")
        user.restricted_by = admin.id
        user.restriction_count = (user.restriction_count or 0) + 1

    for field, value in updates.items():
        setattr(user, field, value)

    new_state = _user_snapshot(user)

    await _log_action(
        db=db,
        admin=admin,
        request=request,
        target_user_id=user.id,
        action_type=",".join(action_types) or "update",
        action_details=updates,
        reason=payload.reason,
        previous_state=previous_state,
        new_state=new_state,
    )

    await db.commit()
    await db.refresh(user)

    return {"success": True, "user": UserResponse.from_db(user).model_dump()}


# ═══════════════════════════════════════════════════════════════
#  Marketplace moderation
# ═══════════════════════════════════════════════════════════════
@router.get("/marketplace/apps", summary="List all marketplace listings (any status)")
async def admin_list_listings(
    status_filter: Optional[ListingStatus] = Query(None, alias="status"),
    category: Optional[ListingCategory] = Query(None),
    featured_only: bool = Query(False),
    search: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(MarketplaceApp)

    if status_filter:
        query = query.where(MarketplaceApp.status == status_filter)
    if category:
        query = query.where(MarketplaceApp.category == category)
    if featured_only:
        query = query.where(MarketplaceApp.is_featured.is_(True))
    if search:
        like = f"%{search}%"
        query = query.where(
            or_(MarketplaceApp.name.ilike(like), MarketplaceApp.tagline.ilike(like))
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

    seller_ids = {listing.seller_id for listing in listings}
    sellers_by_id: dict[str, User] = {}
    if seller_ids:
        sellers_result = await db.execute(select(User).where(User.id.in_(seller_ids)))
        sellers_by_id = {u.id: u for u in sellers_result.scalars().all()}

    return {
        "success": True,
        "listings": [
            _serialize_listing(listing, sellers_by_id.get(listing.seller_id))
            for listing in listings
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


class AdminListingUpdateRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)
    status: Optional[ListingStatus] = None
    is_featured: Optional[bool] = None


@router.patch("/marketplace/apps/{listing_id}", summary="Moderate or feature a listing")
async def admin_update_listing(
    listing_id: str,
    payload: AdminListingUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == listing_id))
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")

    updates = payload.model_dump(exclude_unset=True, exclude={"reason"})
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update.")

    previous_state = {
        "status": _jsonable(listing.status),
        "is_featured": listing.is_featured,
    }

    action_types: list[str] = []
    if "status" in updates:
        action_types.append("moderate_listing")
    if "is_featured" in updates:
        action_types.append("feature_listing" if updates["is_featured"] else "unfeature_listing")

    for field, value in updates.items():
        setattr(listing, field, value)

    new_state = {
        "status": _jsonable(listing.status),
        "is_featured": listing.is_featured,
    }

    await _log_action(
        db=db,
        admin=admin,
        request=request,
        target_user_id=listing.seller_id,
        action_type=",".join(action_types) or "update",
        action_details=updates,
        reason=payload.reason,
        previous_state=previous_state,
        new_state=new_state,
    )

    await db.commit()
    await db.refresh(listing)

    seller_result = await db.execute(select(User).where(User.id == listing.seller_id))
    seller = seller_result.scalar_one_or_none()

    return {"success": True, "listing": _serialize_listing(listing, seller)}


# ═══════════════════════════════════════════════════════════════
#  Audit log
# ═══════════════════════════════════════════════════════════════
@router.get("/audit-log", summary="Browse the admin action audit log")
async def get_audit_log(
    admin_id: Optional[str] = Query(None),
    target_user_id: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(AdminAction)

    if admin_id:
        query = query.where(AdminAction.admin_id == admin_id)
    if target_user_id:
        query = query.where(AdminAction.target_user_id == target_user_id)
    if action_type:
        query = query.where(AdminAction.action_type.ilike(f"%{action_type}%"))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    query = (
        query.order_by(AdminAction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    actions = result.scalars().all()

    return {
        "success": True,
        "actions": [
            {
                "id": a.id,
                "admin_id": a.admin_id,
                "target_user_id": a.target_user_id,
                "action_type": a.action_type,
                "action_details": a.action_details,
                "reason": a.reason,
                "previous_state": a.previous_state,
                "new_state": a.new_state,
                "ip_address": a.ip_address,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in actions
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ═══════════════════════════════════════════════════════════════
#  Platform settings
# ═══════════════════════════════════════════════════════════════
@router.get("/settings", summary="Get all platform settings")
async def get_settings(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PlatformSetting))
    settings_rows = result.scalars().all()
    return {
        "success": True,
        "settings": {
            row.key: {
                "value": row.value,
                "updated_by": row.updated_by,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in settings_rows
        },
    }


class SettingUpdateRequest(BaseModel):
    value: dict


@router.put("/settings/{key}", summary="Create or update a platform setting")
async def update_setting(
    key: str,
    payload: SettingUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == key))
    setting = result.scalar_one_or_none()

    if setting is None:
        setting = PlatformSetting(key=key, value=payload.value, updated_by=admin.id)
        db.add(setting)
    else:
        setting.value = payload.value
        setting.updated_by = admin.id

    await db.commit()
    await db.refresh(setting)

    return {
        "success": True,
        "setting": {
            "key": setting.key,
            "value": setting.value,
            "updated_by": setting.updated_by,
            "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
        },
    }
