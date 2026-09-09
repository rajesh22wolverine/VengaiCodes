"""Tests for the background generation-job service.

These run a real job end to end against a real (SQLite) database with a
stand-in runner, because the parts worth testing are exactly the ones
that only show up when a run is interrupted: does a failed run resume
where it stopped, does a second start join the run already going instead
of paying for a duplicate, does cancelling stop it.
"""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Importing the app registers every model on Base.metadata, which
# create_all() below needs (Project alone won't configure its mappers).
import app.main  # noqa: F401
from app.core.database import Base
from app.models.generation_job import (
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_SUCCEEDED,
    GenerationJob,
)
from app.models.project import Project
from app.models.user import User
from app.services import generation_jobs
from app.services.generation_jobs import PhaseRunner


# ───────────────────────────────────────────────
#  Harness
# ───────────────────────────────────────────────
def _runner(
    calls: list,
    *,
    step_count: int = 3,
    fail_once_on: int | None = None,
    fingerprint: str = "fp-1",
    step_seconds: float = 0.0,
) -> PhaseRunner:
    """A runner that records which steps ran, so a resumed run can be
    checked for redoing work it already paid for."""

    async def run_step(ctx) -> None:
        index = ctx.step["index"]
        calls.append(index)
        if step_seconds:
            await asyncio.sleep(step_seconds)
        if fail_once_on == index and calls.count(index) == 1:
            raise RuntimeError("provider exploded")
        ctx.state["done"] = list(ctx.state.get("done", [])) + [index]

    async def finalize(project, state) -> None:
        project.codegen_data = {"done": state.get("done", [])}

    return PhaseRunner(
        phase="test_phase",
        fingerprint=lambda project: fingerprint,
        steps=lambda project, state: [
            {"kind": "step", "index": i, "label": f"Step {i}"} for i in range(step_count)
        ],
        run_step=run_step,
        finalize=finalize,
    )


class _Harness:
    """A throwaway SQLite database with one user and one project."""

    def __init__(self, tmp_path, monkeypatch):
        # NullPool: each test drives several asyncio.run() loops, and a
        # pooled aiosqlite connection belongs to the loop that opened it.
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}", poolclass=NullPool
        )
        self.sessions = async_sessionmaker(
            bind=self.engine, expire_on_commit=False, autoflush=False
        )
        # The worker, the heartbeat and wait_for_completion each open
        # their own session — point all of them at this database.
        monkeypatch.setattr(generation_jobs, "AsyncSessionLocal", self.sessions)
        monkeypatch.setattr(generation_jobs, "SYNC_POLL_INTERVAL_SECONDS", 0.02)

    async def setup(self) -> None:
        # Tables only, no indexes — several models declare the same index
        # both in __table_args__ and via index=True on the column, and
        # create_all() emits CREATE INDEX for both, which SQLite rejects.
        # Same reason app/main.py's init_db() strips them first.
        stashed = {t.name: list(t.indexes) for t in Base.metadata.tables.values()}
        for table in Base.metadata.tables.values():
            table.indexes.clear()
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            for table in Base.metadata.tables.values():
                table.indexes.update(stashed.get(table.name, []))

        async with self.sessions() as db:
            self.user = User(
                id=str(uuid.uuid4()),
                email=f"{uuid.uuid4().hex}@example.com",
                username=uuid.uuid4().hex[:12],
                hashed_password="x",
                full_name="Test",
            )
            self.project = Project(id=str(uuid.uuid4()), user_id=self.user.id, name="Test App")
            db.add_all([self.user, self.project])
            await db.commit()

    async def run_to_completion(self, runner: PhaseRunner) -> GenerationJob:
        async with self.sessions() as db:
            user = await db.get(User, self.user.id)
            project = await db.get(Project, self.project.id)
            job = await generation_jobs.start_or_resume(db, project, user, runner)
        return await generation_jobs.wait_for_completion(job.id)

    async def start(self, runner: PhaseRunner) -> GenerationJob:
        async with self.sessions() as db:
            user = await db.get(User, self.user.id)
            project = await db.get(Project, self.project.id)
            return await generation_jobs.start_or_resume(db, project, user, runner)

    async def project_row(self) -> Project:
        async with self.sessions() as db:
            return await db.get(Project, self.project.id)

    async def close(self) -> None:
        await self.engine.dispose()


@pytest.fixture
def harness(tmp_path, monkeypatch):
    h = _Harness(tmp_path, monkeypatch)
    asyncio.run(h.setup())
    yield h
    asyncio.run(h.close())


