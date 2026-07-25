# ═══════════════════════════════════════════════════════════════
#  VengaiCode — User AI Config Schemas
#  schemas/ai_config.py — Request/response shapes for BYO AI models
# ═══════════════════════════════════════════════════════════════

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ProviderType = Literal["groq", "openai", "anthropic", "custom"]

# All schemas below have a `model_name` field, which collides with
# Pydantic v2's reserved `model_*` namespace — silence the warning.
_ALLOW_MODEL_NAME = ConfigDict(protected_namespaces=())

# Known default base URLs — only "custom" requires the user to supply one.
DEFAULT_BASE_URLS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
}

# Providers that require an API key (unlike "custom", which usually
# points at a keyless local server).
PROVIDERS_REQUIRING_KEY = {"groq", "openai", "anthropic"}


# ───────────────────────────────────────────────
#  Create / Update
# ───────────────────────────────────────────────
class AIConfigCreate(BaseModel):
    model_config = _ALLOW_MODEL_NAME

    provider_type: ProviderType
    base_url: Optional[str] = None
    # Required for "custom"; falls back to DEFAULT_BASE_URLS for groq/openai.
    api_key: Optional[str] = Field(None, max_length=500)
    # Plaintext in the request only — encrypted before it touches the DB.
    model_name: str = Field(..., min_length=1, max_length=255)
    label: str = Field(..., min_length=1, max_length=100)
    is_active: bool = False


class AIConfigUpdate(BaseModel):
    model_config = _ALLOW_MODEL_NAME

    base_url: Optional[str] = None
    api_key: Optional[str] = Field(None, max_length=500)
    model_name: Optional[str] = Field(None, min_length=1, max_length=255)
    label: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None


# ───────────────────────────────────────────────
#  Response — mirrors models/ai_config.py UserAIConfig
#  Never includes the raw/decrypted key — only whether one is set.
# ───────────────────────────────────────────────
class AIConfigResponse(BaseModel):
    id: str
    provider_type: str
    base_url: str
    has_api_key: bool
    model_name: str
    label: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    @classmethod
    def from_db(cls, config) -> "AIConfigResponse":
        return cls(
            id=config.id,
            provider_type=config.provider_type,
            base_url=config.base_url,
            has_api_key=bool(config.api_key_encrypted),
            model_name=config.model_name,
            label=config.label,
            is_active=config.is_active,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


class AIConfigListResponse(BaseModel):
    success: bool = True
    configs: list[AIConfigResponse]
    total: int


class AIConfigDetailResponse(BaseModel):
    success: bool = True
    config: AIConfigResponse


class DeleteAIConfigResponse(BaseModel):
    success: bool = True
    message: str = "AI model configuration deleted successfully."
