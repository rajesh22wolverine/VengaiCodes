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
from sqlalchemy import func, nullslast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_admin
from app.config import settings
from app.core.crypto import encrypt_secret
from app.core.database import get_db
from app.models.ai_config import UserAIConfig
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
from app.schemas.ai_config import (
    DEFAULT_BASE_URLS,
    PROVIDERS_REQUIRING_KEY,
    AdminAIConfigCreate,
    AdminAIConfigDetailResponse,
    AdminAIConfigListResponse,
    AdminAIConfigResponse,
    AdminAIConfigUpdate,
)
from app.schemas.auth import ErrorResponse, UserResponse

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
        "projects_limit": user.projects_limit,
        "ai_tokens_limit": user.ai_tokens_limit,
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
    projects_limit: Optional[int] = None
    ai_tokens_limit: Optional[int] = None


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
    if "projects_limit" in updates or "ai_tokens_limit" in updates:
        action_types.append("adjust_limits")

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


# ═══════════════════════════════════════════════════════════════
#  AI Models — platform-default AI configs (user_id IS NULL). These sit
#  in every user's "bag" alongside their own BYO configs — see
#  app/ai/orchestrator.get_effective_bag() and app/models/ai_config.py.
# ═══════════════════════════════════════════════════════════════
async def _get_platform_config(db: AsyncSession, config_id: str) -> UserAIConfig:
    result = await db.execute(
        select(UserAIConfig).where(
            UserAIConfig.id == config_id, UserAIConfig.user_id.is_(None)
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Platform AI model configuration not found.",
        )
    return config


@router.get(
    "/ai-configs",
    response_model=AdminAIConfigListResponse,
    summary="List platform-default AI model configs",
)
async def admin_list_ai_configs(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserAIConfig)
        .where(UserAIConfig.user_id.is_(None))
        .order_by(nullslast(UserAIConfig.order_index), UserAIConfig.created_at)
    )
    configs = result.scalars().all()
    return AdminAIConfigListResponse(
        configs=[AdminAIConfigResponse.from_db(c) for c in configs],
        total=len(configs),
    )


@router.post(
    "/ai-configs",
    response_model=AdminAIConfigDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Add a platform-default AI model config",
)
async def admin_create_ai_config(
    payload: AdminAIConfigCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    base_url = payload.base_url or DEFAULT_BASE_URLS.get(payload.provider_type)
    if payload.provider_type == "ollama":
        base_url = base_url or settings.OLLAMA_HOST
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_url is required for a custom provider.",
        )
    if payload.provider_type in PROVIDERS_REQUIRING_KEY and not payload.api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An API key is required for {payload.provider_type}.",
        )

    config = UserAIConfig(
        user_id=None,
        provider_type=payload.provider_type,
        base_url=base_url,
        api_key_encrypted=encrypt_secret(payload.api_key) if payload.api_key else None,
        model_name=payload.model_name,
        label=payload.label,
        is_active=payload.is_active,
        order_index=payload.order_index,
        task_type=payload.task_type,
    )
    db.add(config)
    await db.flush()

    await _log_action(
        db=db,
        admin=admin,
        request=request,
        target_user_id=admin.id,
        action_type="ai_config_create",
        action_details={
            "config_id": config.id,
            "provider_type": config.provider_type,
            "label": config.label,
        },
        reason="Added a platform-default AI model config.",
        previous_state={},
        new_state={"id": config.id, "label": config.label, "provider_type": config.provider_type},
    )

    await db.commit()
    await db.refresh(config)

    return AdminAIConfigDetailResponse(config=AdminAIConfigResponse.from_db(config))


@router.patch(
    "/ai-configs/{config_id}",
    response_model=AdminAIConfigDetailResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Update a platform-default AI model config",
)
async def admin_update_ai_config(
    config_id: str,
    payload: AdminAIConfigUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    config = await _get_platform_config(db, config_id)
    previous_state = {
        "label": config.label,
        "is_active": config.is_active,
        "order_index": config.order_index,
        "model_name": config.model_name,
        "base_url": config.base_url,
    }

    if payload.base_url is not None:
        config.base_url = payload.base_url
    if payload.api_key is not None:
        config.api_key_encrypted = encrypt_secret(payload.api_key) if payload.api_key else None
    if payload.model_name is not None:
        config.model_name = payload.model_name
    if payload.label is not None:
        config.label = payload.label
    if payload.is_active is not None:
        config.is_active = payload.is_active
    if payload.order_index is not None:
        config.order_index = payload.order_index
    elif payload.clear_order_index:
        config.order_index = None
    if payload.task_type is not None:
        config.task_type = payload.task_type
    elif payload.clear_task_type:
        config.task_type = None

    await _log_action(
        db=db,
        admin=admin,
        request=request,
        target_user_id=admin.id,
        action_type="ai_config_update",
        action_details=payload.model_dump(exclude_unset=True, exclude={"api_key"}),
        reason="Updated a platform-default AI model config.",
        previous_state=previous_state,
        new_state={
            "label": config.label,
            "is_active": config.is_active,
            "order_index": config.order_index,
            "model_name": config.model_name,
            "base_url": config.base_url,
        },
    )

    await db.commit()
    await db.refresh(config)

    return AdminAIConfigDetailResponse(config=AdminAIConfigResponse.from_db(config))


@router.delete(
    "/ai-configs/{config_id}",
    responses={404: {"model": ErrorResponse}},
    summary="Remove a platform-default AI model config",
)
async def admin_delete_ai_config(
    config_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    config = await _get_platform_config(db, config_id)

    await _log_action(
        db=db,
        admin=admin,
        request=request,
        target_user_id=admin.id,
        action_type="ai_config_delete",
        action_details={"config_id": config.id, "label": config.label},
        reason="Removed a platform-default AI model config.",
        previous_state={"label": config.label, "provider_type": config.provider_type},
        new_state={},
    )

    await db.delete(config)
    await db.commit()

    return {"success": True, "message": "Platform AI model configuration deleted successfully."}
