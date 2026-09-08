# ═══════════════════════════════════════════════════════════════
#  Guards the one thing that is safe to assert about a model id across
#  every provider: it never contains whitespace.
#
#  model_name goes VERBATIM to the provider (orchestrator._call_anthropic
#  sends {"model": model}), so it must be the provider's exact id, not a
#  display name. Before this validator existed nothing checked it, and a
#  bad id was invisible until generation time — the row saved fine and
#  the admin screen rendered it "Active · key set". A live platform
#  default sat as "opus 5" instead of "claude-opus-5" at the bottom of
#  the fallback chain, where a silent 404 is least likely to be spotted.
#
#  The accept-list below matters as much as the reject-list: id formats
#  vary wildly between providers (slashes, colons, dots), so this test
#  exists to stop the rule being tightened into something that breaks a
#  legitimate provider.
# ═══════════════════════════════════════════════════════════════

import pytest
from pydantic import ValidationError

from app.schemas.ai_config import (
    AdminAIConfigCreate,
    AdminAIConfigUpdate,
    AIConfigCreate,
    AIConfigUpdate,
)

# Real ids, one per provider path the orchestrator can take.
VALID_MODEL_IDS = [
    "claude-opus-5",              # anthropic
    "openai/gpt-oss-120b",        # groq — slash
    "deepseek/deepseek-v4-pro-0813",  # openrouter via custom
    "qwen2.5-coder:7b",           # ollama — colon + dot
    "grok-4",                     # xai
    "gpt-6-astra",                # openai
]


@pytest.mark.parametrize("model_id", VALID_MODEL_IDS)
def test_real_provider_model_ids_are_accepted(model_id):
    assert AdminAIConfigCreate(
        provider_type="custom", model_name=model_id, label="x"
    ).model_name == model_id


@pytest.mark.parametrize(
    "schema, kwargs",
    [
        (AdminAIConfigCreate, {"provider_type": "anthropic", "label": "VengaiClaude"}),
        (AIConfigCreate, {"provider_type": "anthropic", "label": "x"}),
        (AdminAIConfigUpdate, {}),
        (AIConfigUpdate, {}),
    ],
)
def test_a_display_name_is_rejected_on_every_schema(schema, kwargs):
    """"opus 5" is the exact value that reached production."""
    with pytest.raises(ValidationError) as exc:
        schema(model_name="opus 5", **kwargs)
    assert "contains a space" in str(exc.value)


def test_the_error_suggests_the_hyphenated_form():
    with pytest.raises(ValidationError) as exc:
        AdminAIConfigUpdate(model_name="opus 5")
    assert "'opus-5'" in str(exc.value)


def test_surrounding_whitespace_is_stripped_not_rejected():
    assert AdminAIConfigUpdate(model_name="  claude-opus-5  ").model_name == "claude-opus-5"


def test_whitespace_only_is_rejected():
    with pytest.raises(ValidationError):
        AdminAIConfigUpdate(model_name="   ")


def test_omitting_model_name_on_a_patch_is_still_allowed():
    """PATCH bodies legitimately omit the field — the validator must not fire."""
    assert AdminAIConfigUpdate(label="renamed").model_name is None
