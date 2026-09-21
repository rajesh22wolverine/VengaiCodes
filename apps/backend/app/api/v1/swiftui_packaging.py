# ═══════════════════════════════════════════════════════════════
#  VengaiCode — SwiftUI Packaging API Routes (per-project)
#  api/v1/swiftui_packaging.py — Trigger, poll, and download a real,
#  CI-verified Xcode project for a SwiftUI project.
#
#  Deliberately its own router, not folded into android_packaging.py/
#  packaging.py (mirrors o3de_packaging.py's reasoning): iOS needs a
#  macos-latest runner, a different workflow shape, and a different
#  honest ceiling than any of the Windows/Linux/Android pipelines, so
#  giving it its own module keeps that ceiling explicit instead of
#  bolting an "if swiftui" branch onto code that otherwise assumes a
#  Tauri/Capacitor WebView wrap.
#
#  What build-swiftui-project.yml DOES do: fetch the project's generated
#  files (real .swift screens + a real XcodeGen project.yml — see
#  app/ai/codegen/frontend/swiftui.py), run `xcodegen generate` to turn
#  that into a real .xcodeproj, then `xcodebuild build` against an iOS
#  Simulator destination (CODE_SIGNING_ALLOWED=NO) to prove it actually
#  compiles. On success it zips the real project (source + generated
#  .xcodeproj) as the downloadable artifact.
#
#  HONEST CEILING: this proves a *simulator* build compiles — it does
#  NOT produce a signed, device-installable .ipa. Code signing needs the
#  end user's own Apple Developer account/certificates/provisioning
#  profiles, which VengaiCode has no access to; that step stays manual
#  (Xcode's Signing & Capabilities tab, after opening the downloaded
#  project — see the generated setup_commands() instructions).
#
#  HONEST STATUS: written but UNTESTED end-to-end — no macOS runner run
#  has ever been triggered from here. Requires the same GITHUB_TOKEN/
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

logger = logging.getLogger("vengaicode.swiftui_packaging")
router = APIRouter()

GITHUB_API = "https://api.github.com"
_WORKFLOW_FILE = "build-swiftui-project.yml"
_EVENT_TYPE = "build-swiftui-project-app"


# ─── Schemas ───
class TriggerBuildRequest(BaseModel):
    project_id: str


class BuildStatusResponse(BaseModel):
    success: bool = True
    status: str  # "not_started" | "queued" | "in_progress" | "completed" | "failed"
    run_url: str | None = None
    conclusion: str | None = None  # "success" | "failure" | None


async def _get_swiftui_project(project_id: str, user: User, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
        )
    if get_project_stack(project)["frontend_framework"] != "swiftui":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This project isn't using SwiftUI — nothing to package here.",
        )
    return project


# ═══════════════════════════════════════════════════════════════
#  POST /build — trigger a simulator-verified Xcode project build
# ═══════════════════════════════════════════════════════════════
@router.post(
    "/build",
    summary="Build and verify this project's Xcode project via GitHub Actions",
)
async def trigger_build(
    payload: TriggerBuildRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Triggers build-swiftui-project.yml via repository_dispatch. That
    workflow calls back to GET /packaging/{project_id}/files (the same
    platform-agnostic endpoint every other packaging workflow uses),
    runs `xcodegen generate` + a simulator `xcodebuild build`, and zips
    the real project on success.
    """
    if not settings.GITHUB_TOKEN or not settings.GITHUB_REPO:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Packaging is not configured yet (missing GitHub credentials).",
        )

    project = await _get_swiftui_project(payload.project_id, user, db)

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
                f"likely to break the build: {bad_paths}. Regenerate the code before packaging."
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
        logger.error(
            f"Failed to trigger SwiftUI build: {response.status_code} {response.text}"
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to start the build. Please try again.",
        )

    return {
        "success": True,
        "message": (
            "Build started! This runs xcodegen + a simulator xcodebuild on a real macOS "
            "runner (a few minutes) to prove your app compiles — it does NOT produce a "
            "signed .ipa. Open the downloaded project in Xcode to run on a device with "
            "your own Apple Developer account. 🐯🍎"
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id}/status — poll build status
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/status",
    response_model=BuildStatusResponse,
    summary="Check the status of the most recent SwiftUI build",
)
async def get_build_status(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_swiftui_project(project_id, user, db)

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
            detail="Failed to check build status.",
        )

    # The run's display name is set via `run-name:` in the workflow file to
    # include the project_id, so we can find the run for THIS project instead
    # of assuming the single most recent repo-wide run belongs to us.
    runs = response.json().get("workflow_runs", [])
    matching = next((r for r in runs if project_id in (r.get("name") or "")), None)
    if matching is None:
        return BuildStatusResponse(status="not_started")

    return BuildStatusResponse(
        status=matching.get("status", "unknown"),
        conclusion=matching.get("conclusion"),
        run_url=matching.get("html_url"),
    )


# ═══════════════════════════════════════════════════════════════
#  GET /{project_id}/artifacts — list the packaged Xcode project zip
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/{project_id}/artifacts",
    summary="List available downloadable artifacts for a completed SwiftUI build",
)
async def list_build_artifacts(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_swiftui_project(project_id, user, db)

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
                detail="No completed build found for this project. Trigger one first.",
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
            detail="Build completed but no project zip artifact was found.",
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
    summary="Stream the packaged Xcode project zip for direct download",
)
async def download_build_artifact(
    project_id: str,
    artifact_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_swiftui_project(project_id, user, db)

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

    filename = f"{safe_filename(project.name)}-swiftui-{artifact_id}.zip"
    return StreamingResponse(
        stream_artifact(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
