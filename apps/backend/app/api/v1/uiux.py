# ═══════════════════════════════════════════════════════════════
#  VengaiCode — UI/UX Design API Routes (Sprint 4)
#  api/v1/uiux.py — Generate design system from approved requirements
# ═══════════════════════════════════════════════════════════════

import base64
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import uiux_runner
from app.ai.orchestrator import AIError, generate_vision, transcribe_audio
from app.ai.uiux_prompts import build_design_to_code_prompt, parse_ai_json
from app.api.v1.auth import get_current_active_user
from app.api.v1.figma import get_figma_token
from app.core.database import get_db
from app.core.figma_client import FigmaError, export_frame_png, parse_figma_url
from app.schemas.figma import ImportFigmaRequest
from app.core.storage import (
    StorageError, fetch_bytes, upload_design_image, upload_voice_note,
)
from app.models.generation_job import JOB_CANCELLED, JOB_SUCCEEDED
from app.models.project import Project, SDLCPhase
from app.models.user import User
from app.schemas.uiux import UIUXDesign
from app.services import generation_jobs

logger = logging.getLogger("vengaicode.uiux")
router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
ALLOWED_AUDIO_TYPES = {
    "audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4", "audio/x-m4a",
}


# ─── Schemas ───
class GenerateUIUXRequest(BaseModel):
    project_id: str


class GenerateUIUXResponse(BaseModel):
    success: bool = True
    design: UIUXDesign


class ApproveUIUXRequest(BaseModel):
    project_id: str
    approved: bool = True


class SaveDesignCodeRequest(BaseModel):
    html: str
    css: str


class SavedPage(BaseModel):
    id: str
    generated_html: Optional[str] = None
    generated_css: Optional[str] = None
    modules: list[str] = []


class SavePagesRequest(BaseModel):
    project_id: str
    pages: list[SavedPage]
    page_order: list[str]


# ───────────────────────────────────────────────
#  Design generation
#
#  The run lives in ai/uiux_runner.py and happens in a background job
#  (services/generation_jobs.py). It has to: the design system is one
#  AI call, but every screen's mockup is another, so the run's wall
#  time grows with the app while an HTTP timeout is a constant — and
#  the old inline version threw away every finished mockup when the
#  request died.
# ───────────────────────────────────────────────
async def _get_project(db: AsyncSession, user: User, project_id: str) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    return project


async def _get_designable_project(
    db: AsyncSession, user: User, project_id: str
) -> Project:
    project = await _get_project(db, user, project_id)

    if not project.requirements_data or not project.requirements_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requirements must be approved before generating UI/UX design.",
        )

    return project


