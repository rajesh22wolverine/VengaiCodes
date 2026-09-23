# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Architecture API Routes (Sprint 5)
#  api/v1/architecture.py — Generate tech stack, schema, API list
#  from approved requirements + UI/UX design
# ═══════════════════════════════════════════════════════════════

import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.codegen_shared import _slug, get_ordered_pages
from app.ai.orchestrator import AIError, generate_text
from app.api.v1.auth import get_current_active_user
from app.api.v1.reverse_engineer import build_reverse_engineering_directive
from app.core.database import get_db
from app.models.project import Project, SDLCPhase
from app.models.user import User

logger = logging.getLogger("vengaicode.architecture")
router = APIRouter()


# ─── Schemas ───
class GenerateArchitectureRequest(BaseModel):
    project_id: str


class TechStack(BaseModel):
    frontend: str
    backend: str
    database: str
    hosting: str


class DatabaseTable(BaseModel):
    name: str
    purpose: str
    key_fields: list[str]


class APIEndpoint(BaseModel):
    method: str
    path: str
    purpose: str


class ADR(BaseModel):
    """One Architecture Decision Record — 'what was decided, and why',
    the closest thing to a real build-blueprint document this phase
    produces. Wires the previously-unused Project.architecture_data.adrs
    field the model schema already documented but nothing generated."""

    title: str
    decision: str
    rationale: str
    alternatives_considered: list[str] = []


class ArchitectureDesign(BaseModel):
    architecture_summary: str
    tech_stack: TechStack
    database_tables: list[DatabaseTable]
    api_endpoints: list[APIEndpoint]
    third_party_services: list[str]
    adrs: list[ADR] = []


class GenerateArchitectureResponse(BaseModel):
    success: bool = True
    architecture: ArchitectureDesign


class ApproveArchitectureRequest(BaseModel):
    project_id: str
    approved: bool = True


class EditArchitectureRequest(BaseModel):
    database_tables: list[DatabaseTable]
    api_endpoints: list[APIEndpoint]


# ─── Prompt builder ───
def build_stack_directive(selected_stack: dict | None) -> str:
    """
    Renders the user's explicit UI/backend/API pick (from the Stack step,
    /api/v1/stack) as a directive for the architecture prompt, so the pick
    actually reaches what the AI proposes instead of being ignored.
    """
    if not selected_stack:
        return ""

    directive = (
        f"\nThe user has EXPLICITLY chosen this tech stack — use EXACTLY this, "
        f"do not substitute a different framework or language:\n"
        f"- Frontend: {selected_stack.get('frontend_framework')} "
        f"({selected_stack.get('frontend_language')})\n"
        f"- Backend: {selected_stack.get('backend_framework')} "
        f"({selected_stack.get('backend_language')})\n"
        f"- API style: {selected_stack.get('api_style')}\n"
    )
    if not selected_stack.get("buildable_now", True):
        directive += (
            "Note: this stack is valid but not yet buildable by VengaiCode's code "
            "generator — the user has already been told code generation will "
            "substitute the closest buildable stack, so still describe the "
            "architecture in terms of their chosen stack here.\n"
        )
    return directive


