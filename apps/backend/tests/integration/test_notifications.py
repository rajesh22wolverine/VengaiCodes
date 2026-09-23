"""Notifications over HTTP, end to end, with the AI stubbed out.

GET /notifications and POST /notifications/{id}/read used to be a
hardcoded-empty placeholder (no Notification model existed at all).
This covers the real thing: a finished background generation job
creates a real notification for its owner, it's listed with a real
unread count, and marking it read actually persists.
"""

import uuid

import pytest
from sqlalchemy import select

from app.ai import codegen_shared
from app.models.notification import Notification
from app.services.notifications import create_notification


@pytest.fixture(autouse=True)
def stub_ai(monkeypatch):
    async def fake_generate_text(prompt, **kwargs):
        return {"text": "def handler():\n    return {'ok': True}\n"}

    monkeypatch.setattr(codegen_shared, "generate_text", fake_generate_text)


def test_notifications_start_empty(api) -> None:
    response = api.client.get("/api/v1/notifications")
    assert response.status_code == 200
    body = response.json()
    assert body["notifications"] == []
    assert body["unread_count"] == 0


def test_a_finished_codegen_job_creates_a_real_notification(api) -> None:
    api.client.post("/api/v1/codegen/start", json={"project_id": api.project_id})
    finished = api.poll_until_done("codegen")
    assert finished["status"] == "succeeded", finished["error"]

    response = api.client.get("/api/v1/notifications")
    assert response.status_code == 200
    body = response.json()

    assert body["unread_count"] >= 1
    matches = [n for n in body["notifications"] if n["type"] == "success"]
    assert matches, body["notifications"]
    notif = matches[0]
    assert "Code generation" in notif["title"]
    assert api.project_id in (notif["link"] or "")
    assert notif["is_read"] is False


def test_mark_notification_read_persists_and_updates_unread_count(api) -> None:
    api.client.post("/api/v1/codegen/start", json={"project_id": api.project_id})
    api.poll_until_done("codegen")

    before = api.client.get("/api/v1/notifications").json()
    notif_id = before["notifications"][0]["id"]
    unread_before = before["unread_count"]
    assert unread_before >= 1

    mark = api.client.post(f"/api/v1/notifications/{notif_id}/read")
    assert mark.status_code == 200
    assert mark.json()["is_read"] is True

    after = api.client.get("/api/v1/notifications").json()
    assert after["unread_count"] == unread_before - 1
    marked = next(n for n in after["notifications"] if n["id"] == notif_id)
    assert marked["is_read"] is True


def test_marking_a_nonexistent_notification_read_is_404(api) -> None:
    response = api.client.post(f"/api/v1/notifications/{uuid.uuid4()}/read")
    assert response.status_code == 404


def test_marking_someone_elses_notification_read_is_404(api) -> None:
    """A notification belongs to exactly one user — the query is scoped
    to Notification.user_id == the caller, not just the id."""

    async def make_other_users_notification():
        async with api.sessions() as db:
            n = Notification(
                user_id=str(uuid.uuid4()),
                title="Not yours",
                message="x",
                type="info",
            )
            db.add(n)
            await db.commit()
            return n.id

    import asyncio

    other_id = asyncio.run(make_other_users_notification())

    response = api.client.post(f"/api/v1/notifications/{other_id}/read")
    assert response.status_code == 404


def test_a_failed_codegen_job_creates_an_error_notification(api, monkeypatch) -> None:
    """RUNNER is a frozen PhaseRunner built at import time with a direct
    reference to run_step — patching codegen_runner.run_step wouldn't
    reach it, since it's not looked up dynamically. Swapping the whole
    RUNNER object works because codegen.py's route handler reads
    codegen_runner.RUNNER fresh at call time."""
    from app.ai import codegen_runner
    from app.services.generation_jobs import PhaseRunner

    async def boom(ctx):
        raise RuntimeError("simulated provider outage")

    broken_runner = PhaseRunner(
        phase=codegen_runner.PHASE,
        fingerprint=codegen_runner.fingerprint,
        steps=codegen_runner.steps,
        run_step=boom,
        finalize=codegen_runner.finalize,
    )
    monkeypatch.setattr(codegen_runner, "RUNNER", broken_runner)

    api.client.post("/api/v1/codegen/start", json={"project_id": api.project_id})
    finished = api.poll_until_done("codegen")
    assert finished["status"] == "failed"

    body = api.client.get("/api/v1/notifications").json()
    matches = [n for n in body["notifications"] if n["type"] == "error"]
    assert matches, body["notifications"]
    assert "failed" in matches[0]["title"].lower()
    assert "simulated provider outage" in matches[0]["message"]


def test_create_notification_service_adds_a_real_row(api) -> None:
    """The one function every real call site (admin actions, marketplace
    moderation, finished generation jobs) shares — exercised directly
    against a real session, independent of any one call site."""

    async def run():
        async with api.sessions() as db:
            await create_notification(
                db,
                user_id="some-user-id",
                title="Hello",
                message="World",
                type="admin",
                link="/x",
            )
            await db.commit()

            result = await db.execute(
                select(Notification).where(Notification.user_id == "some-user-id")
            )
            return result.scalar_one()

    import asyncio

    notif = asyncio.run(run())
    assert notif.title == "Hello"
    assert notif.message == "World"
    assert notif.type == "admin"
    assert notif.link == "/x"
    assert notif.is_read is False
