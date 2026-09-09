"""Code generation over HTTP, end to end, with the AI stubbed out.

Covers the path the desktop and mobile apps take now: start the run, poll
it while it works, read the result — none of which holds a request open
for the length of the generation.
"""

import pytest

from app.ai import codegen_shared


@pytest.fixture(autouse=True)
def stub_ai(monkeypatch):
    """Every AI call any codegen adapter makes goes through this one
    function; nothing here should reach a provider."""

    async def fake_generate_text(prompt, **kwargs):
        return {"text": "def handler():\n    return {'ok': True}\n"}

    monkeypatch.setattr(codegen_shared, "generate_text", fake_generate_text)


def test_start_returns_immediately_and_the_run_finishes_in_the_background(api) -> None:
    started = api.client.post("/api/v1/codegen/start", json={"project_id": api.project_id})

    assert started.status_code == 202
    job = started.json()["job"]
    assert job["status"] in ("queued", "running")
    # One AI step per table, routes file and screen — known up front, so
    # the client can show real progress instead of an open-ended spinner.
    assert job["total_steps"] == 3

    finished = api.poll_until_done("codegen")
    assert finished["status"] == "succeeded", finished["error"]
    assert finished["completed_steps"] == 3

    result = api.client.get(f"/api/v1/codegen/{api.project_id}")
    assert result.status_code == 200
    paths = [f["path"] for f in result.json()["codegen"]["files"]]
    assert "backend/models/orders.py" in paths
    assert "frontend/src/screens/Home.jsx" in paths
    # The deterministic wiring pass ran after the AI steps.
    assert "frontend/package.json" in paths
    assert result.json()["stack_used"]["codegen_target"]


def test_starting_twice_does_not_run_the_generation_twice(api) -> None:
    first = api.client.post(
        "/api/v1/codegen/start", json={"project_id": api.project_id}
    ).json()["job"]
    second = api.client.post(
        "/api/v1/codegen/start", json={"project_id": api.project_id}
    ).json()["job"]

    assert first["id"] == second["id"]

    finished = api.poll_until_done("codegen")
    assert finished["status"] == "succeeded"
    assert finished["completed_steps"] == finished["total_steps"]


def test_the_legacy_generate_endpoint_still_returns_the_finished_code(api) -> None:
    """Already-installed clients POST /generate and wait. It now waits on
    the same background job — and if it gives up, the run still finishes
    and saves rather than being lost with the request."""
    response = api.client.post("/api/v1/codegen/generate", json={"project_id": api.project_id})

    assert response.status_code == 200
    body = response.json()
    assert body["codegen"]["files"]
    assert body["stack_used"]["codegen_target"]


def test_generating_before_the_architecture_is_approved_is_rejected(api) -> None:
    """The guard the old inline endpoint had has to survive the move to a
    job — otherwise it would start a run with nothing to build from."""
    api.update_project(architecture_data={"user_approved": False})

    response = api.client.post("/api/v1/codegen/start", json={"project_id": api.project_id})

    assert response.status_code == 400
    assert "Architecture must be approved" in response.json()["detail"]


def test_job_endpoint_reports_nothing_before_a_run_exists(api) -> None:
    response = api.client.get(f"/api/v1/codegen/{api.project_id}/job")

    assert response.status_code == 200
    assert response.json()["job"] is None