@router.post(
    "/start",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start (or rejoin) a UI/UX design run and return immediately",
)
async def start_uiux(
    payload: GenerateUIUXRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Idempotent: called while a run is already going, it returns that run
    rather than starting a second one; called after one died partway, it
    resumes from the last finished screen instead of paying again for
    the mockups already generated.
    """
    project = await _get_designable_project(db, user, payload.project_id)
    job = await generation_jobs.start_or_resume(db, project, user, uiux_runner.RUNNER)
    return {"success": True, "job": generation_jobs.job_payload(job)}


@router.get(
    "/{project_id}/job",
    summary="Progress of this project's UI/UX design run",
)
async def get_uiux_job(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Cheap to poll — no AI call, just the job row."""
    project = await _get_project(db, user, project_id)
    job = await generation_jobs.get_latest_job(db, project.id, uiux_runner.PHASE)
    return {"success": True, "job": generation_jobs.job_payload(job)}


@router.post(
    "/cancel",
    summary="Ask this project's UI/UX design run to stop",
)
async def cancel_uiux(
    payload: GenerateUIUXRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stops after the screen currently being designed finishes — an AI
    call already in flight is paid for either way, so it's kept.
    Everything generated so far stays saved and a restart resumes.
    """
    project = await _get_project(db, user, payload.project_id)
    job = await generation_jobs.get_latest_job(db, project.id, uiux_runner.PHASE)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No UI/UX design run to cancel.",
        )

    job = await generation_jobs.request_cancel(db, job)
    return {"success": True, "job": generation_jobs.job_payload(job)}


@router.post(
    "/generate",
    response_model=GenerateUIUXResponse,
    summary="Generate UI/UX design system from approved requirements",
)
async def generate_uiux(
    payload: GenerateUIUXRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start the run and wait for it, returning the finished design system.

    Kept for clients that predate /start + /{id}/job polling. If this
    request times out the run still finishes and saves — the client
    picks it up from GET /uiux/{project_id} instead of losing it.
    """
    project = await _get_designable_project(db, user, payload.project_id)
    job = await generation_jobs.start_or_resume(db, project, user, uiux_runner.RUNNER)

    finished = await generation_jobs.wait_for_completion(job.id)

    if finished is None or generation_jobs.is_stale(finished):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Your design is still being generated. Reopen this screen to check on it.",
        )
    if finished.status == JOB_CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Design generation was cancelled.",
        )
    if finished.status != JOB_SUCCEEDED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=finished.error or "Design generation failed.",
        )

    await db.refresh(project)
    design = (project.uiux_data or {}).get("design", {})
    return GenerateUIUXResponse(design=UIUXDesign(**design))


@router.get(
    "/{project_id}",
    summary="Get saved UI/UX design",
)
async def get_uiux(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a previously generated UI/UX design system."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.uiux_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No UI/UX design generated yet.",
        )

    return {
        "success": True,
        "design": project.uiux_data.get("design"),
        "user_approved": project.uiux_data.get("user_approved", False),
        "generated_at": project.uiux_data.get("generated_at"),
        "uploaded_designs": project.uiux_data.get("uploaded_designs", []),
    }


@router.put(
    "/{project_id}/save",
    summary="Bulk-save all pending page edits and the page order in one action",
)
async def save_pages(
    project_id: str,
    payload: SavePagesRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Backs the single "Save" button in the editor: the user can edit several
    pages' HTML/CSS/modules and reorder the combined page list, then persist
    everything at once. This saved state (including page_order) is what
    architecture/codegen read once the design is approved — see
    app.ai.codegen_shared.get_ordered_pages().
    """
    project = await _get_owned_project(db, project_id, user)
    if not project.uiux_data or not project.uiux_data.get("design"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No UI/UX design to save.")

    uiux_data = dict(project.uiux_data)
    design = dict(uiux_data["design"])
    screens = [dict(s) for s in design.get("screens", [])]
    uploaded_designs = [dict(d) for d in uiux_data.get("uploaded_designs", [])]

    pages_by_id = {p.id: p for p in payload.pages}
    for screen in screens:
        page = pages_by_id.get(screen.get("id"))
        if page is not None:
            screen["generated_html"] = page.generated_html
            screen["generated_css"] = page.generated_css
            screen["modules"] = page.modules
    for design_entry in uploaded_designs:
        page = pages_by_id.get(design_entry.get("id"))
        if page is not None:
            design_entry["generated_html"] = page.generated_html
            design_entry["generated_css"] = page.generated_css
            design_entry["modules"] = page.modules
            design_entry["code_updated_at"] = datetime.now(timezone.utc).isoformat()

    design["screens"] = screens
    design["page_order"] = payload.page_order
    design["last_saved_at"] = datetime.now(timezone.utc).isoformat()
    uiux_data["design"] = design
    uiux_data["uploaded_designs"] = uploaded_designs
    project.uiux_data = uiux_data
    await db.commit()

    return {
        "success": True,
        "design": design,
        "uploaded_designs": uploaded_designs,
    }


@router.post(
    "/approve",
    summary="Approve UI/UX design and move to next phase",
)
async def approve_uiux(
    payload: ApproveUIUXRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves the generated UI/UX design. Marks phase complete."""
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.uiux_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No UI/UX design to approve.",
        )

    uiux_data = dict(project.uiux_data)
    uiux_data["user_approved"] = payload.approved
    uiux_data["approved_at"] = datetime.now(timezone.utc).isoformat()
    project.uiux_data = uiux_data

    if payload.approved:
        phases = project.phases_completed or []
        if "uiux" not in phases:
            phases.append("uiux")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.current_phase = SDLCPhase.ARCHITECTURE

    await db.commit()

    return {
        "success": True,
        "message": "UI/UX design approved! Next: Architecture 🐯" if payload.approved else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }


