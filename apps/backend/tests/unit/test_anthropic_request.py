"""What one Anthropic call actually sends — the two things that decide
what a build costs: the effort level, and whether the shared block is
laid out so the prompt cache can hit it.
"""

import asyncio
import logging

import pytest

from app.ai import orchestrator
from app.config import settings


class _FakeResponse:
    status_code = 200

    def __init__(self, body: dict):
        self._body = body
        self.text = ""

    def json(self) -> dict:
        return self._body


@pytest.fixture
def sent(monkeypatch):
    """Capture the JSON body of the request _call_anthropic() makes."""
    bodies: list[dict] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            bodies.append(json)
            return _FakeResponse(
                {
                    "content": [
                        {"type": "thinking", "thinking": ""},
                        {"type": "text", "text": "def x(): pass"},
                    ],
                    "usage": {
                        "input_tokens": 40,
                        "output_tokens": 300,
                        "cache_read_input_tokens": 900,
                        "cache_creation_input_tokens": 0,
                    },
                    "stop_reason": "end_turn",
                }
            )

    monkeypatch.setattr(orchestrator.httpx, "AsyncClient", FakeClient)
    return bodies


def _call(prompt="Write ONE file", context=None):
    return asyncio.run(
        orchestrator._call_anthropic(
            "https://api.anthropic.com/v1", "sk-test", "claude-opus-5", prompt, context=context
        )
    )


def test_effort_from_settings_is_sent_as_output_config(sent, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_EFFORT", "low")

    _call()

    assert sent[0]["output_config"] == {"effort": "low"}
    assert sent[0]["model"] == "claude-opus-5"
    assert sent[0]["max_tokens"] == settings.ANTHROPIC_MAX_OUTPUT_TOKENS


def test_blank_effort_sends_nothing_so_the_model_default_applies(sent, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_EFFORT", "")

    _call()

    assert "output_config" not in sent[0]


def test_an_unknown_effort_is_dropped_rather_than_failing_every_call(sent, monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_EFFORT", "turbo")

    with caplog.at_level(logging.WARNING):
        _call()

    assert "output_config" not in sent[0]
    assert "ANTHROPIC_EFFORT" in caplog.text


def test_shared_context_is_its_own_cached_block_ahead_of_the_prompt(sent) -> None:
    _call(prompt="Write ONE file for records", context="You are Baby Tiger. App: Vinyl Vault")

    blocks = sent[0]["messages"][0]["content"]
    assert [b["text"] for b in blocks] == [
        "You are Baby Tiger. App: Vinyl Vault",
        "Write ONE file for records",
    ]
    # The breakpoint sits on the shared block, so the per-file prompt
    # after it can differ without spoiling the match.
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1]


def test_without_context_the_single_block_is_still_marked(sent) -> None:
    _call(prompt="Design a UI system")

    blocks = sent[0]["messages"][0]["content"]
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_text_is_collected_past_the_thinking_block_and_usage_keeps_cache_counts(sent) -> None:
    text, _duration, usage = _call()

    assert text == "def x(): pass"
    assert usage["prompt_tokens"] == 40
    assert usage["completion_tokens"] == 300
    assert usage["cache_read_input_tokens"] == 900


def test_every_call_logs_its_token_usage(caplog) -> None:
    with caplog.at_level(logging.INFO):
        orchestrator._log_usage(
            "platform:anthropic",
            "claude-opus-5",
            "codegen",
            1234.0,
            {
                "prompt_tokens": 40,
                "completion_tokens": 300,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 0,
            },
        )

    line = caplog.text
    assert "platform:anthropic" in line
    assert "in=40" in line and "out=300" in line and "cache_read=900" in line
