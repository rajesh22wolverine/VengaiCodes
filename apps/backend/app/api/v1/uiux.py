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

from app.ai.orchestrator import AIError, generate_text, generate_vision, transcribe_audio
from app.api.v1.auth import get_current_active_user
from app.api.v1.figma import get_figma_token
from app.core.database import get_db
from app.core.figma_client import FigmaError, export_frame_png, parse_figma_url
from app.schemas.figma import ImportFigmaRequest
from app.core.storage import (
    StorageError, fetch_bytes, upload_design_image, upload_voice_note,
)
from app.models.project import Project, SDLCPhase
from app.models.user import User

logger = logging.getLogger("vengaicode.uiux")
router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
ALLOWED_AUDIO_TYPES = {
    "audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4", "audio/x-m4a",
}


# ─── Schemas ───
class GenerateUIUXRequest(BaseModel):
    project_id: str


class ScreenDefinition(BaseModel):
    id: str = ""
    name: str
    purpose: str
    key_elements: list[str]
    generated_html: Optional[str] = None
    generated_css: Optional[str] = None
    modules: list[str] = []


class ColorPalette(BaseModel):
    primary: str
    secondary: str
    accent: str
    background: str
    text: str


class UIUXDesign(BaseModel):
    design_style: str
    color_palette: ColorPalette
    typography: str
    screens: list[ScreenDefinition]
    components: list[str]
    navigation_pattern: str


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


# ─── Prompt builder ───
def build_uiux_prompt(project_name: str, requirements: dict) -> str:
    features = ", ".join(requirements.get("key_features", []))
    platforms = ", ".join(requirements.get("platforms", []))

    return f"""You are Baby Tiger 🐯, VengaiCode's AI design assistant. Based on this app's approved requirements, design a UI/UX system.

App: {project_name}
Overview: {requirements.get('overview', '')}
Key features: {features}
Platforms: {platforms}
Target users: {requirements.get('target_users', '')}

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "design_style": "1 sentence describing the visual style (e.g. 'clean and minimal with rounded corners, energetic accent colors')",
  "color_palette": {{
    "primary": "#hexcode",
    "secondary": "#hexcode",
    "accent": "#hexcode",
    "background": "#hexcode",
    "text": "#hexcode"
  }},
  "typography": "1 sentence on font choice and why it fits (e.g. 'Inter for a modern, friendly, highly readable feel')",
  "screens": [
    {{"name": "Screen Name", "purpose": "1 sentence what this screen does", "key_elements": ["element1", "element2", "element3"]}}
  ],
  "components": ["reusable component 1", "reusable component 2", "reusable component 3"],
  "navigation_pattern": "1 sentence describing how users move between screens (e.g. 'bottom tab bar with 4 main sections')"
}}

Generate 4-6 screens covering the core user journey. Pick colors that suit the app's purpose and target users. Choose real, valid hex codes.

Respond with ONLY the JSON object, nothing else."""


def build_design_to_code_prompt(page_name: str, voice_instructions: Optional[str] = None) -> str:
    voice_section = ""
    if voice_instructions:
        voice_section = f"""

The user also recorded a voice note with additional instructions — \
follow these along with what you see in the image:
"{voice_instructions}\""""

    return f"""You are Baby Tiger 🐯, VengaiCode's AI design-to-code assistant. \
Look at the attached page design image (for a page called "{page_name}") and \
recreate it as HTML + CSS as faithfully as you can — layout, spacing, colors, \
typography, and visible text/labels.{voice_section}

Rules:
- Use plain semantic HTML5 (no framework, no Tailwind classes) with a single \
  matching CSS stylesheet — this needs to be readable and directly editable
  by the user afterward, not a build pipeline.
- Match colors (as hex), approximate spacing/sizing, and text content as
  closely as you can infer from the image.
- Use placeholder text/images only where the design shows content you can't
  read clearly.
- Wrap each distinct structural section you identify in its own top-level
  container element carrying a `data-veng-module="<name>"` attribute, where
  `<name>` exactly matches one entry of the "modules" array you return below
  (e.g. `<header data-veng-module="Header nav">...</header>`). This is what
  lets the editor move/reorder whole sections later — every module you
  report must correspond to exactly one real, addressable element.

Respond with ONLY a JSON object, no markdown, no extra text:
{{
  "html": "<the full HTML markup for this page's body content, as a string>",
  "css": "<the full CSS, as a string>",
  "notes": "1 sentence on anything you weren't confident about",
  "modules": ["3 to 6 short names for the distinct structural sections/components you see, e.g. 'Header nav', 'Hero banner', 'Pricing cards', 'Footer'"]
}}"""


