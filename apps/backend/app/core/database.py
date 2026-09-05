# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Database Core
#  core/database.py — SQLAlchemy async engine, session, base
# ═══════════════════════════════════════════════════════════════

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine
)
from sqlalchemy.orm import declarative_base

from app.config import settings

# ───────────────────────────────────────────────
#  Declarative Base — all models inherit from this
# ───────────────────────────────────────────────
Base = declarative_base()

# ───────────────────────────────────────────────
#  Async Engine
#  SQLite (local dev) doesn't support connection pool settings
#  that Postgres/MySQL use, so we branch on the URL scheme.
# ───────────────────────────────────────────────
_is_sqlite = settings.database_url_async.startswith("sqlite")

# Supabase (and any pgbouncer in transaction mode) multiplexes one server
# connection across many clients, so a prepared statement created on one
# request may not exist on the next — asyncpg caches them by default and
# fails with "prepared statement __asyncpg_stmt_N__ does not exist" under
# concurrency. It works fine in light testing and breaks once two requests
# overlap, so it has to be switched off up front rather than debugged later.
#
# Only the POOLER endpoints need this. Supabase's direct connection
# (db.<ref>.supabase.co:5432) keeps prepared statements, which are faster,
# so the cache is disabled only where it's actually unsafe.
_url = settings.database_url_async
_is_pooled = ":6543" in _url or "pooler.supabase.com" in _url

if _is_sqlite:
    engine = create_async_engine(
        settings.database_url_async,
        echo=settings.DATABASE_ECHO,
    )
else:
    _connect_args: dict = {"ssl": "require"}
    if _is_pooled:
        _connect_args["statement_cache_size"] = 0

    engine = create_async_engine(
        settings.database_url_async,
        echo=settings.DATABASE_ECHO,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT,
        pool_pre_ping=True,
        connect_args=_connect_args,
    )

# ───────────────────────────────────────────────
#  Session Factory
# ───────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ───────────────────────────────────────────────
#  Dependency — get_db
#  Use in route handlers: db: AsyncSession = Depends(get_db)
# ───────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()