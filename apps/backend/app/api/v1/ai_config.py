# ═══════════════════════════════════════════════════════════════
#  VengaiCode — User AI Config API Routes
#  api/v1/ai_config.py — CRUD for a user's "bring your own AI model"
#  configurations (their own Groq/OpenAI key, or a custom self-hosted
#  endpoint). Setting one active makes the orchestrator use it instead
#  of the platform default — see app/ai/orchestrator.py.
# ═══════════════════════════════════════════════════════════════

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import get_effective_bag
from app.api.v1.auth import get_current_active_user
from app.core.crypto import encrypt_secret
from app.core.database import get_db
from app.models.ai_config import UserAIConfig
from app.models.user import User
from app.schemas.ai_config import (
    DEFAULT_BASE_URLS,
    PROVIDERS_REQUIRING_KEY,
    AIConfigCreate,
    AIConfigDetailResponse,
    AIConfigListResponse,
    AIConfigResponse,
    AIConfigUpdate,
    BagConfigResponse,
    BagOrderUpdate,
    BagResponse,
    DeleteAIConfigResponse,
)
from app.schemas.auth import ErrorResponse

router = APIRouter()


async def _get_owned_config(db: AsyncSession, user: User, config_id: str) -> UserAIConfig:
    result = await db.execute(
        select(UserAIConfig).where(
            UserAIConfig.id == config_id, UserAIConfig.user_id == user.id
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI model configuration not found.",
        )
    return config


async def _deactivate_others(db: AsyncSession, user: User, keep_id: str | None = None) -> None:
    """Only one config may be is_active per user — clear the rest."""
    stmt = update(UserAIConfig).where(UserAIConfig.user_id == user.id).values(is_active=False)
    if keep_id is not None:
        stmt = stmt.where(UserAIConfig.id != keep_id)
    await db.execute(stmt)


async def _clear_priority_slot(
    db: AsyncSession, user: User, priority: str, keep_id: str | None = None
) -> None:
    """Only one config may hold a given priority slot per user — clear the rest."""
    stmt = (
        update(UserAIConfig)
        .where(UserAIConfig.user_id == user.id, UserAIConfig.priority == priority)
        .values(priority=None)
    )
    if keep_id is not None:
        stmt = stmt.where(UserAIConfig.id != keep_id)
    await db.execute(stmt)


# ═══════════════════════════════════════════════════════════════
#  GET /ai/configs — list current user's saved AI configs
# ═══════════════════════════════════════════════════════════════
@router.get(
    "",
    response_model=AIConfigListResponse,
    summary="List the current user's saved BYO AI model configurations",
)
async def list_ai_configs(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserAIConfig)
        .where(UserAIConfig.user_id == user.id)
        .order_by(UserAIConfig.created_at.desc())
    )
    configs = result.scalars().all()
    return AIConfigListResponse(
        configs=[AIConfigResponse.from_db(c) for c in configs],
        total=len(configs),
    )


# ═══════════════════════════════════════════════════════════════
#  POST /ai/configs — save a new BYO AI model configuration
# ═══════════════════════════════════════════════════════════════
@router.post(
    "",
    response_model=AIConfigDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Save a new BYO AI model configuration (own key or custom endpoint)",
)
async def create_ai_config(
    payload: AIConfigCreate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    base_url = payload.base_url or DEFAULT_BASE_URLS.get(payload.provider_type)
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

    if payload.is_active:
        await _deactivate_others(db, user)
    if payload.priority:
        await _clear_priority_slot(db, user, payload.priority)

    config = UserAIConfig(
        user_id=user.id,
        provider_type=payload.provider_type,
        base_url=base_url,
        api_key_encrypted=encrypt_secret(payload.api_key) if payload.api_key else None,
        model_name=payload.model_name,
        label=payload.label,
        is_active=payload.is_active,
        priority=payload.priority,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)

    return AIConfigDetailResponse(config=AIConfigResponse.from_db(config))


# ═══════════════════════════════════════════════════════════════
#  PATCH /ai/configs/{id} — update a config (including set-active)
# ═══════════════════════════════════════════════════════════════
@router.patch(
    "/{config_id}",
    response_model=AIConfigDetailResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Update a BYO AI model configuration, or set it active",
)
async def update_ai_config(
    config_id: str,
    payload: AIConfigUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    config = await _get_owned_config(db, user, config_id)

    if payload.base_url is not None:
        config.base_url = payload.base_url
    if payload.api_key is not None:
        config.api_key_encrypted = encrypt_secret(payload.api_key) if payload.api_key else None
    if payload.model_name is not None:
        config.model_name = payload.model_name
    if payload.label is not None:
        config.label = payload.label
    if payload.is_active is not None:
        if payload.is_active:
            await _deactivate_others(db, user, keep_id=config.id)
        config.is_active = payload.is_active
    if payload.priority is not None:
        await _clear_priority_slot(db, user, payload.priority, keep_id=config.id)
        config.priority = payload.priority
    elif payload.clear_priority:
        config.priority = None

    await db.commit()
    await db.refresh(config)

    return AIConfigDetailResponse(config=AIConfigResponse.from_db(config))


# ═══════════════════════════════════════════════════════════════
#  DELETE /ai/configs/{id} — remove a saved config
# ═══════════════════════════════════════════════════════════════
@router.delete(
    "/{config_id}",
    response_model=DeleteAIConfigResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Delete a saved BYO AI model configuration",
)
async def delete_ai_config(
    config_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    config = await _get_owned_config(db, user, config_id)
    await db.delete(config)
    await db.commit()
    return DeleteAIConfigResponse()


# ═══════════════════════════════════════════════════════════════
#  GET /ai/configs/bag — preview the current user's effective AI model
#  bag: platform defaults (admin-managed) merged with their own configs,
#  in the order generate_text() tries them — see
#  app/ai/orchestrator.get_effective_bag()
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/bag",
    response_model=BagResponse,
    summary="Preview the current user's effective AI model bag, in try order",
)
async def get_bag(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    bag, _ = await get_effective_bag(user, db)
    return BagResponse(bag=[BagConfigResponse.from_db(c) for c in bag])


# ═══════════════════════════════════════════════════════════════
#  PUT /ai/configs/bag-order — save a personal reorder of the bag
# ═══════════════════════════════════════════════════════════════
@router.put(
    "/bag-order",
    response_model=BagResponse,
    summary="Reorder the current user's AI model bag",
)
async def set_bag_order(
    payload: BagOrderUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    user.ai_bag_order = payload.order
    await db.commit()
    await db.refresh(user)

    bag, _ = await get_effective_bag(user, db)
    return BagResponse(bag=[BagConfigResponse.from_db(c) for c in bag])
