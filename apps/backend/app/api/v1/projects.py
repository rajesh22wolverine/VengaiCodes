# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Projects API Routes
#  api/v1/projects.py — Create, list, get, delete projects
#  Minimal Sprint 1 version — SDLC phase logic arrives in Sprint 2+
# ═══════════════════════════════════════════════════════════════

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.project import Project, ProjectStatus, SDLCPhase, AppCategory
from app.models.user import User
from app.schemas.auth import ErrorResponse
from app.schemas.project import (
    CreateProjectRequest,
    DeleteProjectResponse,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectResponse,
)

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
#  GET /projects — list current user's projects
# ═══════════════════════════════════════════════════════════════
@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List all projects for the current user",
)
async def list_projects(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns all non-deleted projects owned by the current user, newest first."""
    result = await db.execute(
        select(Project)
        .where(Project.user_id == user.id, Project.deleted_at.is_(None))
        .order_by(Project.updated_at.desc())
    )
    projects = result.scalars().all()

    return ProjectListResponse(
        projects=[ProjectResponse.from_db(p) for p in projects],
        total=len(projects),
    )


# ═══════════════════════════════════════════════════════════════
#  POST /projects — create a new project
# ═══════════════════════════════════════════════════════════════
@router.post(
    "",
    response_model=ProjectDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={403: {"model": ErrorResponse}},
    summary="Create a new project from an idea description",
)
async def create_project(
    payload: CreateProjectRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new project in DRAFT status, starting at the
    Requirements phase. Enforces the user's project tier limit.
    """
    if not user.can_create_project():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"You've used all {user.projects_limit} project(s) on your "
                f"{user.tier.value if hasattr(user.tier, 'value') else user.tier} plan. "
                "Upgrade to create more! 🐯"
            ),
        )

    project = Project(
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        raw_idea=payload.raw_idea,
        category=AppCategory.OTHER,
        platforms=[],
        status=ProjectStatus.DRAFT,
        current_phase=SDLCPhase.REQUIREMENTS,
        progress_percent=0.0,
        phases_completed=[],
        understanding_score=0.0,
        ai_conversation_history=[],
        phase_started_at={"requirements": datetime.now(timezone.utc).isoformat()},
        phase_completed_at={},
        change_requests=[],
        reference_apps=[],
        unique_features=[],
    )
    db.add(project)

    # Increment user's project usage count (unless admin-extended/unlimited)
    if user.projects_limit != -1 and not user.is_free_extended:
        user.projects_used += 1

    await db.commit()
    await db.refresh(project)

    return ProjectDetailResponse(project=ProjectResponse.from_db(project))


# ═══════════════════════════════════════════════════════════════
#  GET /projects/{project_id} — get a single project
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get a single project by ID",
)
async def get_project(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns a single project — must be owned by the current user."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
        )

    return ProjectDetailResponse(project=ProjectResponse.from_db(project))


# ═══════════════════════════════════════════════════════════════
#  DELETE /projects/{project_id} — soft delete a project
# ═══════════════════════════════════════════════════════════════
@router.delete(
    "/{project_id}",
    response_model=DeleteProjectResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Delete a project (soft delete)",
)
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Soft-deletes a project (sets deleted_at) — does not free up the
    user's project quota, matching the "1 free project, used or not"
    model described in the pricing plan.
    """
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
        )

    project.deleted_at = datetime.now(timezone.utc)
    project.status = ProjectStatus.DELETED
    await db.commit()

    return DeleteProjectResponse()


@router.post(
    "/{project_id}/complete",
    summary="Mark a project as completed",
)
async def mark_project_complete(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Marks a project as fully completed — flips status from
    in_progress → completed, moving it from the Pending tab
    to the Completed tab on the dashboard. Called from the
    Export screen's "Finish & Return Home" button.
    """
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found."
        )

    project.status = ProjectStatus.COMPLETED
    project.progress_percent = 100.0

    await db.commit()

    return {
        "success": True,
        "message": "Project marked complete 🐯",
        "project_id": project_id,
    }
