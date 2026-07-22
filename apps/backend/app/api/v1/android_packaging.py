# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Android Packaging API Routes (per-project APK builds)
#  api/v1/android_packaging.py — Trigger, poll, and download
#  GitHub Actions-built Android APKs
#
#  Mirrors packaging.py (Windows installer builds) but targets one of
#  FOUR Android workflows, chosen by the project's frontend framework
#  (see _workflow_for_stack): a "web" category frontend (React/Vue/
#  Angular/Svelte/Plain HTML-JS) gets wrapped in a Capacitor WebView
#  (build-android-installer.yml, CONFIRMED WORKING — see that file's
#  header); Jetpack Compose and Flutter get REAL native (non-WebView)
#  builds since their codegen already emits a complete native project,
#  not a web bundle (build-android-native-compose.yml / -flutter.yml);
#  Godot gets a real game-engine export (build-android-game-godot.yml).
#  O3DE and SwiftUI have no automated pipeline (O3DE's engine build is
#  too heavy for CI; SwiftUI is iOS-only) and keep 400ing here — see
#  stack_matrix.CI_BUILDABLE_GAME_ENGINES for why Godot but not O3DE.
#
#  All four workflows call back to GET /packaging/{project_id}/files
#  to fetch the code to package — that endpoint is platform-agnostic.
#
#  HONEST STATUS: build-android-installer.yml is CONFIRMED WORKING
#  (one real successful end-to-end run). The three new native/game
#  workflows are written but UNTESTED end-to-end — no Android SDK/
#  Gradle/Flutter SDK/Godot binary is available in this environment to
#  live-verify them, same class of limitation documented in
#  jetpack_compose.py's and godot.py's headers. Requires the same
#  GITHUB_TOKEN / GITHUB_REPO / BUILD_SECRET settings for all four —
#  no separate configuration needed.
# ═══════════════════════════════════════════════════════════════

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stack_matrix import CI_BUILDABLE_GAME_ENGINES, FRONTEND_FRAMEWORKS, get_project_stack
from app.api.v1.auth import get_current_active_user
from app.config import settings
from app.core.database import get_db
from app.core.naming import safe_filename
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger("vengaicode.android_packaging")
router = APIRouter()

GITHUB_API = "https://api.github.com"

# frontend_framework -> (workflow YAML file, repository_dispatch event_type).
# "web" category frontends (react/vue/angular/svelte/html_css_js) all share
# one entry, added below the literal dict since there are 5 of them and
# they all route to the same Capacitor pipeline.
_NATIVE_WORKFLOW_ROUTES: dict[str, tuple[str, str]] = {
    "jetpack_compose": ("build-android-native-compose.yml", "build-android-native-compose-app"),
    "flutter": ("build-android-native-flutter.yml", "build-android-native-flutter-app"),
}
_WEB_WORKFLOW: tuple[str, str] = ("build-android-installer.yml", "build-android-installer-app")
_GODOT_WORKFLOW: tuple[str, str] = ("build-android-game-godot.yml", "build-android-game-godot-app")


def _workflow_for_stack(stack_info: dict) -> tuple[str, str] | None:
    """Returns (workflow_file, dispatch_event_type), or None if this
    project's frontend has no automated Android build pipeline."""
    fe = stack_info["frontend_framework"]
    if FRONTEND_FRAMEWORKS[fe]["category"] == "web":
        return _WEB_WORKFLOW
    if fe in CI_BUILDABLE_GAME_ENGINES:
        return _GODOT_WORKFLOW
    return _NATIVE_WORKFLOW_ROUTES.get(fe)


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

    stack_info = get_project_stack(project)
    route = _workflow_for_stack(stack_info)
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This project's frontend doesn't have an automated Android build pipeline yet "
                "(SwiftUI is iOS-only; Open 3D Engine's build is too heavy to run in CI). "
                "Download the source and follow README_SETUP.md instead."
            ),
        )
    _, event_type = route

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/dispatches",
            headers={
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "event_type": event_type,
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

    route = _workflow_for_stack(get_project_stack(project))
    if route is None:
        return BuildStatusResponse(status="not_started")
    workflow_file, _ = route

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/workflows/"
            f"{workflow_file}/runs",
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

    route = _workflow_for_stack(get_project_stack(project))
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed build found for this project. Trigger a build first.",
        )
    workflow_file, _ = route

    async with httpx.AsyncClient(timeout=30.0) as client:
        runs_response = await client.get(
            f"{GITHUB_API}/repos/{settings.GITHUB_REPO}/actions/workflows/"
            f"{workflow_file}/runs",
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
                detail="No completed build found for this project. Trigger a build first.",
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
            detail="Build completed but no APK artifact was found.",
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

    filename = f"{safe_filename(project.name)}-android-{artifact_id}.zip"
    return StreamingResponse(
        stream_artifact(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