# ───────────────────────────────────────────────
#  Tests
# ───────────────────────────────────────────────
def test_run_completes_every_step_and_saves_the_result(harness) -> None:
    calls: list[int] = []

    async def scenario():
        return await harness.run_to_completion(_runner(calls))

    job = asyncio.run(scenario())

    assert job.status == JOB_SUCCEEDED
    assert calls == [0, 1, 2]
    assert job.completed_steps == 3
    assert job.total_steps == 3
    # Partial results are dropped once the finished result is on the
    # project — keeping both would store every generated file twice.
    assert job.state == {}
    assert asyncio.run(harness.project_row()).codegen_data == {"done": [0, 1, 2]}


def test_a_failed_run_resumes_instead_of_redoing_finished_steps(harness) -> None:
    """The whole point of persisting progress: an interrupted run must
    not charge the user again for the AI calls that already succeeded."""
    calls: list[int] = []

    async def scenario():
        failed = await harness.run_to_completion(_runner(calls, fail_once_on=1))
        assert failed.status == JOB_FAILED
        assert failed.completed_steps == 1
        assert "provider exploded" in (failed.error or "")

        # Same fingerprint — this picks the same job back up.
        return await harness.run_to_completion(_runner(calls, fail_once_on=1))

    job = asyncio.run(scenario())

    assert job.status == JOB_SUCCEEDED
    # Step 0 ran once, ever. Step 1 ran twice (it failed the first time).
    assert calls == [0, 1, 1, 2]
    assert asyncio.run(harness.project_row()).codegen_data == {"done": [0, 1, 2]}


def test_starting_again_while_running_joins_the_same_run(harness) -> None:
    calls: list[int] = []

    async def scenario():
        runner = _runner(calls, step_seconds=0.1)
        first = await harness.start(runner)
        second = await harness.start(runner)
        assert first.id == second.id
        return await generation_jobs.wait_for_completion(first.id)

    job = asyncio.run(scenario())

    assert job.status == JOB_SUCCEEDED
    # One worker, not two: every step ran exactly once.
    assert calls == [0, 1, 2]


def test_cancel_stops_the_run_and_keeps_what_was_finished(harness) -> None:
    calls: list[int] = []

    async def scenario():
        runner = _runner(calls, step_seconds=0.15)
        job = await harness.start(runner)

        await asyncio.sleep(0.05)  # let step 0 get going
        async with harness.sessions() as db:
            row = await db.get(GenerationJob, job.id)
            await generation_jobs.request_cancel(db, row)

        cancelled = await generation_jobs.wait_for_completion(job.id)
        assert cancelled.status == JOB_CANCELLED
        assert cancelled.completed_steps < 3
        # Cancelling is not throwing away: a restart carries on.
        return await harness.run_to_completion(_runner(calls, step_seconds=0))

    job = asyncio.run(scenario())

    assert job.status == JOB_SUCCEEDED
    assert calls == [0, 1, 2]
    assert asyncio.run(harness.project_row()).codegen_data == {"done": [0, 1, 2]}


def test_changed_inputs_start_a_fresh_run_rather_than_resuming(harness) -> None:
    """A resumed run must belong to the app the user has now — editing
    the architecture between attempts has to invalidate the old files."""
    calls: list[int] = []

    async def scenario():
        first = await harness.run_to_completion(_runner(calls, fail_once_on=1))
        assert first.status == JOB_FAILED

        second = await harness.run_to_completion(
            _runner(calls, fingerprint="fp-2", fail_once_on=None)
        )
        return first, second

    first, second = asyncio.run(scenario())

    assert second.id != first.id
    assert second.status == JOB_SUCCEEDED
    # Started over from step 0 rather than continuing at step 1.
    assert calls == [0, 1, 0, 1, 2]


def test_a_run_whose_worker_died_is_reported_as_failed_and_resumable(harness) -> None:
    """A redeploy kills the worker mid-run. The row still says 'running',
    so clients would poll a ghost forever unless the missing heartbeat is
    treated as a failure."""
    calls: list[int] = []

    async def scenario():
        await harness.run_to_completion(_runner(calls, fail_once_on=1))

        async with harness.sessions() as db:
            row = await generation_jobs.get_latest_job(db, harness.project.id, "test_phase")
            # What a killed worker leaves behind: still "running", no
            # error recorded, and a heartbeat that stopped.
            row.status = "running"
            row.error = None
            row.heartbeat_at = generation_jobs._utcnow() - timedelta(
                seconds=generation_jobs.STALE_AFTER_SECONDS + 30
            )
            await db.commit()
            return generation_jobs.job_payload(row), row

    payload, row = asyncio.run(scenario())

    assert generation_jobs.is_stale(row) is True
    assert generation_jobs.is_active(row) is False
    assert payload["status"] == JOB_FAILED
    assert "start it again" in payload["error"]
