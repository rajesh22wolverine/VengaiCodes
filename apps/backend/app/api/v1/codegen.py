# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Code Generation API Routes (Sprint 6)
#  api/v1/codegen.py — Generate starter code skeleton from
#  approved architecture (models, API stubs, component shells)
#
#  SCOPE: This generates a runnable STARTER SKELETON, not a
#  finished app. SQLAlchemy models from database_tables, FastAPI
#  route stubs from api_endpoints, React component shells from
#  uiux screens. Testing/Export phases (later sprints) refine
#  and package the real thing.
# ═══════════════════════════════════════════════════════════════

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIError, generate_text
from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.project import Project, SDLCPhase
from app.models.user import User

logger = logging.getLogger("vengaicode.codegen")
router = APIRouter()


# ─── Schemas ───
class GenerateCodeRequest(BaseModel):
    project_id: str


class GeneratedFile(BaseModel):
    path: str
    language: str
    content: str
    description: str


class CodeGenResult(BaseModel):
    summary: str
    files: list[GeneratedFile]


class GenerateCodeResponse(BaseModel):
    success: bool = True
    codegen: CodeGenResult


class ApproveCodeRequest(BaseModel):
    project_id: str
    approved: bool = True


# ─── Prompt builder ───
def build_codegen_prompt(project_name: str, architecture: dict, uiux: dict) -> str:
    tech_stack = architecture.get("tech_stack", {})
    tables = architecture.get("database_tables", [])
    endpoints = architecture.get("api_endpoints", [])
    screens = uiux.get("screens", [])

    tables_text = "\n".join(
        f"- {t.get('name')}: {t.get('purpose')} (fields: {', '.join(t.get('key_fields', []))})"
        for t in tables
    )
    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}"
        for e in endpoints
    )
    screens_text = "\n".join(f"- {s.get('name')}: {s.get('purpose')}" for s in screens)

    return f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Based on this approved architecture, generate a STARTER CODE SKELETON — not a finished app, just correct, runnable scaffolding.

App: {project_name}
Backend: {tech_stack.get('backend', 'FastAPI + Python')}
Frontend: {tech_stack.get('frontend', 'React + TypeScript')}
Database: {tech_stack.get('database', 'PostgreSQL')}

Database tables:
{tables_text}

API endpoints:
{endpoints_text}

Screens:
{screens_text}

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "summary": "2-3 sentences on what was generated and what still needs to be built",
  "files": [
    {{
      "path": "backend/models/example.py",
      "language": "python",
      "content": "# actual code here, 20-60 lines, syntactically valid",
      "description": "1 sentence describing this file"
    }}
  ]
}}

Rules:
- Generate ONE file per database table (SQLAlchemy model, matching the fields given)
- Generate ONE file with FastAPI route stubs covering all the API endpoints (return
  placeholder/mock data, no real business logic yet — just correct routing structure)
- Generate ONE file per screen (React functional component, basic JSX structure,
  no styling logic, just the component shell with a TODO comment for content)
- Keep each file concise — 20-60 lines
- All code must be syntactically valid in its language
- Use realistic import statements matching the tech stack

Respond with ONLY the JSON object, nothing else."""


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
    response_model=GenerateCodeResponse,
    summary="Generate starter code skeleton from approved architecture",
)
async def generate_code(
    payload: GenerateCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the approved architecture and UI/UX design and generates a
    starter code skeleton — models, API route stubs, component shells.

    NOTE: This is intentionally scaffolding, not a finished app.
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

    if not project.architecture_data or not project.architecture_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Architecture must be approved before generating code.",
        )

    architecture = (project.architecture_data or {}).get("architecture", {})
    uiux = (project.uiux_data or {}).get("design", {})

    try:
        prompt = build_codegen_prompt(project.name, architecture, uiux)
        ai_result = await generate_text(prompt)
        parsed = parse_ai_json(ai_result["text"])
        print("===== GENERATED FILES =====")
        for f in parsed.get("files", []):
            print(f["path"])
            print("===========================")
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI codegen response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble writing your code. Please try again! 🐯",
        )

    codegen_result = CodeGenResult(**parsed)

    project.codegen_data = {
        "codegen": codegen_result.model_dump(),
        "files_generated": len(codegen_result.files),
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()

    return GenerateCodeResponse(codegen=codegen_result)


@router.get(
    "/{project_id}",
    summary="Get saved generated code",
)
async def get_code(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve previously generated code files."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.codegen_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No code generated yet.",
        )

    return {
        "success": True,
        "codegen": project.codegen_data.get("codegen"),
        "user_approved": project.codegen_data.get("user_approved", False),
        "generated_at": project.codegen_data.get("generated_at"),
    }


@router.post(
    "/approve",
    summary="Approve generated code and move to next phase",
)
async def approve_code(
    payload: ApproveCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves the generated code. Marks phase complete."""
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.codegen_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No generated code to approve.",
        )

    # Reassign whole dict — required for SQLAlchemy JSON column change tracking
    codegen_data = dict(project.codegen_data)
    codegen_data["user_approved"] = payload.approved
    codegen_data["approved_at"] = datetime.now(timezone.utc).isoformat()
    project.codegen_data = codegen_data

    if payload.approved:
        phases = project.phases_completed or []
        if "code_generation" not in phases:
            phases.append("code_generation")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.current_phase = SDLCPhase.TESTING

    await db.commit()

    return {
        "success": True,
        "message": "Code approved! Next: Testing 🐯" if payload.approved else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }
