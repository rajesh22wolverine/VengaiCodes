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
    # Deliberately NOT `with TestClient(app)`: the context-manager form
    # runs the app's lifespan, whose init_db() connects to whatever
    # DATABASE_URL points at — a local .env's SQLite file on a dev
    # machine, but a Postgres on localhost:5432 that doesn't exist in
    # Backend CI, which errored every test here. No route under test
    # needs startup to have run.
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_analyze_returns_a_full_inventory(client):
    response = client.post(
        "/api/v1/page/analyze", json={"html": PAGE, "css": ".p { color: red; }"}
    )
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
        json={
            "html": PAGE,
            "edits": [
                {"op": "set_text", "target": {"selector": "#h"}, "value": "Hi there"}
            ],
        },
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
    response = client.post(
        "/api/v1/page/command",
        json={"html": PAGE, "command": 'change the headline to "Welcome"'},
    )
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
        json={
            "html": PAGE,
            "command": 'change the headline to "Welcome"',
            "apply": True,
        },
    )
    body = response.json()
    assert body["applied"] is True
    assert ">Welcome<" in body["html"]


def test_command_reports_what_it_could_not_understand(client):
    response = client.post(
        "/api/v1/page/command",
        json={"html": PAGE, "command": "make it feel more premium"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["understood"] == []
    assert body["applied"] is False
    assert len(body["not_understood"]) == 1
    assert body["supported_phrasings"]


def test_import_accepts_a_real_html_file_and_returns_its_analysis(client):
    response = client.post(
        "/api/v1/page/import",
        files={"file": ("landing.html", PAGE.encode(), "text/html")},
        data={"page_name": "Landing"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["html"] == PAGE
    assert body["summary"]["by_tag"]["h1"] == 1
    assert body["design"] is None  # no project_id, so nothing was stored


def test_import_accepts_an_optional_stylesheet(client):
    response = client.post(
        "/api/v1/page/import",
        files={
            "file": ("landing.html", PAGE.encode(), "text/html"),
            "css_file": ("landing.css", b".p { color: red; }", "text/css"),
        },
    )
    assert response.status_code == 200
    assert response.json()["summary"]["stylesheet"]["rule_count"] == 1


def test_import_accepts_pasted_html_without_a_file(client):
    # The mobile app has no file picker, so it posts the markup directly.
    response = client.post(
        "/api/v1/page/import", data={"html": PAGE, "page_name": "Pasted"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["html"] == PAGE
    assert body["summary"]["element_count"] > 0


def test_import_rejects_when_neither_file_nor_html_is_given(client):
    response = client.post("/api/v1/page/import", data={"page_name": "Nothing"})
    assert response.status_code == 400
    assert "paste the page's HTML" in response.json()["detail"]


def test_import_rejects_a_non_html_file(client):
    response = client.post(
        "/api/v1/page/import",
        files={"file": ("shot.png", b"\x89PNG\r\n", "image/png")},
    )
    assert response.status_code == 400
    assert ".html" in response.json()["detail"]


def test_import_rejects_a_file_with_no_elements(client):
    response = client.post(
        "/api/v1/page/import",
        files={"file": ("empty.html", b"just some loose text", "text/html")},
    )
    assert response.status_code == 400
    assert "doesn't contain any HTML elements" in response.json()["detail"]


def test_command_handles_a_mix_of_understood_and_not(client):
    response = client.post(
        "/api/v1/page/command",
        json={"html": PAGE, "command": "hide the .p\nmake it pop", "apply": True},
    )
    body = response.json()
    assert len(body["understood"]) == 1
    assert len(body["not_understood"]) == 1
    # The understood half still applies — one unparseable line doesn't
    # throw away a change the user clearly did express.
    assert "display: none" in body["html"]
