# ═══════════════════════════════════════════════════════════════
#  VengaiCode — FastAPI Backend Entry Point
#  Vengai (வேங்கை) = Tiger in Tamil 🐯
#  main.py — App factory, middleware, startup, shutdown
# ═══════════════════════════════════════════════════════════════

import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.config import settings
from app.api.v1.router import api_router
from app.core.database import engine, Base, get_db
from app.core.redis import redis_client
from app.core.security import verify_server_health
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

# ───────────────────────────────────────────────
#  Logging Setup
# ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("vengaicode")

# ───────────────────────────────────────────────
#  Sentry Error Tracking Setup
# ───────────────────────────────────────────────
if settings.SENTRY_DSN and settings.ENVIRONMENT == "production":
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        send_default_pii=False,  # Privacy first — no PII sent to Sentry
    )
    logger.info("✅ Sentry error tracking initialized")


# ───────────────────────────────────────────────
#  App Lifespan — Startup & Shutdown
# ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──
    logger.info("🐯 VengaiCode Backend Starting...")
    logger.info(f"   Environment: {settings.ENVIRONMENT}")
    logger.info(f"   Debug mode:  {settings.DEBUG}")
    logger.info(f"   App version: {settings.APP_VERSION}")

    # Create all database tables
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda conn: Base.metadata.create_all(conn, checkfirst=True))
        logger.info("✅ Database tables created/verified")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

    # Connect to Redis
    try:
        await redis_client.ping()
        logger.info("✅ Redis connection established")
    except Exception as e:
        logger.warning(f"⚠️  Redis connection failed: {e} — caching disabled")

    # Verify Ollama is available
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.OLLAMA_HOST}/api/tags",
                timeout=5.0
            )
            if response.status_code == 200:
                models = response.json().get("models", [])
                logger.info(f"✅ Ollama connected — {len(models)} models available")
            else:
                logger.warning("⚠️  Ollama responded but no models loaded")
    except Exception as e:
        logger.warning(f"⚠️  Ollama not available: {e} — will use Groq fallback")

    logger.info("🐯 VengaiCode Backend Ready! வேங்கை கோட் வாழ்க!")

    yield  # App is running

    # ── SHUTDOWN ──
    logger.info("🐯 VengaiCode Backend Shutting down...")
    try:
        await redis_client.close()
        logger.info("✅ Redis connection closed")
    except Exception:
        pass
    logger.info("👋 VengaiCode Backend stopped. Bye from Baby Tiger!")


# ───────────────────────────────────────────────
#  FastAPI App Factory
# ───────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title="VengaiCode API",
        description="""
## VengaiCode Backend API 🐯

**Vengai (வேங்கை) = Tiger in Tamil**

VengaiCode is a desktop application powered 100% by open-source AI
that lets anyone build any type of application by describing their idea
in plain English.

### Key Features:
- 🤖 **AI-powered** — Ollama (local) + Groq (cloud fallback)
- 🔐 **Dual licence system** — Master + Seller licence
- 💰 **Commission engine** — 10% marketplace / 25% external
- 🏪 **Marketplace** — buy and sell built applications
- 🐯 **Baby Tiger stamp** — mandatory on all built apps
        """,
        version=settings.APP_VERSION,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # ── Middleware (order matters — outermost runs first) ──

    # GZip compression for large responses
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # CORS — allow desktop app and marketplace
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time"],
    )

    # Request logging
    app.add_middleware(LoggingMiddleware)

    # Rate limiting
    app.add_middleware(
        RateLimitMiddleware,
        calls=settings.RATE_LIMIT_CALLS,
        period=settings.RATE_LIMIT_PERIOD,
    )

    # ── Exception Handlers ──

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        """Return friendly validation error messages."""
        errors = []
        for error in exc.errors():
            field = " → ".join(str(loc) for loc in error["loc"] if loc != "body")
            message = error["msg"].replace("Value error, ", "")
            errors.append({"field": field, "message": message})

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "message": "Validation failed — please check your input",
                "errors": errors,
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Catch-all exception handler — never expose internals."""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": "Something went wrong. Baby Tiger is investigating! 🐯🔍",
                "error_id": str(time.time()),
            },
        )

    # ── Request Timing Middleware ──
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        start_time = time.perf_counter()
        response = await call_next(request)
        process_time = (time.perf_counter() - start_time) * 1000
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
        return response

    # ── Include API Routers ──
    app.include_router(
        api_router,
        prefix=settings.API_V1_PREFIX,
    )

    # ── Health Check Endpoints ──

    @app.get("/health", tags=["Health"], summary="Health check")
    async def health_check():
        """Quick health check — used by Docker, load balancers, Uptime Robot."""
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "message": "Baby Tiger is alive and coding! 🐯",
        }

    @app.get("/health/detailed", tags=["Health"], summary="Detailed health check")
    async def detailed_health_check():
        """Detailed health — checks all dependencies."""
        health = {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "services": {},
        }

        # Check Redis
        try:
            await redis_client.ping()
            health["services"]["redis"] = "healthy"
        except Exception:
            health["services"]["redis"] = "unhealthy"
            health["status"] = "degraded"

        # Check Ollama
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{settings.OLLAMA_HOST}/api/tags",
                    timeout=3.0
                )
                health["services"]["ollama"] = (
                    "healthy" if resp.status_code == 200 else "unhealthy"
                )
        except Exception:
            health["services"]["ollama"] = "unavailable"

        # Check Groq (just validate key exists)
        health["services"]["groq"] = (
            "configured" if settings.GROQ_API_KEY else "not_configured"
        )

        return health

    @app.get("/", tags=["Root"], summary="API root")
    async def root():
        """API root — returns basic info."""
        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "description": "Build any app in 30 minutes. Zero coding. 100% open-source.",
            "mascot": "Baby Tiger 🐯 — Vengai (வேங்கை) = Tiger in Tamil",
            "docs": "/docs" if settings.DEBUG else "Disabled in production",
        }

    return app


# ───────────────────────────────────────────────
#  Create App Instance
# ───────────────────────────────────────────────
app = create_app()
