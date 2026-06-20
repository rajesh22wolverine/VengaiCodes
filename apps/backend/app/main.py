# ═══════════════════════════════════════════════════════════════
#  VengaiCode — FastAPI Application Entry Point
#  app/main.py — App factory, middleware, lifespan, routers
#  Vengai (வேங்கை) = Tiger in Tamil 🐯
# ═══════════════════════════════════════════════════════════════

import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.database import Base, engine
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

# ─── Logging Setup ───────────────────────────────────────────
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": "DEBUG" if settings.DEBUG else "INFO",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG" if settings.DEBUG else "INFO",
    },
    "loggers": {
        "vengaicode": {"level": "DEBUG" if settings.DEBUG else "INFO", "propagate": True},
        "uvicorn": {"level": "INFO", "propagate": True},
        "sqlalchemy.engine": {"level": "WARNING", "propagate": True},
        "aiosqlite": {"level": "WARNING", "propagate": True},
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("vengaicode")


# ─── Lifespan ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown lifecycle manager.
    Runs startup tasks before serving requests, shutdown tasks after.
    """
    # ── Startup ──
    logger.info("🐯 VengaiCode Backend Starting...")
    logger.info(f"   Environment: {settings.ENVIRONMENT}")
    logger.info(f"   Debug mode:  {settings.DEBUG}")
    logger.info(f"   App version: {settings.APP_VERSION}")

    # ── Database Initialization ──
    try:
        async with engine.begin() as conn:
            # Step 1 — Create all tables (skips existing tables)
            await conn.run_sync(
                lambda c: Base.metadata.create_all(c, checkfirst=True)
            )
            # Step 2 — Create indexes individually with checkfirst
            # This prevents "index already exists" errors when a column
            # has both index=True AND an explicit Index() in __table_args__
            for table in Base.metadata.tables.values():
                for index in table.indexes:
                    try:
                        await conn.run_sync(
                            lambda c, idx=index: idx.create(c, checkfirst=True)
                        )
                    except Exception as idx_err:
                        # Log at debug level only — duplicate indexes are
                        # expected during development and are harmless
                        logger.debug(
                            f"Skipping index {index.name}: {idx_err}"
                        )
        logger.info("✅ Database tables created/verified")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

    # ── Redis Connection (optional — gracefully skipped if unavailable) ──
    try:
        from app.core.redis import get_redis
        redis = await get_redis()
        await redis.ping()
        logger.info("✅ Redis connection established")
    except Exception as e:
        logger.warning(f"⚠️  Redis connection failed: {e} — caching disabled")

    # ── AI Backend Check (optional — Groq fallback if Ollama unavailable) ──
    try:
        from app.ai.orchestrator import check_ai_availability
        ai_status = await check_ai_availability()
        if ai_status["ollama"]:
            models = ai_status.get("ollama_models", [])
            logger.info(
                f"✅ Ollama connected — {len(models)} model(s) available: "
                f"{', '.join(models[:3]) or 'none pulled yet'}"
            )
        else:
            logger.warning("⚠️  Ollama not available — will use Groq cloud fallback")

        if ai_status["groq"]:
            logger.info("✅ Groq API key configured — cloud fallback ready")
        else:
            logger.warning(
                "⚠️  Groq API key not set — AI features will be limited. "
                "Set GROQ_API_KEY in .env to enable cloud fallback."
            )
    except Exception as e:
        logger.warning(f"⚠️  AI status check failed: {e}")

    logger.info("🐯 VengaiCode Backend Ready!")
    logger.info(f"   Docs: http://localhost:8000/docs")

    yield  # ← Application runs here, serving requests

    # ── Shutdown ──
    logger.info("🐯 VengaiCode Backend Shutting Down...")
    await engine.dispose()
    logger.info("✅ Database connections closed")


# ─── FastAPI App Factory ──────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "VengaiCode API — AI-powered app creation platform. "
            "Vengai (வேங்கை) = Tiger in Tamil 🐯"
        ),
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # ── CORS ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Rate Limiting ──
    app.add_middleware(
        RateLimitMiddleware,
        calls=settings.RATE_LIMIT_CALLS,
        period=settings.RATE_LIMIT_PERIOD,
    )

    # ── Request Logging ──
    app.add_middleware(LoggingMiddleware)

    # ── Routers ──
    from app.api.v1.router import api_router
    app.include_router(
        api_router,
        prefix=settings.API_V1_PREFIX,
    )

    # ── Health Check ──
    @app.get("/health", tags=["Health"], include_in_schema=False)
    async def health_check():
        return JSONResponse(
            content={
                "status": "healthy",
                "app": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "environment": settings.ENVIRONMENT,
                "message": "Baby Tiger is awake and ready! 🐯",
            }
        )

    # ── Root ──
    @app.get("/", tags=["Root"], include_in_schema=False)
    async def root():
        return JSONResponse(
            content={
                "message": f"Welcome to {settings.APP_NAME} API 🐯",
                "version": settings.APP_VERSION,
                "docs": "/docs",
                "health": "/health",
            }
        )

    return app


# ─── App Instance ─────────────────────────────────────────────
app = create_app()
