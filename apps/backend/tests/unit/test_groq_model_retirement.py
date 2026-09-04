"""
Regression tests for Groq model retirement.

Groq shuts models down on a published schedule, and a retired id 404s
with "model_not_found" rather than degrading — which is how the platform
default silently became unservable twice (llama3-70b-8192 in 2025,
llama-3.3-70b-versatile in 2026) and every generation phase started
returning 503.

Two things have to hold: the configured defaults must not themselves be
retired ids, and an already-seeded platform bag row pinned to a retired
id must get repointed on startup — bumping the config default alone
does nothing, because seeding never updates an existing row.
"""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.orchestrator import retire_decommissioned_groq_models
from app.config import DECOMMISSIONED_GROQ_MODELS, Settings, settings
from app.core.database import Base
from app.models.ai_config import UserAIConfig

# app.models has an empty __init__, so importing UserAIConfig alone leaves
# SQLAlchemy's registry half-populated and User's relationship("Project")
# fails to resolve the moment any mapper is configured. Import the rest so
# the registry is whole — same reason main.py imports them all at startup.
import app.models.figma_connection  # noqa: E402,F401
import app.models.marketplace  # noqa: E402,F401
import app.models.project  # noqa: E402,F401
import app.models.settings  # noqa: E402,F401
import app.models.user  # noqa: E402,F401


def test_configured_groq_defaults_are_not_decommissioned() -> None:
    """The bug itself: shipping a default that Groq has already shut
    down. Anything added to DECOMMISSIONED_GROQ_MODELS must be moved off
    of in config.py at the same time."""
    assert settings.GROQ_DEFAULT_MODEL not in DECOMMISSIONED_GROQ_MODELS
    assert settings.GROQ_CODE_MODEL not in DECOMMISSIONED_GROQ_MODELS


def test_replacements_are_not_themselves_decommissioned() -> None:
    """A replacement that points at another retired id would migrate one
    dead model onto another — llama3-70b-8192's official successor was
    llama-3.3-70b-versatile, which has since been retired too."""
    for retired, replacement in DECOMMISSIONED_GROQ_MODELS.items():
        assert replacement not in DECOMMISSIONED_GROQ_MODELS, (
            f"{retired} is migrated onto {replacement}, which is also "
            f"decommissioned"
        )


def test_env_var_cannot_pin_a_retired_model() -> None:
    """The production failure mode: an env var (Render's dashboard)
    overrides the corrected code default and silently reinstates a dead
    model. Fixing the default alone can't prevent that, because env
    always wins — so the value is substituted whatever set it."""
    s = Settings(
        GROQ_DEFAULT_MODEL="llama-3.3-70b-versatile",
        GROQ_CODE_MODEL="llama3-70b-8192",
    )
    assert s.GROQ_DEFAULT_MODEL == "openai/gpt-oss-120b"
    assert s.GROQ_CODE_MODEL == "openai/gpt-oss-120b"


def test_retired_model_is_honoured_when_explicitly_allowed() -> None:
    """llama-3.3-70b-versatile still runs on committed-spend enterprise
    contracts, so the substitution must be overridable rather than
    absolute."""
    s = Settings(
        GROQ_DEFAULT_MODEL="llama-3.3-70b-versatile",
        GROQ_ALLOW_RETIRED_MODELS=True,
    )
    assert s.GROQ_DEFAULT_MODEL == "llama-3.3-70b-versatile"


def test_live_model_passes_through_untouched() -> None:
    """Only known-dead ids are rewritten — an unrecognised or current
    model id must survive exactly as configured."""
    s = Settings(GROQ_DEFAULT_MODEL="qwen/qwen3.6-27b")
    assert s.GROQ_DEFAULT_MODEL == "qwen/qwen3.6-27b"


class _Bag:
    """An in-memory stand-in for the real session factory, so the
    migration can be exercised without a live Postgres."""

    def __init__(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def setup(self, rows: list[UserAIConfig]) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all, tables=[UserAIConfig.__table__]
            )
        async with self.session_factory() as db:
            db.add_all(rows)
            await db.commit()

    async def model_names(self) -> dict[str, str]:
        async with self.session_factory() as db:
            from sqlalchemy import select

            result = await db.execute(select(UserAIConfig))
            return {c.label: c.model_name for c in result.scalars().all()}


def _config(**kwargs) -> UserAIConfig:
    defaults = dict(
        id=str(uuid.uuid4()),
        user_id=None,
        provider_type="groq",
        base_url="https://api.groq.com/openai/v1",
        model_name="llama-3.3-70b-versatile",
        label="Platform default (Groq)",
        is_active=True,
    )
    defaults.update(kwargs)
    return UserAIConfig(**defaults)


def _run_migration_over(rows: list[UserAIConfig], monkeypatch) -> dict[str, str]:
    bag = _Bag()

    async def scenario() -> dict[str, str]:
        await bag.setup(rows)
        monkeypatch.setattr(
            "app.ai.orchestrator.AsyncSessionLocal", bag.session_factory
        )
        await retire_decommissioned_groq_models()
        return await bag.model_names()

    return asyncio.run(scenario())


def test_platform_row_on_retired_model_is_repointed(monkeypatch) -> None:
    names = _run_migration_over([_config()], monkeypatch)
    assert names["Platform default (Groq)"] == "openai/gpt-oss-120b"


def test_platform_row_on_live_model_is_left_alone(monkeypatch) -> None:
    """An admin who has already picked a current model must not have it
    rewritten out from under them."""
    names = _run_migration_over(
        [_config(model_name="qwen/qwen3.6-27b")], monkeypatch
    )
    assert names["Platform default (Groq)"] == "qwen/qwen3.6-27b"


def test_user_owned_byo_row_is_never_touched(monkeypatch) -> None:
    """A user's own config is their key and their model choice — if they
    pinned a retired model, the bag skips past the failure instead of us
    silently editing their row."""
    names = _run_migration_over(
        [_config(user_id=str(uuid.uuid4()), label="My Groq key")], monkeypatch
    )
    assert names["My Groq key"] == "llama-3.3-70b-versatile"


def test_non_groq_row_is_never_touched(monkeypatch) -> None:
    """Model ids are namespaced per provider — a collision on another
    provider must not trigger a Groq migration."""
    names = _run_migration_over(
        [
            _config(
                provider_type="custom",
                base_url="http://127.0.0.1:10086/v1",
                label="Self-hosted",
            )
        ],
        monkeypatch,
    )
    assert names["Self-hosted"] == "llama-3.3-70b-versatile"
