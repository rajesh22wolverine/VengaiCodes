"""A real app, a real database, no AI provider.

Long generations (UI/UX, code) now run as background jobs the client
polls, so the parts worth testing over HTTP are the start/poll/read
handshake and the guards around it — with every AI call stubbed by the
test that uses this.
"""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1.auth import get_current_active_user
from app.core.database import Base, get_db
from app.main import app
from app.models.project import Project
from app.models.user import User
from app.services import generation_jobs

POLL_TIMEOUT_SECONDS = 30


@dataclass
class Api:
    client: TestClient
    project_id: str
    sessions: async_sessionmaker

    def poll_until_done(self, phase: str) -> dict:
        """Follow a run the way the desktop and mobile apps do."""
        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            job = self.client.get(f"/api/v1/{phase}/{self.project_id}/job").json()["job"]
            if job and job["status"] in ("succeeded", "failed", "cancelled"):
                return job
            time.sleep(0.1)
        raise AssertionError(f"{phase} job never finished")

    def update_project(self, **fields) -> None:
        async def apply():
            async with self.sessions() as db:
                project = await db.get(Project, self.project_id)
                for key, value in fields.items():
                    setattr(project, key, value)
                await db.commit()

        asyncio.run(apply())


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'api.db'}", poolclass=NullPool
    )
    sessions = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    # The worker, its heartbeat and wait_for_completion each open their
    # own session — point all of them at this database.
    monkeypatch.setattr(generation_jobs, "AsyncSessionLocal", sessions)
    # The legacy /generate endpoints wait on the job by polling; no need
    # to sit through the production interval in a test.
    monkeypatch.setattr(generation_jobs, "SYNC_POLL_INTERVAL_SECONDS", 0.05)

    user = User(
        id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex}@example.com",
        username=uuid.uuid4().hex[:12],
        hashed_password="x",
        full_name="Test",
    )
    project = Project(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name="Test App",
        requirements_data={
            "user_approved": True,
            "frd": {"key_features": ["track orders"], "user_stories": ["I can order"]},
        },
        architecture_data={
            "user_approved": True,
            "architecture": {
                "database_tables": [{"name": "orders"}],
                "api_endpoints": [{"method": "GET", "path": "/orders"}],
            },
        },
        uiux_data={"design": {"screens": [{"id": "s1", "name": "Home", "purpose": "landing"}]}},
    )

    async def setup():
        # Tables only, no indexes — several models declare the same index
        # twice (in __table_args__ and via index=True), and create_all()
        # emits CREATE INDEX for both, which SQLite rejects. Same reason
        # app/main.py's init_db() strips them first.
        stashed = {t.name: list(t.indexes) for t in Base.metadata.tables.values()}
        for table in Base.metadata.tables.values():
            table.indexes.clear()
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            for table in Base.metadata.tables.values():
                table.indexes.update(stashed.get(table.name, []))

        async with sessions() as db:
            db.add_all([user, project])
            await db.commit()

    asyncio.run(setup())

    async def override_get_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: user

    # Entering TestClient runs the app's lifespan, whose init_db() and
    # seeding hit the REAL engine (settings.DATABASE_URL). That passed
    # on a dev machine only because .env points at SQLite; on CI there
    # is no .env, the default is Postgres on localhost, and every test
    # errored in setup with "Connect call failed 127.0.0.1:5432". These
    # tests bring their own database above and need nothing from the
    # lifespan, so it's replaced for the duration of the fixture.
    @asynccontextmanager
    async def no_lifespan(_app):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", no_lifespan)

    with TestClient(app) as client:
        yield Api(client=client, project_id=project.id, sessions=sessions)

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())
