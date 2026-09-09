"""Every codegen adapter sends the project's shared preamble as `context`,
not inside its per-file prompt.

That split is what lets Anthropic's prompt cache serve the requirements
block on every file after the first (see _anthropic_content()). An
adapter that inlines the requirements again would silently pay full
price for them on every file — this pins it for all 34 prompts at once.
"""

import asyncio

import pytest

from app.ai import codegen_shared
from app.ai.codegen import godot, o3de
from app.ai.codegen.backend import BACKEND_ADAPTERS
from app.ai.codegen.frontend import FRONTEND_ADAPTERS
from app.ai.codegen.types import ModelCtx, RoutesCtx, ScreenCtx

REQUIREMENTS = "\nProblem this app solves: people lose track of their vinyl.\nKey features:\n- catalogue records\n"
TABLE = {
    "name": "records",
    "purpose": "A vinyl record",
    "description": "A vinyl record",
    "key_fields": ["id", "title", "artist"],
    "columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "title", "type": "string"},
        {"name": "artist", "type": "string"},
    ],
    "fields": [
        {"name": "id", "type": "integer"},
        {"name": "title", "type": "string"},
    ],
}
ENDPOINTS = [
    {"method": "GET", "path": "/records", "purpose": "List records"},
    {"method": "POST", "path": "/records", "purpose": "Add a record"},
]
SCREEN = {"name": "Collection", "purpose": "Browse the collection", "key_elements": ["grid"]}


@pytest.fixture
def calls(monkeypatch):
    """Capture every generate_text() call an adapter makes."""
    captured: list[dict] = []

    async def fake_generate_text(prompt, **kwargs):
        captured.append({"prompt": prompt, **kwargs})
        return {"text": "// generated\n"}

    monkeypatch.setattr(codegen_shared, "generate_text", fake_generate_text)
    return captured


def _assert_split(calls: list[dict], label: str = "App") -> None:
    assert calls, "adapter made no AI call"
    for call in calls:
        context = call.get("context")
        assert context, "adapter sent no shared context"
        assert context.startswith("You are Baby Tiger"), context[:60]
        assert f"{label}: Vinyl Vault" in context
        assert REQUIREMENTS.strip() in context
        # The per-file prompt carries only what differs per file.
        assert "You are Baby Tiger" not in call["prompt"]
        assert REQUIREMENTS.strip() not in call["prompt"]
        assert call["task_type"] == "codegen"


@pytest.mark.parametrize("key", sorted(BACKEND_ADAPTERS))
def test_backend_model_prompts_send_the_shared_context_separately(key, calls) -> None:
    adapter = BACKEND_ADAPTERS[key]
    ctx = ModelCtx(
        project_name="Vinyl Vault",
        table=TABLE,
        requirements_text=REQUIREMENTS,
        language=adapter.supported_languages[0],
    )

    asyncio.run(adapter.generate_model(ctx))

    _assert_split(calls)
    assert calls[0]["prompt"].startswith("Write ONE complete")


@pytest.mark.parametrize("key", sorted(BACKEND_ADAPTERS))
def test_backend_routes_prompts_send_the_shared_context_separately(key, calls) -> None:
    adapter = BACKEND_ADAPTERS[key]
    for api_style in adapter.supported_api_styles:
        calls.clear()
        ctx = RoutesCtx(
            project_name="Vinyl Vault",
            endpoints=ENDPOINTS,
            tables=[TABLE],
            requirements_text=REQUIREMENTS,
            api_style=api_style,
            language=adapter.supported_languages[0],
        )

        asyncio.run(adapter.generate_routes(ctx))

        _assert_split(calls)


@pytest.mark.parametrize("key", sorted(FRONTEND_ADAPTERS))
def test_frontend_screen_prompts_send_the_shared_context_separately(key, calls) -> None:
    adapter = FRONTEND_ADAPTERS[key]
    ctx = ScreenCtx(
        project_name="Vinyl Vault",
        screen=SCREEN,
        endpoints=ENDPOINTS,
        requirements_text=REQUIREMENTS,
        native_capabilities=[],
        language=adapter.supported_languages[0],
    )

    asyncio.run(adapter.generate_screen(ctx))

    _assert_split(calls)
    assert calls[0]["prompt"].startswith("Write ONE complete")


@pytest.mark.parametrize("engine,language", [(godot, "gdscript"), (o3de, "lua")])
def test_game_engine_prompts_keep_calling_the_project_a_game(engine, language, calls) -> None:
    ctx = ScreenCtx(
        project_name="Vinyl Vault",
        screen=SCREEN,
        endpoints=ENDPOINTS,
        requirements_text=REQUIREMENTS,
        native_capabilities=[],
        language=language,
    )

    asyncio.run(engine.generate_screen(ctx))

    _assert_split(calls, label="Game")


def test_the_validation_retry_reuses_the_same_context(calls, monkeypatch) -> None:
    """The retry is a cache hit on the shared block only if it sends the
    identical context — a retry that rebuilt or dropped it would pay
    for the requirements twice."""
    monkeypatch.setattr(
        codegen_shared, "validate_generated_content", lambda language, content: "looks truncated"
    )

    asyncio.run(
        codegen_shared.generate_text_validated(
            "Write ONE file", "python", None, context="You are Baby Tiger. App: X"
        )
    )

    assert len(calls) == 2
    assert calls[0]["context"] == calls[1]["context"] == "You are Baby Tiger. App: X"
    assert calls[1]["prompt"].startswith("Write ONE file")
    assert "looks truncated" in calls[1]["prompt"]
