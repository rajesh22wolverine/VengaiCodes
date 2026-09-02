# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Figma Connection API Routes
#  api/v1/figma.py — Connect/disconnect a user's Figma account (a free
#  personal access token, not an OAuth grant). The stored token is what
#  uiux.py's import-figma endpoint uses to pull a frame in as a page.
# ═══════════════════════════════════════════════════════════════

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_active_user
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.database import get_db
from app.core.figma_client import FigmaError, get_figma_user
from app.models.figma_connection import FigmaConnection
from app.models.user import User
from app.schemas.figma import (
    DisconnectFigmaResponse,
    FigmaConnectRequest,
    FigmaConnectionResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


async def _get_connection(db: AsyncSession, user: User) -> FigmaConnection | None:
    result = await db.execute(
        select(FigmaConnection).where(FigmaConnection.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def get_figma_token(db: AsyncSession, user: User) -> str | None:
    """Decrypted Figma token for this user, or None if not connected."""
    connection = await _get_connection(db, user)
    if connection is None:
        return None
    return decrypt_secret(connection.token_encrypted)


# ═══════════════════════════════════════════════════════════════
#  GET /figma/connection — current connection status
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/connection",
    response_model=FigmaConnectionResponse,
    summary="Check whether the current user has a Figma account connected",
)
async def get_connection_status(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    connection = await _get_connection(db, user)
    return FigmaConnectionResponse(
        connected=connection is not None,
        figma_handle=connection.figma_handle if connection else None,
    )


# ═══════════════════════════════════════════════════════════════
#  POST /figma/connection — connect (or reconnect) a Figma account
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/connection",
    response_model=FigmaConnectionResponse,
    summary="Connect a Figma account with a personal access token",
)
async def connect_figma(
    payload: FigmaConnectRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        figma_user = await get_figma_user(payload.token)
    except FigmaError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    handle = figma_user.get("handle") or figma_user.get("email") or "Figma user"
    email = figma_user.get("email")

    connection = await _get_connection(db, user)
    if connection is None:
        connection = FigmaConnection(
            user_id=user.id,
            token_encrypted=encrypt_secret(payload.token),
            figma_handle=handle,
            figma_email=email,
        )
        db.add(connection)
    else:
        connection.token_encrypted = encrypt_secret(payload.token)
        connection.figma_handle = handle
        connection.figma_email = email

    await db.commit()

    return FigmaConnectionResponse(connected=True, figma_handle=handle)


# ═══════════════════════════════════════════════════════════════
#  DELETE /figma/connection — disconnect
# ═══════════════════════════════════════════════════════════════
@router.delete(
    "/connection",
    response_model=DisconnectFigmaResponse,
    summary="Disconnect the current user's Figma account",
)
async def disconnect_figma(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    connection = await _get_connection(db, user)
    if connection is not None:
        await db.delete(connection)
        await db.commit()
    return DisconnectFigmaResponse()
