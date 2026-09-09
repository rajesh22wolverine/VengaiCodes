# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Code Generation API Routes
#  api/v1/codegen.py — Turn approved architecture into a real, working
#  implementation: one dedicated AI call per model/route/screen file
#  (each gets its own full token budget instead of many files sharing
#  one small JSON response), then a deterministic wiring pass that
#  stitches them into an installable, startable project.
#
#  The generation itself lives in ai/codegen_runner.py and runs as a
#  background job (services/generation_jobs.py). It has to: the run
#  makes one AI call per database table and per screen, so its wall
#  time grows with the project while an HTTP timeout is a constant —
#  a big enough project could never finish inside one request, and the
#  old inline version threw away every finished file when the request
#  died.
#
#  Endpoints:
#    POST /generate      — start/resume, then wait for the result
#                          (kept for already-installed clients)
#    POST /start         — start/resume and return immediately
#    GET  /{id}/job      — progress of the current run
#    POST /cancel        — ask the current run to stop
# ═══════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import codegen_runner
from app.ai.codegen_shared import GeneratedFile
from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.models.generation_job import JOB_CANCELLED, JOB_SUCCEEDED
from app.models.project import Project, SDLCPhase
from app.models.user import User
from app.services import generation_jobs

logger = logging.getLogger("vengaicode.codegen")
router = APIRouter()


# ─── Schemas ───
class GenerateCodeRequest(BaseModel):
    project_id: str


class CodeGenResult(BaseModel):
    summary: str
    files: list[GeneratedFile]


class StackUsed(BaseModel):
    codegen_target: str  # "react_fastapi" | "vue_express" | "o3de"
    source: str  # "selected_stack" | "downgraded_selection" | "legacy_o3de_detection" | "fallback_default"
    fallback_reason: str | None = None


class GenerateCodeResponse(BaseModel):
    success: bool = True
    codegen: CodeGenResult
    stack_used: StackUsed


class ApproveCodeRequest(BaseModel):
    project_id: str
    approved: bool = True


# ───────────────────────────────────────────────
#  Shared helpers
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


async def _get_generatable_project(
    db: AsyncSession, user: User, project_id: str
) -> Project:
    project = await _get_project(db, user, project_id)

    if not project.architecture_data or not project.architecture_data.get("user_approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Architecture must be approved before generating code.",
        )

    return project


def _saved_result(project: Project) -> GenerateCodeResponse:
    data = project.codegen_data or {}
    # Projects generated before stack_used was recorded have none saved;
    # resolving the stack is deterministic, so recompute rather than 500.
    stack_used = data.get("stack_used") or codegen_runner.build_context(project)["stack_info"]
    return GenerateCodeResponse(
        codegen=CodeGenResult(**data.get("codegen", {"summary": "", "files": []})),
        stack_used=StackUsed(**stack_used),
    )


# ───────────────────────────────────────────────
#  Generation
# ───────────────────────────────────────────────
@router.post(
    "/start",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start (or rejoin) a code generation run and return immediately",
)
async def start_code_generation(
    payload: GenerateCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Kicks the run off in the background and answers straight away with a
    job to poll — no request is held open for the length of a build.

    Idempotent: called while a run is already going, it returns that run
    rather than starting a second one. Called after a run died partway
    (a redeploy, a provider outage), it resumes from the last finished
    file instead of paying for those files again.
    """
    project = await _get_generatable_project(db, user, payload.project_id)
    job = await generation_jobs.start_or_resume(db, project, user, codegen_runner.RUNNER)
    return {"success": True, "job": generation_jobs.job_payload(job)}


@router.get(
    "/{project_id}/job",
    summary="Progress of this project's code generation run",
)
async def get_code_generation_job(
    project_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Cheap to poll — no AI call, just the job row."""
    project = await _get_project(db, user, project_id)
    job = await generation_jobs.get_latest_job(db, project.id, codegen_runner.PHASE)
    return {"success": True, "job": generation_jobs.job_payload(job)}


@router.post(
    "/cancel",
    summary="Ask this project's code generation run to stop",
)
async def cancel_code_generation(
    payload: GenerateCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stops after the file currently being written finishes — an AI call
    already in flight is paid for either way, so it's kept. Everything
    generated so far stays saved, and starting again resumes from there.
    """
    project = await _get_project(db, user, payload.project_id)
    job = await generation_jobs.get_latest_job(db, project.id, codegen_runner.PHASE)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No code generation run to cancel.",
        )

    job = await generation_jobs.request_cancel(db, job)
    return {"success": True, "job": generation_jobs.job_payload(job)}


@router.post(
    "/generate",
    response_model=GenerateCodeResponse,
    summary="Generate a real, working implementation from approved architecture",
)
async def generate_code(
    payload: GenerateCodeRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start the run and wait for it, returning the finished code.

    Kept for clients that predate /start + /{id}/job polling. It is no
    longer where the work happens: the run is the same background job,
    and this only sits on it. If this request times out, the run keeps
    going and saves — the client just picks the result up from
    GET /codegen/{project_id} next time, instead of losing everything.
    """
    project = await _get_generatable_project(db, user, payload.project_id)
    job = await generation_jobs.start_or_resume(db, project, user, codegen_runner.RUNNER)

    finished = await generation_jobs.wait_for_completion(job.id)

    if finished is None or generation_jobs.is_stale(finished):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Code generation is still running. Reopen this screen to check on it.",
        )
    if finished.status == JOB_CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Code generation was cancelled.",
        )
    if finished.status != JOB_SUCCEEDED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=finished.error or "Code generation failed.",
        )

    await db.refresh(project)
    return _saved_result(project)


# ───────────────────────────────────────────────
#  Results
# ───────────────────────────────────────────────
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
    project = await _get_project(db, user, project_id)

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
        "stack_used": project.codegen_data.get("stack_used"),
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
    project = await _get_project(db, user, payload.project_id)

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
