# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Generation Job Service
#  services/generation_jobs.py — Runs a multi-step AI generation
#  (code generation, UI/UX design) as a background job whose progress
#  and partial results live in the database, so no HTTP request has
#  to stay open for the length of the run.
#
#  A phase plugs in by handing over a PhaseRunner: how to fingerprint
#  its inputs, how to list its steps, how to run one step, and how to
#  write the finished result onto the project. Everything else —
#  claiming, resuming, heartbeating, cancelling, reporting progress —
#  is the same for every phase and lives here.
# ═══════════════════════════════════════════════════════════════

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.generation_job import (
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_SUCCEEDED,
    GenerationJob,
)
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger("vengaicode.jobs")

# How often the worker stamps heartbeat_at while a step is in flight.
HEARTBEAT_INTERVAL_SECONDS = 20
# A running job that hasn't heartbeat in this long is assumed dead (the
# process was redeployed, crashed, or recycled) and can be taken over.
# Comfortably more than the heartbeat interval so an ordinary GC pause
# or a slow DB write can't orphan a healthy run.
STALE_AFTER_SECONDS = 90
# Hard ceiling on the legacy synchronous endpoint's wait. The job itself
# is never bounded by this — only how long one request will sit on it.
MAX_SYNC_WAIT_SECONDS = 3600
SYNC_POLL_INTERVAL_SECONDS = 2


# ───────────────────────────────────────────────
#  Runner contract
# ───────────────────────────────────────────────
@dataclass
class StepCtx:
    """Everything one step of a run gets. `state` is the run's own
    accumulated partial results — the step mutates it in place, and the
    service persists it after the step returns."""

    project: Project
    user: User
    db: AsyncSession
    step: dict
    state: dict


@dataclass(frozen=True)
class PhaseRunner:
    # Project phase this runner drives — "code_generation" | "uiux".
    phase: str
    # Stable hash of the inputs a run is planned from. A change means a
    # half-finished run is no longer resumable (see plan_fingerprint).
    fingerprint: Callable[[Project], str]
    # (project, state) -> ordered step descriptors, each at least
    # {"kind": str, "label": str}. Recomputed after every step, so a
    # phase whose step count only becomes known mid-run (UI/UX learns
    # its screen count from its first step) can grow the list.
    steps: Callable[[Project, dict], list[dict]]
    # Runs one step; mutates ctx.state. Raising aborts the run and
    # leaves every completed step resumable.
    run_step: Callable[[StepCtx], Awaitable[None]]
    # Writes the finished result onto the project (the service commits).
    finalize: Callable[[Project, dict], Awaitable[None]]


# Strong references to in-flight worker tasks. asyncio only holds a weak
# reference to a running task, so without this a job can be garbage
# collected mid-run.
_workers: set[asyncio.Task] = set()

# Serializes start_or_resume within this process. The FOR UPDATE lock
# below covers separate processes; this covers the far likelier case of
# one client firing two starts at once against one worker.
_start_lock = asyncio.Lock()


# ───────────────────────────────────────────────
#  Helpers
# ───────────────────────────────────────────────
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes for timezone=True columns;
    Postgres hands back aware ones. Normalize before comparing."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def is_stale(job: GenerationJob) -> bool:
    """True when a job claims to be running but its worker has gone
    quiet — i.e. the process running it died."""
    if job.status != JOB_RUNNING:
        return False
    beat = _as_utc(job.heartbeat_at) or _as_utc(job.created_at)
    if beat is None:
        return True
    return _utcnow() - beat > timedelta(seconds=STALE_AFTER_SECONDS)


def is_active(job: Optional[GenerationJob]) -> bool:
    """Running (with a live worker) or waiting to start."""
    if job is None:
        return False
    if job.status == JOB_QUEUED:
        return True
    return job.status == JOB_RUNNING and not is_stale(job)


