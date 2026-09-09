"""UI/UX design over HTTP, end to end, with the AI stubbed out.

The interesting difference from codegen: this run doesn't know how many
steps it has until its first step finishes, so total_steps grows once the
design system names its screens.
"""

import json

import pytest

from app.ai import uiux_runner

_DESIGN = {
    "design_style": "clean and minimal",
    "color_palette": {
        "primary": "#f97316",
        "secondary": "#1a1d24",
        "accent": "#38bdf8",
        "background": "#ffffff",
        "text": "#111111",
    },
    "typography": "Inter",
    "screens": [
        {"name": "Home", "purpose": "landing", "key_elements": ["hero"]},
        {"name": "Orders", "purpose": "list orders", "key_elements": ["table"]},
        {"name": "Profile", "purpose": "account", "key_elements": ["form"]},
    ],
    "components": ["Button"],
    "navigation_pattern": "top nav",
}

_MOCKUP = {"html": "<main>Hi</main>", "css": "main{color:red}", "modules": ["Main"]}


@pytest.fixture(autouse=True)
def stub_ai(monkeypatch):
    async def fake_generate_text(prompt, **kwargs):
        # The design prompt asks for the system; every other call is a
        # single screen's mockup.
        if "design a UI/UX system" in prompt:
            return {"text": json.dumps(_DESIGN)}
        return {"text": json.dumps(_MOCKUP)}

    monkeypatch.setattr(uiux_runner, "generate_text", fake_generate_text)


def test_the_step_count_grows_once_the_design_names_its_screens(api) -> None:
    api.update_project(uiux_data=None)

    started = api.client.post("/api/v1/uiux/start", json={"project_id": api.project_id})

    assert started.status_code == 202
    # Before the design exists there is only the design step to plan.
    assert started.json()["job"]["total_steps"] == 1

    finished = api.poll_until_done("uiux")
    assert finished["status"] == "succeeded", finished["error"]
    # Design system + one mockup per screen it came back with.
    assert finished["total_steps"] == 4
    assert finished["completed_steps"] == 4

    design = api.client.get(f"/api/v1/uiux/{api.project_id}").json()["design"]
    assert [s["name"] for s in design["screens"]] == ["Home", "Orders", "Profile"]
    assert all(s["generated_html"] == _MOCKUP["html"] for s in design["screens"])
    # Every screen got its own id, as the inline version always did.
    assert len({s["id"] for s in design["screens"]}) == 3


def test_designing_before_requirements_are_approved_is_rejected(api) -> None:
    api.update_project(requirements_data={"user_approved": False})

    response = api.client.post("/api/v1/uiux/start", json={"project_id": api.project_id})

    assert response.status_code == 400
    assert "Requirements must be approved" in response.json()["detail"]


def test_the_legacy_generate_endpoint_still_returns_the_finished_design(api) -> None:
    api.update_project(uiux_data=None)

    response = api.client.post("/api/v1/uiux/generate", json={"project_id": api.project_id})

    assert response.status_code == 200
    assert len(response.json()["design"]["screens"]) == 3
