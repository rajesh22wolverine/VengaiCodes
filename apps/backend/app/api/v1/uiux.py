# ═══════════════════════════════════════════════════════════════
#  VengaiCode — UI/UX Design API Routes (Sprint 4)
#  api/v1/uiux.py — Generate design system from approved requirements
# ═══════════════════════════════════════════════════════════════

import base64
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIError, generate_text, generate_vision
from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.core.storage import StorageError, fetch_bytes, upload_design_image
from app.models.project import Project, SDLCPhase
from app.models.user import User

logger = logging.getLogger("vengaicode.uiux")
router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


# ─── Schemas ───
class GenerateUIUXRequest(BaseModel):
    project_id: str


class ScreenDefinition(BaseModel):
    name: str
    purpose: str
    key_elements: list[str]


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


def build_design_to_code_prompt(page_name: str) -> str:
    return f"""You are Baby Tiger 🐯, VengaiCode's AI design-to-code assistant. \
Look at the attached page design image (for a page called "{page_name}") and \
recreate it as HTML + CSS as faithfully as you can — layout, spacing, colors, \
typography, and visible text/labels.

Rules:
- Use plain semantic HTML5 (no framework, no Tailwind classes) with a single \
  matching CSS stylesheet — this needs to be readable and directly editable
  by the user afterward, not a build pipeline.
- Match colors (as hex), approximate spacing/sizing, and text content as
  closely as you can infer from the image.
- Use placeholder text/images only where the design shows content you can't
  read clearly.

Respond with ONLY a JSON object, no markdown, no extra text:
{{
  "html": "<the full HTML markup for this page's body content, as a string>",
  "css": "<the full CSS, as a string>",
  "notes": "1 sentence on anything you weren't confident about"
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
        ai_result = await generate_text(prompt)
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
        "code_generated_at": None,
        "code_updated_at": None,
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
    prompt = build_design_to_code_prompt(design["page_name"])

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
    design["code_generated_at"] = datetime.now(timezone.utc).isoformat()

    project.uiux_data = uiux_data
    await db.commit()

    return {"success": True, "design": design}


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
