"""The step lists the two long-running phases plan their runs from.

A step is one AI call and one resume point, so what belongs in the list
— and what makes a half-finished run no longer resumable — is worth
pinning down without spending a single token to find out.
"""

import asyncio

# Registers every model, without which Project's mappers can't configure
# (User relates to models these tests never touch).
import app.main  # noqa: F401
from app.ai import codegen_runner, uiux_runner
from app.models.project import Project


def _project(**kwargs) -> Project:
    defaults = {
        "id": "p1",
        "name": "Test App",
        "requirements_data": {"user_approved": True, "frd": {"key_features": ["a"]}},
        "architecture_data": {
            "user_approved": True,
            "architecture": {
                "database_tables": [{"name": "users"}, {"name": "orders"}],
                "api_endpoints": [{"method": "GET", "path": "/orders"}],
            },
        },
        "uiux_data": {
            "design": {
                "screens": [
                    {"id": "s1", "name": "Home", "purpose": "landing"},
                    {"id": "s2", "name": "Orders", "purpose": "list"},
                ]
            }
        },
    }
    defaults.update(kwargs)
    return Project(**defaults)


# ───────────────────────────────────────────────
#  Code generation
# ───────────────────────────────────────────────
def test_codegen_plans_one_step_per_table_routes_file_and_screen() -> None:
    steps = codegen_runner.steps(_project(), {})

    assert [s["kind"] for s in steps] == [
        "model",
        "model",
        "routes",
        "screen",
        "screen",
    ]
    # Every step names what it's working on — this is what the progress
    # UI shows while a long run is in flight.
    assert steps[0]["label"] == "Data model: users"
    assert steps[-1]["label"] == "Screen: Orders"


def test_codegen_skips_the_routes_step_when_there_are_no_endpoints() -> None:
    project = _project(
        architecture_data={
            "user_approved": True,
            "architecture": {"database_tables": [{"name": "users"}], "api_endpoints": []},
        }
    )

    assert [s["kind"] for s in codegen_runner.steps(project, {})] == ["model", "screen", "screen"]


def test_codegen_for_a_game_engine_target_generates_screens_only() -> None:
    """O3DE and Godot have no separate backend, so there are no model or
    routes steps to plan."""
    project = _project(
        architecture_data={
            "user_approved": True,
            "architecture": {
                "tech_stack": {"frontend": "O3DE (Open 3D Engine)"},
                "database_tables": [{"name": "users"}],
                "api_endpoints": [{"method": "GET", "path": "/x"}],
            },
        }
    )

    assert [s["kind"] for s in codegen_runner.steps(project, {})] == ["screen", "screen"]


def test_codegen_fingerprint_changes_when_the_architecture_does() -> None:
    before = codegen_runner.fingerprint(_project())

    changed = _project(
        architecture_data={
            "user_approved": True,
            "architecture": {
                "database_tables": [{"name": "users"}, {"name": "invoices"}],
                "api_endpoints": [{"method": "GET", "path": "/orders"}],
            },
        }
    )

    assert codegen_runner.fingerprint(changed) != before
    # Same inputs, same fingerprint — otherwise every retry would start
    # from scratch instead of resuming.
    assert codegen_runner.fingerprint(_project()) == before


def test_codegen_finalize_builds_the_project_from_saved_partial_files() -> None:
    """finalize() works off the run's saved state, which is what lets a
    run that was interrupted finish without regenerating anything."""
    state = {
        "model": [
            {
                "path": "backend/models/user.py",
                "language": "python",
                "content": "class User: pass",
                "description": "User model",
            }
        ],
        "routes": [],
        "screen": [
            {
                "path": "frontend/src/pages/Home.jsx",
                "language": "jsx",
                "content": "export default function Home() {}",
                "description": "Home screen",
            }
        ],
        "warnings": [{"path": "frontend/src/pages/Home.jsx", "reason": "no export"}],
    }
    project = _project()

    asyncio.run(codegen_runner.finalize(project, state))

    data = project.codegen_data
    paths = [f["path"] for f in data["codegen"]["files"]]
    assert "backend/models/user.py" in paths
    assert "frontend/src/pages/Home.jsx" in paths
    # The deterministic wiring pass runs at the end, not as AI steps.
    assert any(p.endswith("README_SETUP.md") for p in paths)
    assert data["validation_warnings"] == state["warnings"]
    assert data["user_approved"] is False
    assert set(data["stack_used"]) == {"codegen_target", "source", "fallback_reason"}


# ───────────────────────────────────────────────
#  UI/UX
# ───────────────────────────────────────────────
def test_uiux_only_knows_its_screen_steps_after_the_design_exists() -> None:
    project = _project(uiux_data=None)

    # Before the first step there is no screen list to plan from.
    assert [s["kind"] for s in uiux_runner.steps(project, {})] == ["design"]

    state = {
        "design": {
            "screens": [{"name": "Home"}, {"name": "Cart"}, {"name": "Profile"}],
        }
    }
    steps = uiux_runner.steps(project, state)

    assert [s["kind"] for s in steps] == ["design", "mockup", "mockup", "mockup"]
    assert steps[1]["label"] == "Mockup: Home"


def test_uiux_fingerprint_follows_the_approved_requirements() -> None:
    before = uiux_runner.fingerprint(_project())
    changed = _project(
        requirements_data={"user_approved": True, "frd": {"key_features": ["a", "b"]}}
    )

    assert uiux_runner.fingerprint(changed) != before


def test_uiux_finalize_saves_the_design_it_accumulated() -> None:
    project = _project(uiux_data=None)
    state = {"design": {"screens": [{"name": "Home", "generated_html": "<h1>Hi</h1>"}]}}

    asyncio.run(uiux_runner.finalize(project, state))

    assert project.uiux_data["design"] == state["design"]
    assert project.uiux_data["user_approved"] is False
    assert project.uiux_data["generated_at"]
