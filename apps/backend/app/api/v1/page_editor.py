# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Page Editor API Routes
#  api/v1/page_editor.py — Analyze and edit a real page with ZERO AI.
#
#  Every route here is a pure deterministic transform over HTML/CSS
#  (see services/page_engine.py and services/page_commands.py): no
#  model call, no network, no token spend, same input -> same output
#  every time. That's what makes these safe to run on every keystroke
#  in an editor UI, unlike the AI-backed design-to-code route in
#  uiux.py which costs a generation per call and can't guarantee it
#  changed only what was asked.
#
#  Each route works two ways:
#    - stateless: pass html/css in the body, get the result back
#    - stored:    pass project_id + design_id and it loads the design
#                 from uiux_data["uploaded_designs"], applies, and (for
#                 edits) saves it back — so a big page never has to
#                 round-trip through the client.
# ═══════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.project import Project
from app.models.user import User
from app.services.page_commands import SUPPORTED_PHRASINGS, parse_commands
from app.services.page_engine import Page, PageEditError, edit_page

logger = logging.getLogger("vengaicode.page_editor")
router = APIRouter()

MAX_PAGE_BYTES = 2_000_000


# ─── Schemas ───
class PageSource(BaseModel):
    """Either inline html/css, or a pointer at a stored design."""
    html: Optional[str] = None
    css: Optional[str] = ""
    project_id: Optional[str] = None
    design_id: Optional[str] = None


class AnalyzeRequest(PageSource):
    pass


class EditRequest(PageSource):
    edits: list[dict] = Field(..., min_length=1)
    save: bool = True


class CommandRequest(PageSource):
    command: str = Field(..., min_length=1, max_length=2000)
    # Default False: a command is a proposal until the user sees what it
    # would do. The UI shows the diff, then re-posts with apply=true.
    apply: bool = False
    save: bool = True


# ─── Loading / saving a stored design ───
async def _load_design(db: AsyncSession, user: User, project_id: str, design_id: str) -> tuple[Project, dict, dict]:
    result = await db.execute(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")

    uiux_data = dict(project.uiux_data or {})
    for design in uiux_data.get("uploaded_designs", []):
        if design.get("id") == design_id:
            return project, uiux_data, design
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Uploaded design not found.")


async def _resolve_source(
    payload: PageSource, db: AsyncSession, user: User
) -> tuple[str, str, Optional[tuple[Project, dict, dict]]]:
    if payload.project_id and payload.design_id:
        project, uiux_data, design = await _load_design(db, user, payload.project_id, payload.design_id)
        html = design.get("generated_html") or ""
        if not html.strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "That design has no HTML yet — generate or save its code first.",
            )
        return html, design.get("generated_css") or "", (project, uiux_data, design)

    if payload.html is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Send either html (with optional css), or project_id + design_id.",
        )
    if len(payload.html) > MAX_PAGE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "That page is too large to edit here.")
    return payload.html, payload.css or "", None


async def _save_design(db: AsyncSession, stored: tuple[Project, dict, dict], html: str, css: str) -> dict:
    project, uiux_data, design = stored
    design["generated_html"] = html
    design["generated_css"] = css
    design["code_updated_at"] = datetime.now(timezone.utc).isoformat()
    # Reassign the whole dict — SQLAlchemy doesn't track in-place JSON edits.
    project.uiux_data = uiux_data
    await db.commit()
    return design


# ─── Routes ───
@router.post("/analyze", summary="Inventory everything on a page (no AI)")
async def analyze(
    payload: AnalyzeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    html, css, _stored = await _resolve_source(payload, db, user)
    page = Page(html, css)
    result = page.analyze()
    return {"success": True, **result}


@router.post("/edit", summary="Apply structured edits to a page (no AI)")
async def edit(
    payload: EditRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    html, css, stored = await _resolve_source(payload, db, user)

    try:
        result = edit_page(html, css, payload.edits)
    except PageEditError as error:
        # A refusal, not a failure: the edit was unambiguously not
        # applicable, and guessing at what was meant is exactly what this
        # engine exists to avoid.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error))

    saved = False
    if stored and payload.save:
        await _save_design(db, stored, result["html"], result["css"])
        saved = True

    return {"success": True, "saved": saved, **result}


@router.post("/command", summary="Turn a plain-English change into edits and apply it (no AI)")
async def command(
    payload: CommandRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    html, css, stored = await _resolve_source(payload, db, user)
    page = Page(html, css)

    parsed = parse_commands(payload.command, page)
    understood = [p for p in parsed if p.understood]
    rejected = [p for p in parsed if not p.understood]

    response: dict[str, Any] = {
        "success": True,
        "understood": [{"explanation": p.explanation, "edits": p.edits} for p in understood],
        "not_understood": [
            {"error": p.error, "suggestions": p.suggestions} for p in rejected
        ],
        "supported_phrasings": SUPPORTED_PHRASINGS if rejected else [],
        "applied": False,
        "saved": False,
    }

    if not understood:
        return response

    edits = [edit_op for p in understood for edit_op in p.edits]
    try:
        result = edit_page(html, css, edits)
    except PageEditError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error))

    response["preview"] = {"html": result["html"], "css": result["css"], "html_changed": result["html_changed"], "css_changed": result["css_changed"]}

    if payload.apply:
        response["applied"] = True
        response["html"] = result["html"]
        response["css"] = result["css"]
        if stored and payload.save:
            await _save_design(db, stored, result["html"], result["css"])
            response["saved"] = True

    return response
