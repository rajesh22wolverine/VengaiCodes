"""End-to-end coverage of the /page routes through the real FastAPI app.

Runs against the real router and real request validation (TestClient with
a stubbed auth dependency), so these catch wiring mistakes the pure-logic
suites can't: bad schemas, wrong status codes, and the stored-design path
reading/writing uiux_data correctly.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.v1.auth import get_current_active_user
from app.core.database import get_db
from app.main import app

PAGE = '<html lang="en"><head><title>T</title><meta name="viewport" content="w"></head><body><h1 id="h">Hello</h1><p class="p">Body</p></body></html>'


class _FakeUser:
    id = "user-1"
    is_active = True
    is_admin = False


@pytest.fixture()
def client():
    app.dependency_overrides[get_current_active_user] = lambda: _FakeUser()
    # No route under test touches the DB unless project_id/design_id is
    # sent, and those cases are covered separately with a real session.
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_analyze_returns_a_full_inventory(client):
    response = client.post("/api/v1/page/analyze", json={"html": PAGE, "css": ".p { color: red; }"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["summary"]["by_tag"]["h1"] == 1
    assert body["summary"]["ids"] == ["h"]
    assert body["summary"]["stylesheet"]["rule_count"] == 1
    assert any(e["tag"] == "h1" and e["text"] == "Hello" for e in body["elements"])


def test_analyze_requires_a_source(client):
    response = client.post("/api/v1/page/analyze", json={})
    assert response.status_code == 400
    assert "project_id" in response.json()["detail"]


def test_edit_applies_structured_ops(client):
    response = client.post(
        "/api/v1/page/edit",
        json={"html": PAGE, "edits": [{"op": "set_text", "target": {"selector": "#h"}, "value": "Hi there"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert '<h1 id="h">Hi there</h1>' in body["html"]
    assert body["html_changed"] is True
    assert body["saved"] is False


def test_edit_rejects_an_ambiguous_target_with_400(client):
    response = client.post(
        "/api/v1/page/edit",
        json={
            "html": "<p>a</p><p>b</p>",
            "edits": [{"op": "set_text", "target": {"selector": "p"}, "value": "x"}],
        },
    )
    assert response.status_code == 400
    assert "matches 2 elements" in response.json()["detail"]


def test_edit_rejects_an_unknown_op_with_400(client):
    response = client.post(
        "/api/v1/page/edit",
        json={"html": PAGE, "edits": [{"op": "vibes", "target": {"selector": "#h"}}]},
    )
    assert response.status_code == 400
    assert "Unknown op" in response.json()["detail"]


def test_edit_requires_at_least_one_edit(client):
    response = client.post("/api/v1/page/edit", json={"html": PAGE, "edits": []})
    assert response.status_code == 422


def test_command_previews_without_applying_by_default(client):
    response = client.post("/api/v1/page/command", json={"html": PAGE, "command": 'change the headline to "Welcome"'})
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is False
    assert "html" not in body
    assert ">Welcome<" in body["preview"]["html"]
    assert len(body["understood"]) == 1
    assert "element" in body["understood"][0]["explanation"]


def test_command_applies_when_asked(client):
    response = client.post(
        "/api/v1/page/command",
        json={"html": PAGE, "command": 'change the headline to "Welcome"', "apply": True},
    )
    body = response.json()
    assert body["applied"] is True
    assert ">Welcome<" in body["html"]


def test_command_reports_what_it_could_not_understand(client):
    response = client.post("/api/v1/page/command", json={"html": PAGE, "command": "make it feel more premium"})
    assert response.status_code == 200
    body = response.json()
    assert body["understood"] == []
    assert body["applied"] is False
    assert len(body["not_understood"]) == 1
    assert body["supported_phrasings"]


def test_command_handles_a_mix_of_understood_and_not(client):
    response = client.post(
        "/api/v1/page/command",
        json={"html": PAGE, "command": 'hide the .p\nmake it pop', "apply": True},
    )
    body = response.json()
    assert len(body["understood"]) == 1
    assert len(body["not_understood"]) == 1
    # The understood half still applies — one unparseable line doesn't
    # throw away a change the user clearly did express.
    assert "display: none" in body["html"]