def job_payload(job: Optional[GenerationJob]) -> Optional[dict]:
    """The client-facing shape of a job — what the poll endpoint and
    every start/cancel response return."""
    if job is None:
        return None
    stale = is_stale(job)
    return {
        "id": job.id,
        "phase": job.phase,
        # A stale "running" job is reported as failed rather than as a
        # run the client should keep waiting on: its worker is gone, and
        # nothing moves it forward until someone starts it again.
        "status": JOB_FAILED if stale else job.status,
        # Not a real failure — the worker was killed (a redeploy, a
        # crash, a container recycle) with the run half done. Clients
        # treat this as "start it again", which resumes; a genuine
        # failure (a provider error, unparseable output) does not.
        "interrupted": stale,
        "total_steps": job.total_steps,
        "completed_steps": job.completed_steps,
        "current_step": job.current_step,
        "error": job.error
        or (
            "Generation stopped unexpectedly — start it again to pick up "
            "where it left off."
            if stale
            else None
        ),
        "cancel_requested": job.cancel_requested,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


async def get_latest_job(
    db: AsyncSession, project_id: str, phase: str
) -> Optional[GenerationJob]:
    result = await db.execute(
        select(GenerationJob)
        .where(
            GenerationJob.project_id == project_id,
            GenerationJob.phase == phase,
        )
        .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ───────────────────────────────────────────────
#  Starting / resuming
# ───────────────────────────────────────────────
async def start_or_resume(
    db: AsyncSession,
    project: Project,
    user: User,
    runner: PhaseRunner,
) -> GenerationJob:
    """
    Attach to this project's in-flight run, resume the last one that
    died or failed partway, or start a fresh one — in that order.

    Safe to call repeatedly: two clients hitting it at the same time get
    the same job, not two runs billing the same user twice.
    """
    fingerprint = runner.fingerprint(project)

    async with _start_lock:
        # Serializes concurrent starts across processes too: everyone
        # planning a run for this project queues behind this row lock
        # until the winner has committed its job. SQLite has no FOR
        # UPDATE and SQLAlchemy omits it there, which is fine — a
        # single-process dev DB has nothing to race with.
        await db.execute(
            select(Project.id).where(Project.id == project.id).with_for_update()
        )

        job = await get_latest_job(db, project.id, runner.phase)

        if is_active(job) and job.plan_fingerprint == fingerprint:
            # Someone already has this exact run going — join it.
            await db.commit()
            return job

        resumable = (
            job is not None
            and job.plan_fingerprint == fingerprint
            and job.status in (JOB_FAILED, JOB_RUNNING, JOB_QUEUED, JOB_CANCELLED)
            and not is_active(job)
            and job.completed_steps > 0
        )

        if resumable:
            job.status = JOB_RUNNING
            job.error = None
            job.cancel_requested = False
            job.finished_at = None
            job.heartbeat_at = _utcnow()
            logger.info(
                f"Resuming {runner.phase} job {job.id} at step "
                f"{job.completed_steps}/{job.total_steps}"
            )
        else:
            job = GenerationJob(
                project_id=project.id,
                user_id=user.id,
                phase=runner.phase,
                status=JOB_RUNNING,
                plan_fingerprint=fingerprint,
                state={},
                total_steps=len(runner.steps(project, {})),
                completed_steps=0,
                heartbeat_at=_utcnow(),
            )
            db.add(job)
            logger.info(f"Starting {runner.phase} job for project {project.id}")

        # Commit before the worker starts: it opens its own session and
        # has to be able to see the row.
        await db.commit()
        await db.refresh(job)

        task = asyncio.create_task(_run_job(job.id, runner))
        _workers.add(task)
        task.add_done_callback(_workers.discard)

        return job


async def request_cancel(db: AsyncSession, job: GenerationJob) -> GenerationJob:
    """Ask a running job to stop. The worker checks between steps, so
    the step already in flight still finishes — and is still saved. A
    cancelled run is resumable, not discarded."""
    if job.status in (JOB_RUNNING, JOB_QUEUED):
        job.cancel_requested = True
        await db.commit()
        await db.refresh(job)
    return job


async def wait_for_completion(job_id: str) -> Optional[GenerationJob]:
    """Block until a job reaches a terminal state, for the legacy
    synchronous endpoints. Polls the row rather than awaiting the task
    so it works no matter which process is running the job.

    A client giving up on that wait (timeout, disconnect) does NOT stop
    the job — that is the entire point: the run finishes and saves
    either way, and the client picks the result up on its next load."""
    deadline = _utcnow() + timedelta(seconds=MAX_SYNC_WAIT_SECONDS)
    while _utcnow() < deadline:
        async with AsyncSessionLocal() as db:
            job = await db.get(GenerationJob, job_id)
            if job is None:
                return None
            if job.status in (JOB_SUCCEEDED, JOB_FAILED, JOB_CANCELLED) or is_stale(job):
                return job
        await asyncio.sleep(SYNC_POLL_INTERVAL_SECONDS)
    return None


# ───────────────────────────────────────────────
#  Worker
# ───────────────────────────────────────────────
async def _heartbeat(job_id: str, stop: asyncio.Event) -> None:
    """Stamp heartbeat_at while a step runs. Its own session, because a
    single AsyncSession is not safe to use from two tasks at once."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)
            return
        except asyncio.TimeoutError:
            pass
        try:
            async with AsyncSessionLocal() as db:
                job = await db.get(GenerationJob, job_id)
                if job is None or job.status != JOB_RUNNING:
                    return
                job.heartbeat_at = _utcnow()
                await db.commit()
        except Exception as e:  # never let a heartbeat failure kill the run
            logger.warning(f"Heartbeat failed for job {job_id}: {e}")


async def _run_job(job_id: str, runner: PhaseRunner) -> None:
    """Run every remaining step of a job, saving after each one."""
    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(_heartbeat(job_id, stop_heartbeat))

    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(GenerationJob, job_id)
            if job is None:
                return

            project = await db.get(Project, job.project_id)
            user = await db.get(User, job.user_id)
            if project is None or user is None:
                job.status = JOB_FAILED
                job.error = "Project or user no longer exists."
                job.finished_at = _utcnow()
                await db.commit()
                return

            state = dict(job.state or {})

            try:
                steps = runner.steps(project, state)
                job.total_steps = len(steps)

                while job.completed_steps < len(steps):
                    await db.refresh(job, ["cancel_requested"])
                    if job.cancel_requested:
                        job.status = JOB_CANCELLED
                        job.current_step = None
                        job.finished_at = _utcnow()
                        await db.commit()
                        logger.info(f"{runner.phase} job {job.id} cancelled by user")
                        return

                    step = steps[job.completed_steps]
                    job.current_step = str(step.get("label") or step.get("kind") or "")
                    job.heartbeat_at = _utcnow()
                    await db.commit()

                    await runner.run_step(
                        StepCtx(
                            project=project, user=user, db=db, step=step, state=state
                        )
                    )

                    # Reassign, don't mutate — SQLAlchemy only notices a
                    # JSON column changed when the value is replaced.
                    job.completed_steps += 1
                    job.state = dict(state)
                    job.heartbeat_at = _utcnow()
                    await db.commit()

                    steps = runner.steps(project, state)
                    if len(steps) != job.total_steps:
                        job.total_steps = len(steps)
                        await db.commit()

                await runner.finalize(project, state)
                job.status = JOB_SUCCEEDED
                job.current_step = None
                job.error = None
                # The finished result now lives on the project row;
                # a second copy here would double the stored size of
                # every generated file.
                job.state = {}
                job.finished_at = _utcnow()
                await db.commit()
                logger.info(f"{runner.phase} job {job.id} finished")

            except asyncio.CancelledError:
                # Process is shutting down. Leave the job as it is: its
                # heartbeat goes quiet, and the next start takes it over
                # and picks up from the last saved step.
                raise
            except Exception as e:
                logger.exception(f"{runner.phase} job {job_id} failed")
                await db.rollback()
                failed = await db.get(GenerationJob, job_id)
                if failed is not None:
                    failed.status = JOB_FAILED
                    failed.error = str(e) or e.__class__.__name__
                    failed.current_step = None
                    failed.finished_at = _utcnow()
                    await db.commit()
    finally:
        stop_heartbeat.set()
        try:
            await heartbeat_task
        except Exception:
            pass