# ═══════════════════════════════════════════════════════════════
#  Design upload → code (design-to-code feature)
#
#  Lets a user upload their own page mockup/screenshot and have
#  Baby Tiger convert it into editable HTML/CSS via a vision model,
#  separate from the AI-generated design system above. Stored under
#  uiux_data["uploaded_designs"] — a list of:
#  {id, page_name, image_url, uploaded_at, generated_html,
#   generated_css, generation_notes, code_generated_at, code_updated_at}
# ═══════════════════════════════════════════════════════════════


async def _get_owned_project(db: AsyncSession, project_id: str, user: User) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


def _find_design(uiux_data: dict, design_id: str) -> dict:
    for design in uiux_data.get("uploaded_designs", []):
        if design["id"] == design_id:
            return design
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded design not found.")


@router.post(
    "/{project_id}/design/upload",
    summary="Upload a page design image to convert into code",
)
async def upload_design(
    project_id: str,
    page_name: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PNG, JPEG, or WebP images are supported.",
        )

    project = await _get_owned_project(db, project_id, user)
    content = await file.read()

    try:
        image_url = await upload_design_image(
            project_id, file.filename or "design.png", content, file.content_type
        )
    except StorageError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    uiux_data = dict(project.uiux_data or {})
    designs = list(uiux_data.get("uploaded_designs", []))
    new_design = {
        "id": uuid.uuid4().hex,
        "page_name": page_name,
        "image_url": image_url,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "generated_html": None,
        "generated_css": None,
        "generation_notes": None,
        "modules": [],
        "code_generated_at": None,
        "code_updated_at": None,
        "voice_note_url": None,
        "voice_note_transcript": None,
        "voice_note_uploaded_at": None,
    }
    designs.append(new_design)
    uiux_data["uploaded_designs"] = designs
    project.uiux_data = uiux_data
    await db.commit()

    return {"success": True, "design": new_design}


@router.post(
    "/{project_id}/design/import-figma",
    summary="Import a Figma frame as a page design",
)
async def import_figma_design(
    project_id: str,
    payload: ImportFigmaRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)

    token = await get_figma_token(db, user)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect your Figma account in Settings first.",
        )

    try:
        file_key, node_id = parse_figma_url(payload.figma_url)
        if not node_id:
            raise FigmaError(
                "That link doesn't point at a specific frame. In Figma, "
                "right-click the frame and choose 'Copy link to selection', "
                "then paste that link here."
            )
        export_url = await export_frame_png(token, file_key, node_id)
        content = await fetch_bytes(export_url)
    except FigmaError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to fetch Figma-exported image: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch the exported Figma frame.",
        )

    try:
        image_url = await upload_design_image(
            project_id, f"{payload.page_name}.png", content, "image/png"
        )
    except StorageError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    uiux_data = dict(project.uiux_data or {})
    designs = list(uiux_data.get("uploaded_designs", []))
    new_design = {
        "id": uuid.uuid4().hex,
        "page_name": payload.page_name,
        "image_url": image_url,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "generated_html": None,
        "generated_css": None,
        "generation_notes": None,
        "modules": [],
        "code_generated_at": None,
        "code_updated_at": None,
        "voice_note_url": None,
        "voice_note_transcript": None,
        "voice_note_uploaded_at": None,
        "source": "figma",
        "figma_file_key": file_key,
        "figma_node_id": node_id,
    }
    designs.append(new_design)
    uiux_data["uploaded_designs"] = designs
    project.uiux_data = uiux_data
    await db.commit()

    return {"success": True, "design": new_design}


