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
from sqlalchemy import text, event
from sqlalchemy.schema import CreateIndex

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


async def init_db():
    """
    Initialize database tables and indexes safely.

    Root cause of the duplicate index bug:
    SQLAlchemy's create_all() always emits CREATE INDEX for every Index()
    defined in __table_args__, PLUS for every column with index=True.
    When both exist for the same column, SQLite gets duplicate CREATE INDEX
    calls and crashes — checkfirst=True on create_all() only skips tables,
    not indexes.

    Fix: use CREATE TABLE only (no indexes), then create all indexes
    manually using SQLite's native "CREATE INDEX IF NOT EXISTS" syntax
    which is guaranteed to never fail on duplicates.
    """
    # Step 1 — collect all indexes from metadata, then temporarily remove
    # them so create_all() creates tables only (no index DDL emitted)
    all_indexes = {}
    for table in Base.metadata.tables.values():
        all_indexes[table.name] = list(table.indexes)
        table.indexes.clear()

    try:
        # Step 2 — create tables only, no indexes
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: Base.metadata.create_all(c, checkfirst=True)
            )
        logger.info("✅ Database tables created/verified")
    finally:
        # Step 3 — restore indexes to metadata (important for ORM queries)
        for table in Base.metadata.tables.values():
            if table.name in all_indexes:
                for idx in all_indexes[table.name]:
                    table.indexes.add(idx)

    # Step 4 — create indexes using native SQLite IF NOT EXISTS
    # This never fails regardless of duplicates
    async with engine.begin() as conn:
        for table_name, indexes in all_indexes.items():
            seen = set()  # deduplicate by index name
            for index in indexes:
                if index.name in seen:
                    continue
                seen.add(index.name)
                cols = ", ".join(col.name for col in index.columns)
                unique = "UNIQUE " if index.unique else ""
                sql = (
                    f"CREATE {unique}INDEX IF NOT EXISTS "
                    f"{index.name} ON {table_name} ({cols})"
                )
                try:
                    await conn.execute(text(sql))
                    logger.debug(f"Index ensured: {index.name}")
                except Exception as e:
                    logger.warning(f"Index {index.name} skipped: {e}")

    logger.info("✅ Database indexes created/verified")


# ─── Lifespan ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown lifecycle manager.
    """
    # ── Startup ──
    logger.info("🐯 VengaiCode Backend Starting...")
    logger.info(f"   Environment: {settings.ENVIRONMENT}")
    logger.info(f"   Debug mode:  {settings.DEBUG}")
    logger.info(f"   App version: {settings.APP_VERSION}")

    # ── Database ──
    try:
        await init_db()
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

    # ── Redis (optional) ──
    try:
        from app.core.redis import get_redis
        redis = await get_redis()
        await redis.ping()
        logger.info("✅ Redis connection established")
    except Exception as e:
        logger.warning(f"⚠️  Redis connection failed: {e} — caching disabled")

    # ── AI Backend Check (optional) ──
    try:
        from app.ai.orchestrator import check_ai_availability
        ai_status = await check_ai_availability()
        if ai_status["ollama"]:
            models = ai_status.get("ollama_models", [])
            logger.info(f"✅ Ollama connected — {len(models)} model(s) available")
        else:
            logger.warning("⚠️  Ollama not available — will use Groq cloud fallback")
        if ai_status["groq"]:
            logger.info("✅ Groq API key configured — cloud fallback ready")
        else:
            logger.warning("⚠️  Groq API key not set — set GROQ_API_KEY in .env")
    except Exception as e:
        logger.warning(f"⚠️  AI status check failed: {e}")

    logger.info("🐯 VengaiCode Backend Ready!")

    yield  # ← Application runs here

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
