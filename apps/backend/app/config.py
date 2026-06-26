# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Application Configuration
#  config.py — All settings loaded from environment variables
#  Uses Pydantic BaseSettings for type-safe config
# ═══════════════════════════════════════════════════════════════

from typing import List, Optional
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    VengaiCode application settings.
    All values loaded from environment variables.
    Defaults provided for local development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ───────────────────────────────────────────
    #  App Configuration
    # ───────────────────────────────────────────
    APP_NAME: str = "VengaiCode"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # ───────────────────────────────────────────
    #  Security
    # ───────────────────────────────────────────
    JWT_SECRET: str = "changeme_generate_with_openssl_rand_hex_32"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    ENCRYPTION_KEY: str = "changeme_generate_with_openssl_rand_hex_32"

    # RSA Keys for Licence System
    RSA_PRIVATE_KEY_PATH: str = "./keys/private.pem"
    RSA_PUBLIC_KEY_PATH: str = "./keys/public.pem"

    # Admin Secret for hidden admin panel
    ADMIN_SECRET_KEY: str = "changeme_admin_secret"
    ADMIN_EMAIL: str = ""

    # Baby Tiger Stamp Cryptographic Key 🐯
    TIGER_STAMP_ENABLED: bool = True
    TIGER_STAMP_CRYPTOGRAPHIC_KEY: str = "changeme_tiger_stamp_key"

    # ───────────────────────────────────────────
    #  Database — PostgreSQL (Supabase) or SQLite (local dev)
    # ───────────────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://vengaicode_user:vengaicode_pass_dev"
        "@localhost:5432/vengaicode"
    )
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_ECHO: bool = False

    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # ───────────────────────────────────────────
    #  Redis Cache
    # ───────────────────────────────────────────
    REDIS_URL: str = "redis://:vengaicode_redis_dev@localhost:6379/0"
    REDIS_PASSWORD: str = "vengaicode_redis_dev"
    REDIS_MAX_CONNECTIONS: int = 10

    # Cache TTLs (seconds)
    CACHE_TTL_SHORT: int = 300       # 5 minutes
    CACHE_TTL_MEDIUM: int = 3600     # 1 hour
    CACHE_TTL_LONG: int = 86400      # 24 hours
    CACHE_TTL_LICENCE: int = 300     # 5 minutes for licence verification

    # ───────────────────────────────────────────
    #  Upstash Redis (Production)
    # ───────────────────────────────────────────
    UPSTASH_REDIS_URL: str = ""
    UPSTASH_REDIS_TOKEN: str = ""

    # ───────────────────────────────────────────
    #  AI Configuration
    # ───────────────────────────────────────────

    # Ollama — Local AI (runs on user's machine)
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_TIMEOUT: int = 120
    OLLAMA_DEFAULT_MODEL: str = "deepseek-coder"
    OLLAMA_FALLBACK_MODEL: str = "phi3"

    # AI Models by use case
    OLLAMA_CODE_MODEL: str = "deepseek-coder"
    OLLAMA_CHAT_MODEL: str = "qwen2.5-coder"
    OLLAMA_SMALL_MODEL: str = "phi3"

    # Groq API — Cloud Fallback (FREE tier: 14,400 req/day)
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_TIMEOUT: int = 60
    GROQ_DEFAULT_MODEL: str = "llama3-70b-8192"
    GROQ_CODE_MODEL: str = "llama3-70b-8192"

    # AI Performance Thresholds
    AI_SLOW_RESPONSE_THRESHOLD_MS: int = 3000
    AI_CRITICAL_RESPONSE_THRESHOLD_MS: int = 10000

    # AI Generation Settings
    AI_MAX_TOKENS: int = 4096
    AI_TEMPERATURE: float = 0.1
    AI_CODE_TEMPERATURE: float = 0.05

    # ───────────────────────────────────────────
    #  File Storage — Cloudflare R2
    # ───────────────────────────────────────────
    CLOUDFLARE_R2_ACCESS_KEY: str = ""
    CLOUDFLARE_R2_SECRET: str = ""
    CLOUDFLARE_R2_BUCKET: str = "vengaicode-files"
    CLOUDFLARE_R2_ENDPOINT: str = ""

    # ───────────────────────────────────────────
    #  Payment — Razorpay
    # ───────────────────────────────────────────
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    RAZORPAY_CURRENCY: str = "INR"

    # Commission Rates
    COMMISSION_MARKETPLACE_PERCENT: float = 10.0
    COMMISSION_EXTERNAL_PERCENT: float = 25.0
    COMMISSION_TEMPLATE_PERCENT: float = 10.0

    # ───────────────────────────────────────────
    #  Identity Verification — Digio
    # ───────────────────────────────────────────
    DIGIO_API_KEY: str = ""
    DIGIO_API_SECRET: str = ""
    DIGIO_BASE_URL: str = "https://ext.digio.in:444"

    # ───────────────────────────────────────────
    #  SMS — MSG91
    # ───────────────────────────────────────────
    MSG91_API_KEY: str = ""
    MSG91_SENDER_ID: str = "VENGAI"
    MSG91_TEMPLATE_ID: str = ""
    MSG91_OTP_EXPIRE_MINUTES: int = 10

    # ───────────────────────────────────────────
    #  Email — Resend
    # ───────────────────────────────────────────
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "support@vengaicode.com"
    EMAIL_FROM_NAME: str = "VengaiCode"

    # ───────────────────────────────────────────
    #  Search — MeiliSearch
    # ───────────────────────────────────────────
    MEILISEARCH_HOST: str = "http://localhost:7700"
    MEILISEARCH_KEY: str = "vengaicode_meili_dev_key"

    # ───────────────────────────────────────────
    #  Error Tracking — Sentry
    # ───────────────────────────────────────────
    SENTRY_DSN: str = ""

    # ───────────────────────────────────────────
    #  Rate Limiting
    # ───────────────────────────────────────────
    RATE_LIMIT_CALLS: int = 100
    RATE_LIMIT_PERIOD: int = 60
    RATE_LIMIT_AUTH_CALLS: int = 10
    RATE_LIMIT_AUTH_PERIOD: int = 60
    RATE_LIMIT_AI_CALLS: int = 20
    RATE_LIMIT_AI_PERIOD: int = 60

    # ───────────────────────────────────────────
    #  CORS — Allowed Origins
    # ───────────────────────────────────────────
    ALLOWED_ORIGINS_STR: str = (
        "http://localhost:1420,"
        "http://localhost:3000,"
        "http://localhost:3002,"
        "tauri://localhost,"
        "https://vengaicode.com,"
        "https://admin.vengaicode.com,"
        "https://vengaicode-backend.onrender.com"
    )

    ALLOWED_ORIGINS_PATTERNS: list = [
        "github.dev",
        "gitpod.io",
        "app.github.dev",
    ]

    @property
    def ALLOWED_ORIGINS(self) -> List[str]:
        origins = [o.strip() for o in self.ALLOWED_ORIGINS_STR.split(",") if o.strip()]
        # Always allow GitHub Codespaces and Gitpod in development
        if self.ENVIRONMENT == "development":
            origins.extend([
                "https://*.app.github.dev",
                "https://*.gitpod.io",
            ])
        return origins

    # ───────────────────────────────────────────
    #  Pricing Tiers
    # ───────────────────────────────────────────
    PRICING_FREE_PROJECTS: int = 1
    PRICING_CREATOR_PROJECTS: int = 5
    PRICING_PROFESSIONAL_PROJECTS: int = 15
    PRICING_STUDIO_PROJECTS: int = -1

    PRICING_CREATOR_PRICE_INR: float = 1999.0
    PRICING_PROFESSIONAL_PRICE_INR: float = 3499.0
    PRICING_STUDIO_PRICE_INR: float = 6000.0
    PRICING_WL_BASIC_PRICE_INR: float = 15000.0
    PRICING_WL_PRO_PRICE_INR: float = 25000.0
    PRICING_WL_FULL_PRICE_INR: float = 50000.0

    # ───────────────────────────────────────────
    #  Validators
    # ───────────────────────────────────────────
    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v

    @field_validator("JWT_ALGORITHM")
    @classmethod
    def validate_jwt_algorithm(cls, v: str) -> str:
        allowed = {"HS256", "HS384", "HS512", "RS256"}
        if v not in allowed:
            raise ValueError(f"JWT_ALGORITHM must be one of {allowed}")
        return v

    @model_validator(mode="after")
    def warn_about_defaults(self) -> "Settings":
        """Warn if dangerous default values are used in production."""
        if self.ENVIRONMENT == "production":
            dangerous_defaults = [
                ("JWT_SECRET", self.JWT_SECRET, "changeme_generate_with_openssl_rand_hex_32"),
                ("ENCRYPTION_KEY", self.ENCRYPTION_KEY, "changeme_generate_with_openssl_rand_hex_32"),
                ("ADMIN_SECRET_KEY", self.ADMIN_SECRET_KEY, "changeme_admin_secret"),
            ]
            for name, value, default in dangerous_defaults:
                if value == default:
                    raise ValueError(
                        f"❌ {name} is using default value in production! "
                        f"Generate a secure value: openssl rand -hex 32"
                    )
        return self

    # ───────────────────────────────────────────
    #  Helper Properties
    # ───────────────────────────────────────────
    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def database_url_async(self) -> str:
        """Return async-compatible DB URL for SQLAlchemy (Postgres or SQLite)."""
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("sqlite://"):
            url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return url


# ───────────────────────────────────────────────
#  Singleton Settings Instance
#  Use @lru_cache so settings loaded only once
# ───────────────────────────────────────────────
@lru_cache()
def get_settings() -> Settings:
    return Settings()


# Global settings instance — import this everywhere
settings = get_settings()