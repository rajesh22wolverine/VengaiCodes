# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Generation Job Model
#  models/generation_job.py — One long-running AI generation run
#  (code generation, UI/UX design) tracked in the database instead
#  of inside a single HTTP request.
#
#  Why this table exists:
#  UI/UX and code generation both make ONE AI call per screen (and,
#  for codegen, per database table too), sequentially — see
#  ai/uiux_runner.py and ai/codegen_runner.py. Their wall time is
#  therefore O(screens + tables), while an HTTP request timeout is a
#  constant. A 4-screen project finished inside the client's 10-minute
#  budget; a 25-screen one never could, and because the old code only
#  committed at the very end, a timeout also threw away every AI call
#  that HAD already succeeded — the retry then started from zero and
#  hit the same wall.
#
#  Persisting the run means: progress is pollable with ordinary short
#  requests, a dropped connection (or a redeploy) costs at most the
#  step that was in flight, and a resumed run doesn't pay again for
#  work already done.
# ═══════════════════════════════════════════════════════════════

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
)
from sqlalchemy.sql import func

from app.core.database import Base


# ── Status values (plain strings, not a DB Enum) ──
# A DB-level Enum type would need a real migration to add a value to;
# these are only ever read/written by this codebase.
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

TERMINAL_STATUSES = (JOB_SUCCEEDED, JOB_FAILED, JOB_CANCELLED)


class GenerationJob(Base):
    """One AI generation run for one project phase."""

    __tablename__ = "generation_jobs"
    __table_args__ = (
        Index("ix_generation_jobs_project_id", "project_id"),
        Index("ix_generation_jobs_project_phase", "project_id", "phase"),
        Index("ix_generation_jobs_status", "status"),
    )

    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )

    project_id: str = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Whose AI config the run spends — the run keeps using this user's
    # model bag after their HTTP request is long gone.
    user_id: str = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Which SDLC phase this run belongs to — "code_generation" | "uiux".
    phase: str = Column(String(32), nullable=False, index=True)

    status: str = Column(String(16), default=JOB_QUEUED, nullable=False, index=True)

    # ── Progress ──
    # total_steps is NOT fixed at creation: UI/UX only learns how many
    # screens it has to mock up after its first step generates the design
    # system, so the runner recomputes the step list each iteration and
    # this grows. Clients must treat it as "best known so far".
    total_steps: int = Column(Integer, default=0, nullable=False)
    completed_steps: int = Column(Integer, default=0, nullable=False)
    current_step: Optional[str] = Column(String(255), nullable=True)

    # Runner-owned partial results — every file/screen finished so far.
    # Written after each step, which is what makes a resume cheap.
    # Cleared on success (the finished result lives on the project row).
    state: dict = Column(JSON, default=dict, nullable=False)

    # Hash of the inputs this run was planned from (architecture tables,
    # endpoints, screens, stack). If the user edits the architecture and
    # regenerates, the old job's half-finished files are for a different
    # app — the fingerprint mismatch forces a fresh run instead of a
    # resume that would silently mix the two.
    plan_fingerprint: Optional[str] = Column(String(64), nullable=True)

    error: Optional[str] = Column(Text, nullable=True)
    cancel_requested: bool = Column(Boolean, default=False, nullable=False)

    # Updated every ~20s by the worker while a step is in flight. A
    # running job whose heartbeat has gone quiet is a worker that died
    # (redeploy, crash, container recycle) — the next start takes it
    # over and resumes rather than waiting forever on a ghost.
    heartbeat_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)

    created_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Optional[datetime] = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<GenerationJob {self.id} {self.phase} {self.status} "
            f"{self.completed_steps}/{self.total_steps}>"
        )
