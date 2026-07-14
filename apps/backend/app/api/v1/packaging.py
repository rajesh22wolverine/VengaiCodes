# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Packaging API Routes (Windows .exe/.msi builds)
#  api/v1/packaging.py — Trigger, poll, and download GitHub
#  Actions-built Windows installers
#
#  HONEST STATUS: written but UNTESTED end-to-end. Requires:
#  - GITHUB_TOKEN (a GitHub Personal Access Token with 'repo' and
#    'workflow' scopes) set in Render environment variables
#  - GITHUB_REPO setting (e.g. "KalRaj2/VengaiCodes")
#  - BUILD_SECRET setting, matching secrets.VENGAICODE_BUILD_SECRET
#    configured in the GitHub repo's Actions secrets
#
#  KNOWN LIMITATION: GitHub's repository_dispatch API does not
#  return a run ID directly. This module finds "the most recent
#  workflow run" as a best-effort way to track status — this works
#  for one build at a time but is not fully robust if multiple
#  users trigger builds concurrently. A more correct solution would
#  use a webhook callback from the workflow back to this backend.
# ═══════════════════════════════════════════════════════════════

import logging

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_active_user
from app.config import settings
from app.core.database import get_db
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger("vengaicode.packaging")
router = APIRouter()

GITHUB_API = "https://api.github.com"


# ─── Schemas ───
class TriggerBuildRequest(BaseModel):
    project_id: str


class BuildStatusResponse(BaseModel):
    success: bool = True
    status: str  # "not_started" | "queued" | "in_progress" | "completed" | "failed"
    run_url: str | None = None
    conclusion: str | None = None  # "success" | "failure" | None


# ═══════════════════════════════════════════════════════════════
#  GET /build/{project_id}/files
#  Called BY GitHub Actions (not the frontend) — secured by a
#  shared secret header instead of a user JWT, since the CI
#  runner has no user session.
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/files",
    summary="[CI use only] Fetch generated files for a build",
)
async def get_build_files(
    project_id: str,
    x_build_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the raw generated code files for a project, for
    GitHub Actions to inject into the Tauri build template.
    Secured by a shared secret (not user auth) since this is
    called by a CI runner, not a logged-in user.
    """
    if not settings.BUILD_SECRET or x_build_secret != settings.BUILD_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid build secret.",
        )

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if project is None or not project.codegen_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project or generated code not found.",
        )

    return {
        "project_name": project.name,
        "files": project.codegen_data.get("codegen", {}).get("files", []),
    }


# ═══════════════════════════════════════════════════════════════
#  POST /packaging/build — trigger a Windows build
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/build",
    summary="Trigger a Windows installer build via GitHub Actions",
)
async def trigger_build(
    payload: TriggerBuildRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Triggers the build-windows-installer.yml GitHub Actions workflow
    via the repository_dispatch API. The workflow then calls back to
    GET /build/{project_id}/files to fetch the code to package.
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
                "event_type": "build-windows-app",
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
        "message": "Build started! This takes 5-15 minutes. Check status for progress. 🐯🏗️",
    }


# ═══════════════════════════════════════════════════════════════
#  GET /packaging/{project_id}/status — poll build status
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/status",
    response_model=BuildStatusResponse,
    summary="Check the status of the most recent Windows build",
)
async def get_build_status(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Finds the most recent build-windows-installer.yml workflow run
    and returns its status. See module docstring for the known
    limitation on tracking concurrent builds.
    """
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
            f"build-windows-installer.yml/runs",
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
        status=latest.get("status", "unknown"),  # queued | in_progress | completed
        conclusion=latest.get("conclusion"),  # success | failure | None
        run_url=latest.get("html_url"),
    )


@router.get(
    "/{project_id}/artifacts",
    summary="List available downloadable artifacts for a completed build",
)
async def list_build_artifacts(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lists available artifacts (.msi zip, .exe zip) from the most recent
    successful workflow run so the frontend can render download options.
    Use GET /packaging/{project_id}/artifacts/{artifact_id}/download to
    actually stream the bytes.
    """
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
            f"build-windows-installer.yml/runs",
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
            detail="Build completed but no installer artifact was found.",
        )

    return {
        "success": True,
        "artifacts": [
            {
                "id": a["id"],
                "name": a["name"],
                "size_bytes": a["size_in_bytes"],
                # Note: GitHub returns artifacts as .zip wrappers, even for
                # single-file artifacts like .msi. The user will extract to find
                # the actual installer inside.
                "download_filename": f"{a['name']}.zip",
            }
            for a in artifacts
        ],
    }


@router.get(
    "/{project_id}/artifacts/{artifact_id}/download",
    summary="Stream a specific build artifact for direct download",
)
async def download_build_artifact(
    project_id: str,
    artifact_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Proxies GitHub artifact bytes directly back to the user so the browser
    can download the ZIP without requiring the user to authenticate to GitHub.

    Streaming rather than buffering the whole file — artifacts can be tens
    of MB, and we don't want to hold that in memory on Render's free tier.

    Note: GitHub artifacts are ALWAYS delivered as .zip files, even when they
    contain a single .msi/.exe. The user extracts to find the installer inside.
    This is a GitHub API constraint, not something we can bypass here.
    """
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

    # GitHub's artifact download endpoint returns a 302 redirect to a signed
    # AWS S3 URL. httpx follows redirects by default, so we just stream what
    # we get back — could be either the redirect target's bytes or a direct
    # response depending on GitHub's routing.
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
                    # Can't raise HTTPException mid-stream — log and end early
                    logger.error(
                        f"GitHub artifact download failed: {response.status_code}"
                    )
                    return
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    yield chunk

    filename = f"vengaicode-installer-{artifact_id}.zip"
    return StreamingResponse(
        stream_artifact(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
