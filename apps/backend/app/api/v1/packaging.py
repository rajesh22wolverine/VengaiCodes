# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Packaging API Routes (Windows builds)
#  api/v1/packaging.py — Trigger, poll, and download GitHub
#  Actions-built Windows binaries
#
#  Mirrors android_packaging.py's routing: a "web" category frontend
#  (React/Vue/Angular/Svelte/Plain HTML-JS) gets wrapped in Tauri/
#  WebView2 (build-windows-installer.yml, CONFIRMED WORKING — 5
#  consecutive successful runs); Flutter gets a REAL native (non-
#  WebView) build since its codegen already emits a complete Dart
#  project (build-windows-native-flutter.yml); Godot gets a real game
#  engine export (build-windows-game-godot.yml). O3DE and Jetpack
#  Compose/SwiftUI have no automated Windows pipeline — O3DE's engine
#  build is too heavy for CI, Compose/SwiftUI are mobile-only
#  frameworks with no Windows target at all — see
#  stack_matrix.CI_BUILDABLE_GAME_ENGINES for why Godot but not O3DE.
#
#  HONEST STATUS: build-windows-installer.yml is CONFIRMED WORKING.
#  The two new native/game workflows are written but UNTESTED end-to-
#  end — no Flutter SDK/Godot binary available in this dev environment
#  to live-verify, same class of limitation documented in
#  android_packaging.py's header for its own new pipelines. Requires:
#  - GITHUB_TOKEN (a GitHub Personal Access Token with 'repo' and
#    'workflow' scopes) set in Render environment variables
#  - GITHUB_REPO setting (e.g. "rajesh22wolverine/VengaiCodes")
#  - BUILD_SECRET setting, matching secrets.VENGAICODE_BUILD_SECRET
#    configured in the GitHub repo's Actions secrets
#  — same for all three workflows, no separate configuration needed.
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

logger = logging.getLogger("vengaicode.packaging")
router = APIRouter()

GITHUB_API = "https://api.github.com"

# frontend_framework -> (workflow YAML file, repository_dispatch event_type).
# Mirrors android_packaging.py's _WORKFLOW_ROUTES/_workflow_for_stack shape.
_NATIVE_WORKFLOW_ROUTES: dict[str, tuple[str, str]] = {
    "flutter": ("build-windows-native-flutter.yml", "build-windows-native-flutter-app"),
}
_WEB_WORKFLOW: tuple[str, str] = ("build-windows-installer.yml", "build-windows-app")
_GODOT_WORKFLOW: tuple[str, str] = ("build-windows-game-godot.yml", "build-windows-game-godot-app")


def _workflow_for_stack(stack_info: dict) -> tuple[str, str] | None:
    """Returns (workflow_file, dispatch_event_type), or None if this
    project's frontend has no automated Windows build pipeline."""
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
        "native_capabilities": project.codegen_data.get("native_capabilities", []),
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
                "This project's frontend doesn't have an automated Windows build pipeline yet "
                "(Jetpack Compose/SwiftUI are mobile-only; Open 3D Engine's build is too heavy "
                "to run in CI). Download the source and follow README_SETUP.md instead."
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
    Finds the most recent workflow run (for whichever of the three
    Windows pipelines this project's stack routes to) and returns its
    status. See module docstring for the known limitation on tracking
    concurrent builds.
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
        status=matching.get("status", "unknown"),  # queued | in_progress | completed
        conclusion=matching.get("conclusion"),  # success | failure | None
        run_url=matching.get("html_url"),
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
                "download_filename": f"{safe_filename(project.name)}-{a['name']}.zip",
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

    filename = f"{safe_filename(project.name)}-installer-{artifact_id}.zip"
    return StreamingResponse(
        stream_artifact(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
