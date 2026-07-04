# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Testing API Routes (Sprint 7)
#  api/v1/testing.py — Generate test file stubs from approved
#  architecture + generated code
#
#  SCOPE (honest): This generates TEST CODE FILES (pytest/jest
#  stubs), same pattern as codegen.py — it does NOT execute any
#  code. There is no code-execution sandbox in this system.
#  Actually running tests against real generated code is a much
#  bigger, separate capability (would need a sandboxed execution
#  environment) and is explicitly out of scope here.
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

logger = logging.getLogger("vengaicode.testing")
router = APIRouter()


# ─── Schemas ───
class GenerateTestsRequest(BaseModel):
    project_id: str


class GeneratedTestFile(BaseModel):
    path: str
    language: str
    content: str
    description: str
    tests_what: str  # which generated file/endpoint this test targets


class TestPlanResult(BaseModel):
    summary: str
    test_files: list[GeneratedTestFile]
    coverage_notes: str  # honest note on what IS and ISN'T covered


class GenerateTestsResponse(BaseModel):
    success: bool = True
    testing: TestPlanResult


class ApproveTestsRequest(BaseModel):
    project_id: str
    approved: bool = True


# ─── Prompt builder ───
def build_testing_prompt(project_name: str, architecture: dict, codegen: dict) -> str:
    endpoints = architecture.get("api_endpoints", [])
    files = codegen.get("files", [])

    endpoints_text = "\n".join(
        f"- {e.get('method')} {e.get('path')}: {e.get('purpose')}"
        for e in endpoints
    )
    files_text = "\n".join(
        f"- {f.get('path')} ({f.get('language')}): {f.get('description')}"
        for f in files
    )

    return f"""You are Baby Tiger 🐯, VengaiCode's AI testing assistant. Based on this app's approved architecture and generated starter code, write TEST FILE STUBS — not full test suites, just well-structured starting points.

App: {project_name}

API endpoints:
{endpoints_text}

Generated files:
{files_text}

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "summary": "2-3 sentences on what test coverage was generated and its purpose",
  "test_files": [
    {{
      "path": "backend/tests/test_example.py",
      "language": "python",
      "content": "# actual pytest test code, 15-40 lines, syntactically valid",
      "description": "1 sentence describing what this test file covers",
      "tests_what": "the file or endpoint this targets, e.g. 'POST /api/workouts'"
    }}
  ],
  "coverage_notes": "1-2 honest sentences on what these test stubs DO cover and what they DON'T (e.g. happy-path only, no edge cases, no auth failure cases, not yet runnable without a live database)"
}}

Rules:
- Generate ONE test file per API endpoint (pytest style, using FastAPI's TestClient pattern),
  covering the basic happy-path request/response shape
- Generate ONE test file for frontend components (basic render test, e.g. using
  React Testing Library patterns) covering 2-3 key components
- Keep each file concise — 15-40 lines
- These are STUBS meant to compile/parse correctly, not necessarily pass against
  real running code, since there's no database or server connected yet
- Be honest in coverage_notes about the limitations

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
    response_model=GenerateTestsResponse,
    summary="Generate test file stubs from approved code",
)
async def generate_tests(
    payload: GenerateTestsRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the approved architecture and generated code, and produces
    test file stubs. Does NOT execute any code — no sandbox exists.
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

    if not project.codegen_data or not project.codegen_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generated code must be approved before generating tests.",
        )

    architecture = (project.architecture_data or {}).get("architecture", {})
    codegen = (project.codegen_data or {}).get("codegen", {})

    try:
        prompt = build_testing_prompt(project.name, architecture, codegen)
        ai_result = await generate_text(prompt)
        parsed = parse_ai_json(ai_result["text"])
    except AIError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI testing response: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Baby Tiger had trouble writing your tests. Please try again! 🐯",
        )

    testing_result = TestPlanResult(**parsed)

    project.testing_data = {
        "testing": testing_result.model_dump(),
        "total_tests": len(testing_result.test_files),
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()

    return GenerateTestsResponse(testing=testing_result)


@router.get(
    "/{project_id}",
    summary="Get saved test files",
)
async def get_tests(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve previously generated test files."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.testing_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No tests generated yet.",
        )

    return {
        "success": True,
        "testing": project.testing_data.get("testing"),
        "user_approved": project.testing_data.get("user_approved", False),
        "generated_at": project.testing_data.get("generated_at"),
    }


@router.post(
    "/approve",
    summary="Approve tests and move to next phase",
)
async def approve_tests(
    payload: ApproveTestsRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """User approves the generated tests. Marks phase complete."""
    result = await db.execute(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == user.id,
        )
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if not project.testing_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tests to approve.",
        )

    # Reassign whole dict — required for SQLAlchemy JSON column change tracking
    testing_data = dict(project.testing_data)
    testing_data["user_approved"] = payload.approved
    testing_data["approved_at"] = datetime.now(timezone.utc).isoformat()
    project.testing_data = testing_data

    if payload.approved:
        phases = project.phases_completed or []
        if "testing" not in phases:
            phases.append("testing")
        project.phases_completed = phases
        project.progress_percent = project.get_progress_percent()
        project.current_phase = SDLCPhase.EXPORT

    await db.commit()

    return {
        "success": True,
        "message": "Tests approved! Next: Export 🐯" if payload.approved else "Feedback noted.",
        "progress_percent": project.progress_percent,
    }
