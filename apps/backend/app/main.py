# ═══════════════════════════════════════════════════════════════
#  VengaiCode — FastAPI Application Entry Point
#  app/main.py — App factory, middleware, lifespan, routers
#  Vengai (வேங்கை) = Tiger in Tamil 🐯
# ═══════════════════════════════════════════════════════════════

import json
import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text, inspect
from sqlalchemy.types import JSON

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


def _column_default_sql(column) -> str:
    """
    Render a SQL literal for a NOT NULL column's default, so ALTER TABLE
    ADD COLUMN can backfill existing rows. Mirrors the column's Python-side
    `default=` (JSON list/dict, bool, number, string, enum) — server_default
    (e.g. func.now()) is used as-is when present.
    """
    if column.server_default is not None:
        return str(column.server_default.arg)

    value = None
    if column.default is not None:
        arg = column.default.arg
        if callable(arg):
            try:
                value = arg()
            except TypeError:
                value = arg(None)  # context-sensitive default callable
        else:
            value = arg

    if isinstance(column.type, JSON):
        return "'%s'" % json.dumps(value if value is not None else {})
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'%s'" % value.replace("'", "''")
    if hasattr(value, "value"):  # Enum member
        return "'%s'" % str(value.value).replace("'", "''")
    return "NULL"


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

    # Step 3.5 — add columns missing from tables that already existed.
    # create_all(checkfirst=True) skips a table entirely if it already
    # exists — it never ALTERs it to pick up columns added to the model
    # later (e.g. Project.chat_messages), so those silently never reach
    # production until we add them explicitly here.
    async with engine.begin() as conn:
        def get_existing_columns(sync_conn):
            inspector = inspect(sync_conn)
            return {
                table_name: {col["name"] for col in inspector.get_columns(table_name)}
                for table_name in inspector.get_table_names()
            }
        existing_columns = await conn.run_sync(get_existing_columns)

        for table in Base.metadata.tables.values():
            db_columns = existing_columns.get(table.name)
            if db_columns is None:
                continue  # brand new table — create_all already added every column
            for column in table.columns:
                if column.name in db_columns:
                    continue
                ddl_type = column.type.compile(dialect=engine.dialect)
                default_clause = ""
                if not column.nullable:
                    default_clause = f" DEFAULT {_column_default_sql(column)}"
                nullable_clause = "" if column.nullable else " NOT NULL"
                sql = (
                    f"ALTER TABLE {table.name} ADD COLUMN {column.name} "
                    f"{ddl_type}{default_clause}{nullable_clause}"
                )
                try:
                    await conn.execute(text(sql))
                    logger.info(f"✅ Added missing column {table.name}.{column.name}")
                except Exception as e:
                    logger.warning(f"Column {table.name}.{column.name} skipped: {e}")

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

    # Step 5 — relax constraints on existing columns that changed shape.
    # Unlike Step 3.5 (missing columns), create_all()/ALTER-ADD never
    # touches a column that already exists — so a column whose model
    # definition changed (e.g. user_ai_configs.user_id going NOT NULL ->
    # nullable, to allow platform-default rows) needs its own explicit
    # migration. A *fresh* SQLite create_all() already gets the nullable
    # version for free, but a pre-existing local SQLite DB (any dev who
    # already had this table before the column changed shape) still has
    # the old NOT NULL constraint baked into its CREATE TABLE statement —
    # SQLite has no ALTER COLUMN, so that case needs the standard
    # rename-recreate-copy dance instead of a single ALTER.
    def get_user_id_nullable(sync_conn):
        inspector = inspect(sync_conn)
        if "user_ai_configs" not in inspector.get_table_names():
            return None
        for col in inspector.get_columns("user_ai_configs"):
            if col["name"] == "user_id":
                return col["nullable"]
        return None

    if engine.dialect.name == "postgresql":
        async with engine.begin() as conn:
            nullable = await conn.run_sync(get_user_id_nullable)
            if nullable is False:
                try:
                    await conn.execute(
                        text("ALTER TABLE user_ai_configs ALTER COLUMN user_id DROP NOT NULL")
                    )
                    logger.info("✅ Relaxed user_ai_configs.user_id to nullable")
                except Exception as e:
                    logger.warning(f"Could not relax user_ai_configs.user_id: {e}")

    elif engine.dialect.name == "sqlite":
        async with engine.begin() as conn:
            def get_state(sync_conn):
                inspector = inspect(sync_conn)
                tables = inspector.get_table_names()
                nullable = None
                if "user_ai_configs" in tables:
                    for col in inspector.get_columns("user_ai_configs"):
                        if col["name"] == "user_id":
                            nullable = col["nullable"]
                return nullable, "user_ai_configs__pre_nullable" in tables

            nullable, has_interrupted_leftover = await conn.run_sync(get_state)
            table = Base.metadata.tables["user_ai_configs"]
            column_list = ", ".join(table.columns.keys())

            # aiosqlite/SQLite don't roll back DDL on an exception the way
            # Postgres would — a crash between the RENAME below and the
            # final DROP TABLE can leave both user_ai_configs (new, already
            # nullable) and user_ai_configs__pre_nullable (old, with any
            # rows that hadn't been copied yet) sitting side by side. Finish
            # that copy on the next startup instead of colliding with the
            # already-renamed table by trying the migration again.
            if has_interrupted_leftover and nullable is not False:
                try:
                    await conn.execute(
                        text(
                            f"INSERT INTO user_ai_configs ({column_list}) "
                            f"SELECT {column_list} FROM user_ai_configs__pre_nullable"
                        )
                    )
                    await conn.execute(text("DROP TABLE user_ai_configs__pre_nullable"))
                    logger.info("✅ Recovered leftover rows from an interrupted user_ai_configs migration")
                except Exception as e:
                    logger.warning(f"Could not recover user_ai_configs__pre_nullable leftovers: {e}")

            elif nullable is False:
                try:
                    # SQLite index names are unique per-database, not per-
                    # table — renaming the table does NOT rename its
                    # indexes, so they'd collide with the ones table.create()
                    # is about to emit for the rebuilt table below. Drop
                    # them first (idempotent either way).
                    for index in all_indexes.get("user_ai_configs", []):
                        await conn.execute(text(f"DROP INDEX IF EXISTS {index.name}"))

                    await conn.execute(
                        text("ALTER TABLE user_ai_configs RENAME TO user_ai_configs__pre_nullable")
                    )
                    await conn.run_sync(lambda sync_conn: table.create(sync_conn))
                    await conn.execute(
                        text(
                            f"INSERT INTO user_ai_configs ({column_list}) "
                            f"SELECT {column_list} FROM user_ai_configs__pre_nullable"
                        )
                    )
                    await conn.execute(text("DROP TABLE user_ai_configs__pre_nullable"))
                    logger.info("✅ Relaxed user_ai_configs.user_id to nullable (SQLite table rebuild)")
                except Exception as e:
                    logger.warning(
                        f"Could not relax user_ai_configs.user_id: {e} — will retry on next startup "
                        "(check for a leftover user_ai_configs__pre_nullable table if this recurs)."
                    )


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

    # ── AI model bag — seed platform defaults, backfill legacy priorities ──
    # Both are one-time, additive, and non-fatal: a failure here shouldn't
    # crash startup, just leave the bag to be configured manually.
    try:
        from app.ai.orchestrator import seed_default_ai_configs, backfill_legacy_bag_orders
        await seed_default_ai_configs()
        await backfill_legacy_bag_orders()
    except Exception as e:
        logger.warning(f"⚠️  AI model bag seeding/backfill failed: {e}")

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
        allow_origins=["*"],
        allow_credentials=False if settings.ENVIRONMENT == "development" else True,
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

    # ── Validation error normalization ──
    # FastAPI's default 422 body is {"detail": [{"loc":..., "msg":...}, ...]}
    # — an array under "detail", not a string. Frontend interceptors (e.g.
    # apps/desktop/src/lib/api.ts) only special-case {"detail": "<string>"}
    # (HTTPException) or {"success", "message", "errors"} (this handler);
    # without this, real validation errors (e.g. a field over its max_length)
    # fell through to a generic "something went wrong" toast that hid the
    # actual problem from the user.
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = [
            {
                "field": ".".join(str(p) for p in err["loc"] if p != "body"),
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        first = errors[0] if errors else {"field": "", "message": "Invalid request."}
        message = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
        return JSONResponse(
            status_code=422,
            content={"success": False, "message": message, "errors": errors},
        )

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