def build_architecture_prompt(
    project_name: str,
    requirements: dict,
    pages: list[dict],
    selected_stack: dict | None = None,
    reverse_data: dict | None = None,
) -> str:
    features = ", ".join(requirements.get("key_features", []))
    platforms = ", ".join(requirements.get("platforms", []))
    screen_names = ", ".join(p.get("name", "") for p in pages)
    tech_hint = requirements.get("tech_recommendations", "")
    stack_directive = build_stack_directive(selected_stack)
    reverse_directive = build_reverse_engineering_directive(reverse_data)
    if reverse_directive:
        reverse_directive += (
            "Prefer recommending the SAME or a directly compatible technology to what was detected above, "
            "rather than inventing an unrelated stack — and base database_tables/api_endpoints on the real "
            'data entities/endpoints found above when they exist. Write the "adrs" entries as real decisions '
            'grounded in that detected evidence (e.g. "decision: keep the same backend framework", '
            '"rationale: it was directly detected in the source/site being reverse-engineered") rather than '
            "generic boilerplate reasoning.\n"
        )

    return f"""You are Baby Tiger 🐯, VengaiCode's AI architecture assistant. Based on this app's approved requirements and UI/UX design, propose a simple, open-source technical architecture.

App: {project_name}
Overview: {requirements.get("overview", "")}
Key features: {features}
Platforms: {platforms}
Screens: {screen_names}
Complexity hint: {tech_hint}
{stack_directive}
{reverse_directive}
If the app is a game, favor Godot Engine for the tech stack — it's fully open-source, capable of high-end 2D/3D games, and VengaiCode can build it into a real installable APK automatically. Only suggest Open 3D Engine (O3DE) instead if the user explicitly asked for an AAA-grade engine by name — O3DE has no automated build pipeline here, so it stays a downloadable project template the user builds themselves. If the app is not a game, favor simple open-source web or mobile technologies.

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "architecture_summary": "2-3 sentences describing the overall technical approach",
  "tech_stack": {{
    "frontend": "framework/library choice + 1 sentence why it fits",
    "backend": "framework/language choice + 1 sentence why it fits",
    "database": "database choice + 1 sentence why it fits",
    "hosting": "suggested free/open-source hosting approach"
  }},
  "database_tables": [
    {{"name": "table_name", "purpose": "1 sentence", "key_fields": ["field1", "field2", "field3"]}}
  ],
  "api_endpoints": [
    {{"method": "GET", "path": "/resource", "purpose": "1 sentence"}}
  ],
  "third_party_services": ["service1 (why needed)", "service2 (why needed)"],
  "adrs": [
    {{"title": "short decision title", "decision": "what was decided", "rationale": "why", "alternatives_considered": ["alternative 1", "alternative 2"]}}
  ]
}}

Generate 3-6 database tables and 6-10 core API endpoints covering the key features.
Favor simple, well-known, open-source technology suitable for the app's complexity.
Use realistic REST conventions for API endpoint paths and methods.

"third_party_services" MUST default to free, open-source, or self-hostable options the user
doesn't need to pay for or already own an account with (e.g. self-hosted Postfix/an SMTP relay
instead of SendGrid, self-hosted MinIO instead of S3, Firebase Cloud Messaging's free tier
instead of a paid push provider). Only name a specific paid/subscription service if the user
already said, in the overview/features/conversation above, that they have their own account or
credentials for it — and even then, phrase it as using THEIR OWN key/account (e.g. "Stripe,
using the user's own API key"), never implying VengaiCode provisions or pays for it. If a
feature genuinely needs a paid capability with no realistic open-source substitute, name it
plainly but flag that it requires the user's own subscription.
Generate 3-5 ADRs (Architecture Decision Records) covering the most consequential choices
(tech stack, database, one or two key structural decisions) — each a real trade-off with a
stated rationale and the alternatives that were passed over, not a restatement of the summary.

Respond with ONLY the JSON object, nothing else."""


def parse_ai_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


def _mermaid_safe_text(text: str) -> str:
    """Strips characters that break Mermaid node-label syntax. Applied to
    AI-generated tech_stack/service strings before embedding them in a
    diagram, since we don't control their exact punctuation."""
    return re.sub(r'["\[\]{}<>|]', "", text).strip()[:80]


