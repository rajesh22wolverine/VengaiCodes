# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Share via QR API Routes
#  api/v1/share.py — The three QR share options (see
#  services/qr_share.py for why there are three), plus the receiving
#  side of the blueprint.
#
#  Endpoints (all owner-only unless noted):
#    POST   /{id}/links            new download link + its QR code
#    GET    /{id}/links            the project's links (never their tokens)
#    DELETE /{id}/links/{link_id}  turn a link off
#    GET    /d/{token}             PUBLIC — the ZIP a link points to
#    GET    /{id}/blueprint        the design as one QR code
#    POST   /blueprint/inspect     what a scanned blueprint contains
#    POST   /blueprint/import      a new project from a scanned blueprint
#    GET    /{id}/sequence         the whole bundle as QR frames
# ═══════════════════════════════════════════════════════════════

import hashlib
import ipaddress
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.stack_matrix import validate_stack
from app.api.v1.architecture import (
    build_ai_architecture,
    build_erd,
    build_system_diagram,
)
from app.api.v1.auth import get_current_active_user
from app.api.v1.export import (
    build_bundle_zip,
    build_export_filename,
    export_bundle_files,
)
from app.config import settings
from app.core.database import get_db
from app.models.project import AppCategory, Project, ProjectStatus, SDLCPhase
from app.models.project_share import ProjectShareLink
from app.models.user import User
from app.services import qr_share

logger = logging.getLogger("vengaicode.share")
router = APIRouter()

MAX_LINK_HOURS = 24 * 30


# ─── Schemas ───
class CreateLinkRequest(BaseModel):
    expires_in_hours: int = Field(24 * 7, ge=1, le=MAX_LINK_HOURS)


class BlueprintTextRequest(BaseModel):
    text: str = Field(..., max_length=10_000)


# ─── Helpers ───
async def _owned_project(db: AsyncSession, user: User, project_id: str) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
        )
    return project


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_base(request: Request) -> str:
    return (settings.PUBLIC_BASE_URL or str(request.base_url)).rstrip("/")


def link_reach(url: str) -> str:
    """Who can open a link: "anyone" (a public address), "same_network"
    (a private LAN address), or "this_device" (localhost). The QR only
    helps someone else when it's not "this_device"."""
    host = (urlsplit(url).hostname or "").lower()
    if host in ("localhost", "") or host.endswith(".localhost"):
        return "this_device"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return (
            "same_network"
            if host.endswith((".local", ".lan", ".internal"))
            else "anyone"
        )
    if ip.is_loopback:
        return "this_device"
    if ip.is_private or ip.is_link_local:
        return "same_network"
    return "anyone"


def _link_view(link: ProjectShareLink) -> dict:
    return {
        "id": link.id,
        "created_at": link.created_at.isoformat() if link.created_at else None,
        "expires_at": link.expires_at.isoformat(),
        "revoked": link.revoked_at is not None,
        "active": link.is_active(),
        "download_count": link.download_count,
        "last_downloaded_at": link.last_downloaded_at.isoformat()
        if link.last_downloaded_at
        else None,
    }


def _qr_error(e: qr_share.QrShareError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ═══════════════════════════════════════════════
#  1. Download link
# ═══════════════════════════════════════════════
_UNAVAILABLE_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Link not available</title></head>
<body style="font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;color:#222">
<h1 style="font-size:1.3rem">This download link isn't available</h1>
<p>It may have expired or been turned off by the person who shared it. Ask them for a new QR code.</p>
</body></html>"""


@router.get(
    "/d/{token}",
    summary="PUBLIC: download the project a share link points to",
    include_in_schema=False,
)
async def download_shared_project(token: str, db: AsyncSession = Depends(get_db)):
    # No sign-in: holding the link IS the permission. Every failure looks
    # the same, so the page never reveals whether a token ever existed.
    result = await db.execute(
        select(ProjectShareLink).where(ProjectShareLink.token_hash == _hash(token))
    )
    link = result.scalar_one_or_none()
    project = await db.get(Project, link.project_id) if link is not None else None
    if link is None or project is None or not link.is_active():
        return HTMLResponse(_UNAVAILABLE_PAGE, status_code=status.HTTP_404_NOT_FOUND)

    # The project as it is NOW — a link shares a project, not a snapshot.
    body = build_bundle_zip(export_bundle_files(project))
    link.download_count = (link.download_count or 0) + 1
    link.last_downloaded_at = datetime.now(timezone.utc)
    await db.commit()
    return Response(
        content=body,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{build_export_filename(project.name)}"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/{project_id}/links",
    status_code=status.HTTP_201_CREATED,
    summary="Create a download link + QR code",
)
async def create_share_link(
    project_id: str,
    payload: CreateLinkRequest,
    request: Request,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _owned_project(db, user, project_id)
    token = secrets.token_urlsafe(18)
    link = ProjectShareLink(
        project_id=project.id,
        user_id=user.id,
        token_hash=_hash(token),
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=payload.expires_in_hours),
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    # The token exists only in this response (and the QR made from it).
    url = f"{_public_base(request)}{settings.API_V1_PREFIX}/share/d/{token}"
    return {
        "success": True,
        "url": url,
        "reach": link_reach(url),
        "qr": qr_share.qr_image(url, error="m"),
        "link": _link_view(link),
    }


@router.get("/{project_id}/links", summary="List a project's download links")
async def list_share_links(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _owned_project(db, user, project_id)
    result = await db.execute(
        select(ProjectShareLink)
        .where(ProjectShareLink.project_id == project_id)
        .order_by(ProjectShareLink.created_at.desc())
    )
    return {
        "success": True,
        "links": [_link_view(link) for link in result.scalars().all()],
    }


@router.delete("/{project_id}/links/{link_id}", summary="Turn a download link off")
async def revoke_share_link(
    project_id: str,
    link_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _owned_project(db, user, project_id)
    link = await db.get(ProjectShareLink, link_id)
    if link is None or link.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Link not found."
        )
    if link.revoked_at is None:
        link.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    return {"success": True, "link": _link_view(link)}


# ═══════════════════════════════════════════════
#  2. Blueprint
# ═══════════════════════════════════════════════
@router.get("/{project_id}/blueprint", summary="The project's design as one QR code")
async def get_blueprint(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _owned_project(db, user, project_id)
    try:
        blueprint = qr_share.encode_blueprint(project)
        image = qr_share.qr_image(blueprint.text, error="l")
    except qr_share.QrShareError as e:
        raise _qr_error(e) from e
    return {
        "success": True,
        "text": blueprint.text,
        "qr": image,
        "compressed_bytes": blueprint.compressed_bytes,
        "omitted": blueprint.omitted,
        "table_count": len(blueprint.payload["tables"]),
        "endpoint_count": len(blueprint.payload.get("endpoints") or []),
    }


def _inspect(text: str) -> dict:
    try:
        return qr_share.decode_blueprint(text)
    except qr_share.QrShareError as e:
        raise _qr_error(e) from e


@router.post(
    "/blueprint/inspect", summary="What a scanned blueprint contains (saves nothing)"
)
async def inspect_blueprint(
    payload: BlueprintTextRequest, user: User = Depends(get_current_active_user)
):
    data = _inspect(payload.text)
    return {
        "success": True,
        "name": data["name"],
        "description": data["description"],
        "stack": data["stack"],
        "table_names": [str(t.get("name", "")) for t in data["tables"]],
        "endpoint_count": len(data["endpoints"]),
    }


@router.post(
    "/blueprint/import",
    status_code=status.HTTP_201_CREATED,
    summary="New project from a scanned blueprint",
)
async def import_blueprint(
    payload: BlueprintTextRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    data = _inspect(payload.text)
    notes: list[str] = []

    selected_stack = None
    if data["stack"]:
        validation = validate_stack(data["stack"])
        if validation["coherent"]:
            selected_stack = {
                **data["stack"],
                "buildable_now": validation["buildable_now"],
                "validated_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            notes.append(
                "The blueprint's stack isn't a valid combination, so the default stack will be used."
            )
    backend = (selected_stack or {}).get("backend_framework")

    stack_label = selected_stack or {}
    tech = data["tech_stack"]
    design_input = {
        "architecture_summary": data["summary"]
        or "Imported from a VengaiCode blueprint QR code.",
        "tech_stack": {
            "frontend": tech["frontend"]
            or stack_label.get("frontend_framework", "Not specified"),
            "backend": tech["backend"]
            or stack_label.get("backend_framework", "Not specified"),
            "database": tech["database"] or "Not specified",
            "hosting": tech["hosting"] or "Not specified",
        },
        "database_tables": data["tables"],
        "api_endpoints": data["endpoints"],
        "third_party_services": data["services"],
    }
    try:
        design, schema_notes = build_ai_architecture(design_input, backend)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This blueprint's tables couldn't be read — it may come from an incompatible VengaiCode version.",
        ) from e
    notes += schema_notes

    now = datetime.now(timezone.utc).isoformat()
    project = Project(
        user_id=user.id,
        name=data["name"],
        description=data["description"] or None,
        category=AppCategory.OTHER,
        platforms=[],
        status=ProjectStatus.IN_PROGRESS,
        # Lands on an approved Architecture: the design IS what arrived,
        # and No-AI code generation can rebuild the app from it right away.
        current_phase=SDLCPhase.ARCHITECTURE,
        phases_completed=["architecture"],
        understanding_score=0.0,
        ai_conversation_history=[],
        phase_started_at={"architecture": now},
        phase_completed_at={"architecture": now},
        change_requests=[],
        reference_apps=[],
        unique_features=[],
        selected_stack=selected_stack,
        architecture_data={
            "architecture": design.model_dump(),
            "user_approved": True,
            "approved_at": now,
            "generated_at": now,
            "imported_from": "blueprint_qr",
            "system_diagram": build_system_diagram(design),
            "schema_notes": notes,
        },
        uml_diagrams={"erd": build_erd(design.database_tables)},
    )
    project.progress_percent = project.get_progress_percent()
    db.add(project)
    user.projects_used += 1
    await db.commit()
    await db.refresh(project)
    logger.info(
        "Imported blueprint as project %s (%d tables)",
        project.id,
        len(design.database_tables),
    )
    return {
        "success": True,
        "project_id": project.id,
        "name": project.name,
        "notes": notes,
    }


# ═══════════════════════════════════════════════
#  3. QR sequence
# ═══════════════════════════════════════════════
@router.get(
    "/{project_id}/sequence",
    summary="The whole project (code + documents) as a sequence of QR codes",
)
async def get_sequence(
    project_id: str,
    frame_bytes: int = Query(qr_share.DEFAULT_FRAME_BYTES),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _owned_project(db, user, project_id)
    bundle = export_bundle_files(project)
    try:
        sequence = qr_share.build_sequence(project.name, bundle, frame_bytes)
    except qr_share.QrShareError as e:
        raise _qr_error(e) from e
    has_code = bool(((project.codegen_data or {}).get("codegen") or {}).get("files"))
    return {"success": True, **sequence, "has_code": has_code}