def build_screen_to_code_prompt(
    screen: dict, design_style: str, color_palette: dict, typography: str
) -> str:
    key_elements = ", ".join(screen.get("key_elements", []))
    palette_text = ", ".join(f"{k}: {v}" for k, v in color_palette.items())

    return f"""You are Baby Tiger 🐯, VengaiCode's AI design assistant. Design a single \
page mockup, as HTML + CSS, for the "{screen.get('name', 'Screen')}" screen of this app.

Screen purpose: {screen.get('purpose', '')}
Key elements this screen needs: {key_elements}

Match the app's design system:
- Style: {design_style}
- Color palette: {palette_text}
- Typography: {typography}

Rules:
- Use plain semantic HTML5 (no framework, no Tailwind classes) with a single \
  matching CSS stylesheet — this needs to be readable and directly editable
  by the user afterward, not a build pipeline.
- Use real hex colors from the palette above, and reflect the stated style
  and typography choice.
- Use realistic placeholder text/labels appropriate to the screen's purpose
  and key elements — no lorem ipsum.
- Wrap each distinct structural section you create in its own top-level
  container element carrying a `data-veng-module="<name>"` attribute, where
  `<name>` exactly matches one entry of the "modules" array you return below
  (e.g. `<header data-veng-module="Header nav">...</header>`). This is what
  lets the editor move/reorder whole sections later — every module you
  report must correspond to exactly one real, addressable element.

Respond with ONLY a JSON object, no markdown, no extra text:
{{
  "html": "<the full HTML markup for this page's body content, as a string>",
  "css": "<the full CSS, as a string>",
  "notes": "1 sentence on anything you weren't confident about",
  "modules": ["3 to 6 short names for the distinct structural sections you created, e.g. 'Header nav', 'Hero banner', 'Pricing cards', 'Footer'"]
}}"""


def parse_ai_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


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
    Takes the approved requirements document and generates a UI/UX
    design system — colors, typography, screens, components.
    """
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.requirements_data or not project.requirements_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requirements must be approved before generating UI/UX design.",
        )

    frd = project.requirements_data.get("frd", {})

    try:
        prompt = build_uiux_prompt(project.name, frd)
        ai_result = await generate_text(prompt, user=user, db=db)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI UI/UX response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble designing your app. Please try again! 🐯",
        )

    design = UIUXDesign(**parsed)

    for screen in design.screens:
        screen.id = uuid.uuid4().hex

    palette_dict = design.color_palette.model_dump()

    async def _mockup_for(screen: ScreenDefinition) -> None:
        try:
            screen_prompt = build_screen_to_code_prompt(
                screen.model_dump(), design.design_style, palette_dict, design.typography
            )
            screen_result = await generate_text(screen_prompt, user=user, db=db)
            screen_parsed = parse_ai_json(screen_result["text"])
            screen.generated_html = screen_parsed.get("html")
            screen.generated_css = screen_parsed.get("css")
            modules = screen_parsed.get("modules")
            screen.modules = modules if isinstance(modules, list) else []
        except (AIError, json.JSONDecodeError, KeyError, IndexError) as e:
            # Non-fatal — the design system itself already succeeded. The
            # screen just falls back to a text-only card until the user
            # regenerates or uploads their own mockup for it.
            logger.warning(f"Auto mockup generation failed for screen '{screen.name}': {e}")

    # Sequential, NOT asyncio.gather(). Every _mockup_for() call reaches
    # generate_text(user=..., db=...), which uses this request's single
    # AsyncSession — it queries the model bag and, for platform-default
    # configs, does `user.ai_tokens_used += ...; await db.commit()`.
    # Fanning that out concurrently broke three ways at once:
    #   1. AsyncSession is not safe for concurrent use. Two screens
    #      touching it at the same time raised
    #      "IllegalStateChangeError: Method 'close()' can't be called
    #      here; method '_connection_for_bind()' is already in progress"
    #      in production.
    #   2. ai_tokens_used is a read-modify-write, so parallel screens lost
    #      each other's updates and the platform quota under-counted.
    #   3. N screens hit the provider simultaneously against a per-minute
    #      token ceiling (Groq's free tier is 8k TPM), so the burst just
    #      turned into 429s and retry backoff — no real speedup anyway.
    # Making these concurrent again needs generate_text() split into
    # "resolve the bag" (one DB hit up front) and "call the provider"
    # (no session), with token metering summed once at the end.
    for screen in design.screens:
        await _mockup_for(screen)

    project.uiux_data = {
        "design": design.model_dump(),
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()

    return GenerateUIUXResponse(design=design)


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