def _mermaid_safe_id(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_") or "T"
    if safe[0].isdigit():
        safe = f"T_{safe}"
    return safe.upper()


def build_system_diagram(architecture: "ArchitectureDesign") -> str:
    """Deterministic Mermaid component diagram built straight from the
    already-structured tech_stack + third_party_services the AI call above
    just produced — no separate AI call, so it can't drift from or
    hallucinate beyond what generate_architecture actually decided."""
    ts = architecture.tech_stack
    lines = [
        "graph TD",
        f'  FE["Frontend<br/>{_mermaid_safe_text(ts.frontend)}"]',
        f'  BE["Backend<br/>{_mermaid_safe_text(ts.backend)}"]',
        f'  DB[("Database<br/>{_mermaid_safe_text(ts.database)}")]',
        "  FE --> BE",
        "  BE --> DB",
    ]
    for i, svc in enumerate(architecture.third_party_services):
        node = f"SVC{i}"
        lines.append(f'  {node}["{_mermaid_safe_text(svc)}"]')
        lines.append(f"  BE --> {node}")
    return "\n".join(lines)


def build_erd(database_tables: list["DatabaseTable"]) -> str:
    """Deterministic Mermaid ERD from the architecture's own database_tables
    — same rationale as build_system_diagram: derived from structured data
    we already trust, not a second AI call that could contradict it."""
    lines = ["erDiagram"]
    for table in database_tables:
        table_id = _mermaid_safe_id(table.name)
        lines.append(f"  {table_id} {{")
        for field in table.key_fields[:12]:
            field_id = re.sub(r"[^A-Za-z0-9_]", "_", field).strip("_") or "field"
            lines.append(f"    string {field_id}")
        lines.append("  }")
    return "\n".join(lines)


class ArchitectureEditError(RuntimeError):
    """A failure with a message meant for the user, not a stack trace."""


_VALID_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _validate_tables(tables: list[DatabaseTable]) -> None:
    seen_slugs: set[str] = set()
    for table in tables:
        name = (table.name or "").strip()
        if not name:
            raise ArchitectureEditError("Every table needs a name.")
        table.name = name
        slug = _slug(name)
        if slug in seen_slugs:
            raise ArchitectureEditError(
                f'Two tables both resolve to "{slug}" — table names must be distinct.'
            )
        seen_slugs.add(slug)

        field_slugs: set[str] = set()
        for field in table.key_fields:
            field_name = (field or "").strip()
            if not field_name:
                raise ArchitectureEditError(f'Table "{name}" has a blank field name.')
            field_slug = _slug(field_name)
            if field_slug in field_slugs:
                raise ArchitectureEditError(
                    f'Table "{name}" has the field "{field_name}" more than once.'
                )
            field_slugs.add(field_slug)


def _validate_endpoints(endpoints: list[APIEndpoint]) -> None:
    for endpoint in endpoints:
        method = (endpoint.method or "").strip().upper()
        if method not in _VALID_HTTP_METHODS:
            raise ArchitectureEditError(
                f'"{endpoint.method}" is not a valid HTTP method — use one of '
                f"{', '.join(sorted(_VALID_HTTP_METHODS))}."
            )
        endpoint.method = method

        path = (endpoint.path or "").strip()
        if not path.startswith("/"):
            raise ArchitectureEditError(
                f'Endpoint path "{endpoint.path}" must start with "/".'
            )
        endpoint.path = path


def apply_architecture_edit(
    architecture_data: dict | None,
    uml_diagrams: dict | None,
    database_tables: list[DatabaseTable],
    api_endpoints: list[APIEndpoint],
) -> tuple[dict, dict]:
    """Rebuilds the saved ArchitectureDesign with user-edited tables and
    endpoints, leaving every AI-authored field (summary, tech_stack,
    third_party_services, adrs) untouched, then regenerates the
    deterministic diagrams from the EDITED data via the exact same
    build_system_diagram()/build_erd() generate_architecture() itself
    uses — so an edited diagram is never stale or hand-drawn, just a
    live view of whatever is currently saved.

    Both the AI codegen path (codegen_runner.build_context()) and the
    deterministic codegen path (codegen_deterministic.py) read straight
    from architecture_data.architecture.{database_tables,api_endpoints}
    — an edit made here is honored by the next codegen run with zero
    codegen-side changes, the same way approving the AI's first draft
    always has been.

    Un-approves the architecture (codegen is gated on
    architecture_data["user_approved"]): an edit is a real change the
    user should re-review before it drives a build.
    """
    if not (architecture_data or {}).get("architecture"):
        raise ArchitectureEditError(
            "No architecture exists yet to edit — generate one first."
        )

    _validate_tables(database_tables)
    _validate_endpoints(api_endpoints)

    current = ArchitectureDesign(**architecture_data["architecture"])
    updated = current.model_copy(
        update={
            "database_tables": database_tables,
            "api_endpoints": api_endpoints,
        }
    )

    new_architecture_data = dict(architecture_data)
    new_architecture_data["architecture"] = updated.model_dump()
    new_architecture_data["system_diagram"] = build_system_diagram(updated)
    new_architecture_data["user_approved"] = False
    new_architecture_data.pop("approved_at", None)
    new_architecture_data["edited_at"] = datetime.now(timezone.utc).isoformat()

    new_uml_diagrams = {
        **(uml_diagrams or {}),
        "erd": build_erd(updated.database_tables),
    }

    return new_architecture_data, new_uml_diagrams


@router.post(
    "/generate",
    response_model=GenerateArchitectureResponse,
    summary="Generate architecture from approved requirements + UI/UX",
)
async def generate_architecture(
    payload: GenerateArchitectureRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the approved requirements + UI/UX design and generates a
    technical architecture — tech stack, database schema, API endpoints.
    """
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
        )

    if not project.uiux_data or not project.uiux_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="UI/UX design must be approved before generating architecture.",
        )

    frd = (project.requirements_data or {}).get("frd", {})
    pages = get_ordered_pages(project.uiux_data)

    try:
        prompt = build_architecture_prompt(
            project.name,
            frd,
            pages,
            project.selected_stack,
            project.reverse_engineering_data,
        )
        ai_result = await generate_text(prompt, user=user, db=db)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI architecture response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble planning your architecture. Please try again! 🐯",
        )

    architecture = ArchitectureDesign(**parsed)

    project.architecture_data = {
        "architecture": architecture.model_dump(),
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # Deterministic (no AI call) — derived from the architecture object
        # right above, so these can't drift from or contradict it.
        "system_diagram": build_system_diagram(architecture),
    }
    project.uml_diagrams = {
        **(project.uml_diagrams or {}),
        "erd": build_erd(architecture.database_tables),
    }
    await db.commit()

    return GenerateArchitectureResponse(architecture=architecture)


@router.get(
    "/{project_id}",
    summary="Get saved architecture design",
)
async def get_architecture(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a previously generated architecture design."""
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

    if not project.architecture_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No architecture generated yet.",
        )

    return {
        "success": True,
        "architecture": project.architecture_data.get("architecture"),
        "user_approved": project.architecture_data.get("user_approved", False),
        "generated_at": project.architecture_data.get("generated_at"),
        "system_diagram": project.architecture_data.get("system_diagram"),
        "erd": (project.uml_diagrams or {}).get("erd"),
    }


@router.put(
    "/{project_id}/edit",
    summary="Directly edit the saved architecture's tables/endpoints (no AI call)",
)
async def edit_architecture(
    project_id: str,
    payload: EditArchitectureRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lets a user add/rename/remove tables, fields and endpoints directly,
    instead of only reviewing what the AI proposed. See
    apply_architecture_edit()'s docstring for why this needs no codegen
    or packaging changes to take effect on a later build.
    """
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

    try:
        new_architecture_data, new_uml_diagrams = apply_architecture_edit(
            project.architecture_data,
            project.uml_diagrams,
            payload.database_tables,
            payload.api_endpoints,
        )
    except ArchitectureEditError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e

    project.architecture_data = new_architecture_data
    project.uml_diagrams = new_uml_diagrams
    await db.commit()

    return {
        "success": True,
        "architecture": new_architecture_data.get("architecture"),
        "user_approved": False,
        "generated_at": new_architecture_data.get("generated_at"),
        "system_diagram": new_architecture_data.get("system_diagram"),
        "erd": new_uml_diagrams.get("erd"),
        "message": "Changes saved — review and approve again before generating code.",
    }


@router.post(
    "/approve",
    summary="Approve architecture and move to next phase",
)
async def approve_architecture(
    payload: ApproveArchitectureRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves the generated architecture. Marks phase complete."""
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
        )

    if not project.architecture_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No architecture to approve.",
        )

    # Reassign the whole dict — required for SQLAlchemy JSON column
    # change tracking (in-place mutation is not detected)
    architecture_data = dict(project.architecture_data)
    architecture_data["user_approved"] = payload.approved
    architecture_data["approved_at"] = datetime.now(timezone.utc).isoformat()
    project.architecture_data = architecture_data

    if payload.approved:
        phases = project.phases_completed or []
        if "architecture" not in phases:
            phases.append("architecture")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.current_phase = SDLCPhase.API_BUILDER

    await db.commit()

    return {
        "success": True,
        "message": "Architecture approved! Next: API Builder 🐯"
        if payload.approved
        else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }
