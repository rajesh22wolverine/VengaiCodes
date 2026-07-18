# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Android Packaging API Routes (per-project APK builds)
#  api/v1/android_packaging.py — Trigger, poll, and download
#  GitHub Actions-built Android APKs
#
#  Mirrors packaging.py (Windows installer builds) but targets
#  build-android-installer.yml instead. Reuses the same
#  GET /packaging/{project_id}/files endpoint for fetching generated
#  code — that endpoint is platform-agnostic.
#
#  HONEST STATUS: written but UNTESTED end-to-end, same caveats as
#  packaging.py. Requires the same GITHUB_TOKEN / GITHUB_REPO /
#  BUILD_SECRET settings — no separate configuration needed.
# ═══════════════════════════════════════════════════════════════

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_active_user
from app.config import settings
from app.core.database import get_db
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger("vengaicode.android_packaging")
router = APIRouter()

GITHUB_API = "https://api.github.com"
WORKFLOW_FILE = "build-android-installer.yml"


# ─── Schemas ───
class TriggerBuildRequest(BaseModel):
    project_id: str


class BuildStatusResponse(BaseModel):
    success: bool = True
    status: str  # "not_started" | "queued" | "in_progress" | "completed" | "failed"
    run_url: str | None = None
    conclusion: str | None = None  # "success" | "failure" | None


# ═══════════════════════════════════════════════════════════════
#  POST /build — trigger an Android APK build
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/build",
    summary="Trigger an Android APK build via GitHub Actions",
)
async def trigger_build(
    payload: TriggerBuildRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Triggers the build-android-installer.yml GitHub Actions workflow
    via the repository_dispatch API. The workflow then calls back to
    GET /packaging/{project_id}/files to fetch the code to package.
    """
    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Packaging is not configured yet (missing GitHub credentials).",
        )

    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.codegen_data or not project.codegen_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generated code must be approved before packaging.",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/dispatches",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "event_type": "build-android-installer-app",
                "client_payload": {"project_id": payload.project_id},
            },
        )

    if response.status_code != 204:
        logger.error(f"Failed to trigger build: {response.status_code} {response.text}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to start the build. Please try again.",
        )

    return {
        "success": True,
        "message": "Build started! This takes 10-25 minutes. Check status for progress. 🐯🏗️",
    }


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id}/status — poll build status
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/status",
    response_model=BuildStatusResponse,
    summary="Check the status of the most recent Android APK build",
)
async def get_build_status(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Packaging is not configured yet.",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/workflows/"
            f"{WORKFLOW_FILE}/runs",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 1},
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to check build status.",
        )

    runs = response.json().get("workflow_runs", [])
    if not runs:
        return BuildStatusResponse(status="not_started")

    latest = runs[0]
    return BuildStatusResponse(
        status=latest.get("status", "unknown"),
        conclusion=latest.get("conclusion"),
        run_url=latest.get("html_url"),
    )


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id}/artifacts — list available APK artifacts
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/artifacts",
    summary="List available downloadable artifacts for a completed Android build",
)
async def list_build_artifacts(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Packaging is not configured yet.",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        runs_response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/workflows/"
            f"{WORKFLOW_FILE}/runs",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 1, "status": "completed"},
        )

        runs = runs_response.json().get("workflow_runs", [])
        if not runs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No completed build found. Trigger a build first.",
            )

        run_id = runs[0]["id"]

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
            detail="Build completed but no APK artifact was found.",
        )

    return {
        "success": True,
        "artifacts": [
            {
                "id": a["id"],
                "name": a["name"],
                "size_bytes": a["size_in_bytes"],
                "download_filename": f"{a['name']}.zip",
            }
            for a in artifacts
        ],
    }


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id}/artifacts/{artifact_id}/download
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/artifacts/{artifact_id}/download",
    summary="Stream a specific Android build artifact for direct download",
)
async def download_build_artifact(
    project_id: str,
    artifact_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

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

    filename = f"vengaicode-android-{artifact_id}.zip"
    return StreamingResponse(
        stream_artifact(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
