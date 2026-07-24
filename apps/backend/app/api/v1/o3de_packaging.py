# ═══════════════════════════════════════════════════════════════
#  VengaiCode — O3DE Packaging API Routes (per-project)
#  api/v1/o3de_packaging.py — Trigger, poll, and download a validated,
#  zipped O3DE project via GitHub Actions.
#
#  Deliberately named "package", not "build" — package-o3de-project.yml
#  does NOT compile anything (see that workflow's header for why: a real
#  O3DE engine build is tens of GB and hours, not something a GitHub-
#  hosted runner can do — same reasoning stack_matrix.CI_BUILDABLE_
#  GAME_ENGINES already documents for why O3DE isn't in that set, unlike
#  Godot). What this DOES do: fetch the project's generated files (real
#  project.json / level prefab / Lua scripts — see app/ai/codegen/
#  o3de.py), validate them (JSON parses, Lua syntax checks), and zip the
#  result as a downloadable artifact the user opens in their own O3DE
#  Editor. Mirrors android_packaging.py's route shape (trigger/status/
#  artifacts/download) but for one engine, not a multi-stack dispatch
#  table — there's no "_workflow_for_stack" here since this router is
#  only ever reached for O3DE projects.
#
#  HONEST STATUS: written but UNTESTED end-to-end — no O3DE-aware CI
#  run has ever been triggered. Requires the same GITHUB_TOKEN/
#  GITHUB_REPO/BUILD_SECRET settings as every other packaging module —
#  no separate configuration needed.
# ═══════════════════════════════════════════════════════════════

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stack_matrix import get_project_stack
from app.api.v1.auth import get_current_active_user
from app.config import settings
from app.core.database import get_db
from app.core.naming import safe_filename
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger("vengaicode.o3de_packaging")
router = APIRouter()

GITHUB_API = "https://api.github.com"
_WORKFLOW_FILE = "package-o3de-project.yml"
_EVENT_TYPE = "package-o3de-project-app"


# ─── Schemas ───
class TriggerPackageRequest(BaseModel):
    project_id: str


class PackageStatusResponse(BaseModel):
    success: bool = True
    status: str  # "not_started" | "queued" | "in_progress" | "completed" | "failed"
    run_url: str | None = None
    conclusion: str | None = None  # "success" | "failure" | None


async def _get_o3de_project(project_id: str, user: User, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    if get_project_stack(project)["frontend_framework"] != "o3de":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This project isn't using Open 3D Engine — nothing to package here.",
        )
    return project


# ═══════════════════════════════════════════════════════════════
#  POST /package — trigger a validate-and-zip O3DE package
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/package",
    summary="Validate and zip this project's generated O3DE files via GitHub Actions",
)
async def trigger_package(
    payload: TriggerPackageRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Triggers package-o3de-project.yml via repository_dispatch. That
    workflow calls back to GET /packaging/{project_id}/files (the same
    platform-agnostic endpoint every other packaging workflow uses) to
    fetch the code, then validates and zips it — it does NOT compile
    an O3DE build. See this module's header for why.
    """
    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Packaging is not configured yet (missing GitHub credentials).",
        )

    project = await _get_o3de_project(payload.project_id, user, db)

    if not project.codegen_data or not project.codegen_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generated code must be approved before packaging.",
        )

    validation_warnings = project.codegen_data.get("validation_warnings", [])
    if validation_warnings:
        bad_paths = ", ".join(w["path"] for w in validation_warnings)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{len(validation_warnings)} generated file(s) failed validation and are "
                f"likely broken: {bad_paths}. Regenerate the code before packaging."
            ),
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/dispatches",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "event_type": _EVENT_TYPE,
                "client_payload": {"project_id": payload.project_id},
            },
        )

    if response.status_code != 204:
        logger.error(f"Failed to trigger O3DE package: {response.status_code} {response.text}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to start packaging. Please try again.",
        )

    return {
        "success": True,
        "message": (
            "Packaging started! This validates and zips your O3DE project (a few minutes) — "
            "it does NOT compile a game. Open the result in your own O3DE Editor afterward. 🐯📦"
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id}/status — poll packaging status
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/status",
    response_model=PackageStatusResponse,
    summary="Check the status of the most recent O3DE packaging run",
)
async def get_package_status(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_o3de_project(project_id, user, db)

    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Packaging is not configured yet.",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/workflows/"
            f"{_WORKFLOW_FILE}/runs",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 20},
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to check packaging status.",
        )

    # The run's display name is set via `run-name:` in the workflow file to
    # include the project_id, so we can find the run for THIS project instead
    # of assuming the single most recent repo-wide run belongs to us.
    runs = response.json().get("workflow_runs", [])
    matching = next((r for r in runs if project_id in (r.get("name") or "")), None)
    if matching is None:
        return PackageStatusResponse(status="not_started")

    return PackageStatusResponse(
        status=matching.get("status", "unknown"),
        conclusion=matching.get("conclusion"),
        run_url=matching.get("html_url"),
    )


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id}/artifacts — list the packaged project zip
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/artifacts",
    summary="List available downloadable artifacts for a completed O3DE packaging run",
)
async def list_package_artifacts(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_o3de_project(project_id, user, db)

    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Packaging is not configured yet.",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        runs_response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/workflows/"
            f"{_WORKFLOW_FILE}/runs",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 20, "status": "completed"},
        )

        runs = runs_response.json().get("workflow_runs", [])
        matching = next((r for r in runs if project_id in (r.get("name") or "")), None)
        if matching is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No completed packaging run found for this project. Trigger one first.",
            )

        run_id = matching["id"]

        artifacts_response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/runs/{run_id}/artifacts",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
        )

    artifacts = artifacts_response.json().get("artifacts", [])
    if not artifacts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packaging completed but no project zip artifact was found.",
        )

    return {
        "success": True,
        "artifacts": [
            {
                "id": a["id"],
                "name": a["name"],
                "size_bytes": a["size_in_bytes"],
                "download_filename": f"{safe_filename(project.name)}-{a['name']}.zip",
            }
            for a in artifacts
        ],
    }


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id}/artifacts/{artifact_id}/download
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/artifacts/{artifact_id}/download",
    summary="Stream the packaged O3DE project zip for direct download",
)
async def download_package_artifact(
    project_id: str,
    artifact_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_o3de_project(project_id, user, db)

    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Packaging is not configured yet.",
        )

    async def stream_artifact():
        github_url = (
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/artifacts/"
            f"{artifact_id}/zip"
        )
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
            async with client.stream(
                "GET",
                github_url,
                headers={
                    "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                },
            ) as response:
                if response.status_code != 200:
                    logger.error(
                        f"GitHub artifact download failed: {response.status_code}"
                    )
                    return
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    yield chunk

    filename = f"{safe_filename(project.name)}-o3de-{artifact_id}.zip"
    return StreamingResponse(
        stream_artifact(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
