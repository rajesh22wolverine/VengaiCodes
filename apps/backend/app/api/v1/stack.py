# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Stack Selection API Routes
#  api/v1/stack.py — Lets the user explicitly pick a UI language+
#  framework, a backend language+framework, and an API style, tells
#  them whether that combination is possible, and suggests the
#  nearest possible combination when it isn't (or isn't buildable
#  yet). See app.ai.stack_matrix for the actual compatibility rules.
# ═══════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stack_matrix import (
    API_STYLES,
    BACKEND_FRAMEWORKS,
    DEFAULT_GAME_COMBO,
    DEFAULT_WEB_COMBO,
    FRONTEND_FRAMEWORKS,
    validate_stack,
)
from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.project import AppCategory, Project
from app.models.user import User

logger = logging.getLogger("vengaicode.stack")
router = APIRouter()


# ─── Schemas ───
class StackSelection(BaseModel):
    frontend_language: str
    frontend_framework: str
    backend_language: str
    backend_framework: str
    api_style: str


class StackComboOut(BaseModel):
    selection: StackSelection
    frontend_label: str
    backend_label: str
    buildable_now: bool


class ValidateStackRequest(BaseModel):
    selection: StackSelection


class ValidateStackResponse(BaseModel):
    success: bool = True
    status: str  # "ok" | "coherent_not_buildable" | "incoherent"
    coherent: bool
    buildable_now: bool
    coherence_errors: list[str] = []
    message: str
    suggestion: StackComboOut | None = None


class FrontendFrameworkOption(BaseModel):
    key: str
    label: str
    languages: list[str]
    category: str


class BackendFrameworkOption(BaseModel):
    key: str
    label: str
    languages: list[str]
    supported_api_styles: list[str]


class StackOptionsResponse(BaseModel):
    success: bool = True
    frontend_languages: list[str]
    frontend_frameworks: list[FrontendFrameworkOption]
    backend_languages: list[str]
    backend_frameworks: list[BackendFrameworkOption]
    api_styles: list[str]
    recommended_default: StackSelection


class SelectStackRequest(BaseModel):
    project_id: str
    selection: StackSelection


class SelectStackResponse(BaseModel):
    success: bool = True
    message: str
    buildable_now: bool
    selected_stack: dict


# ─── Helpers ───
def _pickable_frontend_frameworks() -> list[FrontendFrameworkOption]:
    return [
        FrontendFrameworkOption(key=key, label=meta["label"], languages=meta["languages"], category=meta["category"])
        for key, meta in FRONTEND_FRAMEWORKS.items()
    ]


def _pickable_backend_frameworks() -> list[BackendFrameworkOption]:
    return [
        BackendFrameworkOption(
            key=key,
            label=meta["label"],
            languages=meta["languages"],
            supported_api_styles=[a for a in meta["api_styles"] if a != "none"],
        )
        for key, meta in BACKEND_FRAMEWORKS.items()
    ]


# ═══════════════════════════════════════════════════════════════
#  GET /options — full compatibility matrix, for the picker UI
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/options",
    response_model=StackOptionsResponse,
    summary="Get the full stack compatibility matrix for the picker UI",
)
async def get_stack_options(
    project_id: str | None = None,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    recommended = DEFAULT_WEB_COMBO
    if project_id:
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user.id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        if project.category == AppCategory.GAME:
            recommended = DEFAULT_GAME_COMBO

    frontend_languages = sorted({lang for meta in FRONTEND_FRAMEWORKS.values() for lang in meta["languages"]})
    backend_languages = sorted({lang for meta in BACKEND_FRAMEWORKS.values() for lang in meta["languages"] if lang != "none"})

    return StackOptionsResponse(
        frontend_languages=frontend_languages,
        frontend_frameworks=_pickable_frontend_frameworks(),
        backend_languages=backend_languages,
        backend_frameworks=_pickable_backend_frameworks(),
        api_styles=API_STYLES,
        recommended_default=StackSelection(**recommended["selection"]),
    )


# ═══════════════════════════════════════════════════════════════
#  POST /validate — dry-run check of a requested combination
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/validate",
    response_model=ValidateStackResponse,
    summary="Check whether a UI/backend/API combination is possible and buildable",
)
async def validate_stack_selection(
    payload: ValidateStackRequest,
    user: User = Depends(get_current_active_user),
):
    """
    Pure validation, no DB write — safe to call on every picker change.
    `status` is one of "ok" (valid and buildable now), "coherent_not_buildable"
    (technically valid, VengaiCode just can't generate it yet), or "incoherent"
    (not actually possible — e.g. a UI framework paired with a language it
    doesn't run in). Whenever status != "ok", `suggestion` is the nearest
    combination that IS buildable right now.
    """
    result = validate_stack(payload.selection.model_dump())
    return ValidateStackResponse(**result)


# ═══════════════════════════════════════════════════════════════
#  POST /select — validate server-side and persist the choice
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/select",
    response_model=SelectStackResponse,
    summary="Validate and save this project's chosen tech stack",
)
async def select_stack(
    payload: SelectStackRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == payload.project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    # Re-validate server-side — never trust the picker alone. The frontend
    # already calls POST /stack/validate on every picker change and disables
    # "Continue" for incoherent combos, so this is a defense-in-depth check,
    # not the primary place a user sees coherence_errors/suggestion — those
    # are surfaced from the /validate response body instead of here, because
    # apiClient's response interceptor (lib/api.ts) flattens every error
    # response down to a plain string message and discards the rest of
    # error.response.data, same as every other endpoint in this app.
    validation = validate_stack(payload.selection.model_dump())
    if not validation["coherent"]:
        suggestion = validation["suggestion"] or {}
        suggested_selection = suggestion.get("selection", {})
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{validation['message']} "
                f"({'; '.join(validation['coherence_errors'])}) "
                f"Nearest possible: {suggestion.get('frontend_label', '?')} + "
                f"{suggestion.get('backend_label', '?')} "
                f"({suggested_selection.get('api_style', '?')})."
            ),
        )

    selected_stack = {
        **payload.selection.model_dump(),
        "buildable_now": validation["buildable_now"],
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    project.selected_stack = selected_stack
    await db.commit()

    if validation["buildable_now"]:
        message = "Stack saved — ready to build."
    else:
        message = (
            "Stack saved. It's technically valid, but VengaiCode can't generate it yet — "
            "code generation will substitute the nearest supported stack when you get there."
        )

    return SelectStackResponse(
        message=message,
        buildable_now=validation["buildable_now"],
        selected_stack=selected_stack,
    )


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id} — fetch a previously saved stack selection
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}",
    summary="Get this project's saved stack selection",
)
async def get_project_stack_selection(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.selected_stack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No stack selected yet.")

    return {"success": True, "selected_stack": project.selected_stack}