@router.post(
    "/{project_id}/design/{design_id}/generate-code",
    summary="Generate HTML/CSS from an uploaded design image",
)
async def generate_design_code(
    project_id: str,
    design_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    uiux_data = dict(project.uiux_data or {})
    design = _find_design(uiux_data, design_id)

    try:
        image_bytes = await fetch_bytes(design["image_url"])
    except Exception as e:
        logger.error(f"Failed to fetch uploaded design image: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch the uploaded design image.",
        )

    media_type = "image/png" if design["image_url"].lower().endswith(".png") else "image/jpeg"
    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    prompt = build_design_to_code_prompt(design["page_name"], design.get("voice_note_transcript"))

    try:
        ai_result = await generate_vision(prompt, image_base64, media_type)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse design-to-code response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble reading that design. Please try again! 🐯",
        )

    design["generated_html"] = parsed.get("html", "")
    design["generated_css"] = parsed.get("css", "")
    design["generation_notes"] = parsed.get("notes")
    modules = parsed.get("modules")
    design["modules"] = modules if isinstance(modules, list) else []
    design["code_generated_at"] = datetime.now(timezone.utc).isoformat()

    project.uiux_data = uiux_data
    await db.commit()

    return {"success": True, "design": design}


@router.post(
    "/{project_id}/design/{design_id}/voice-note",
    summary="Attach a voice note to an uploaded design and transcribe it",
)
async def upload_voice_note_for_design(
    project_id: str,
    design_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stores the raw recording AND transcribes it via Groq Whisper — the
    transcript is folded into the design-to-code prompt as extra
    instructions the next time /generate-code runs for this design.
    """
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported audio format.",
        )

    project = await _get_owned_project(db, project_id, user)
    uiux_data = dict(project.uiux_data or {})
    design = _find_design(uiux_data, design_id)

    content = await file.read()

    try:
        voice_note_url = await upload_voice_note(
            project_id, file.filename or "voice-note.webm", content, file.content_type
        )
    except StorageError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    transcript = None
    try:
        transcription = await transcribe_audio(
            content, file.filename or "voice-note.webm", file.content_type
        )
        transcript = transcription["text"]
    except AIError as e:
        # Recording is still saved even if transcription fails — surface
        # the error but don't lose the upload.
        logger.warning(f"Voice note transcription failed: {e}")

    design["voice_note_url"] = voice_note_url
    design["voice_note_transcript"] = transcript
    design["voice_note_uploaded_at"] = datetime.now(timezone.utc).isoformat()

    project.uiux_data = uiux_data
    await db.commit()

    return {
        "success": True,
        "design": design,
        "transcription_failed": transcript is None,
    }


@router.put(
    "/{project_id}/design/{design_id}/code",
    summary="Save user edits to a design's generated HTML/CSS",
)
async def save_design_code(
    project_id: str,
    design_id: str,
    payload: SaveDesignCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    uiux_data = dict(project.uiux_data or {})
    design = _find_design(uiux_data, design_id)

    design["generated_html"] = payload.html
    design["generated_css"] = payload.css
    design["code_updated_at"] = datetime.now(timezone.utc).isoformat()

    project.uiux_data = uiux_data
    await db.commit()

    return {"success": True, "design": design}


@router.delete(
    "/{project_id}/design/{design_id}",
    summary="Delete an uploaded design",
)
async def delete_design(
    project_id: str,
    design_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    uiux_data = dict(project.uiux_data or {})
    designs = uiux_data.get("uploaded_designs", [])
    remaining = [d for d in designs if d["id"] != design_id]
    if len(remaining) == len(designs):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded design not found.")

    uiux_data["uploaded_designs"] = remaining
    project.uiux_data = uiux_data
    await db.commit()

    return {"success": True}
