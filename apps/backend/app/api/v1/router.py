# ═══════════════════════════════════════════════════════════════
#  VengaiCode — API v1 Router
#  api/v1/router.py — Aggregates all v1 endpoint routers
#  Mounted in main.py under settings.API_V1_PREFIX (/api/v1)
# ═══════════════════════════════════════════════════════════════

from fastapi import APIRouter

from app.api.v1 import auth, projects

# ───────────────────────────────────────────────
#  Main v1 Router
# ───────────────────────────────────────────────
api_router = APIRouter()

# ── Authentication ──
# /api/v1/auth/signup, /login, /send-otp, /verify-otp, etc.
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"],
)

# ── Projects ──
# /api/v1/projects, /api/v1/projects/{id}
api_router.include_router(
    projects.router,
    prefix="/projects",
    tags=["Projects"],
)

# ── AI Engine ──
# /api/v1/ai/status, /api/v1/ai/ask
from app.api.v1 import ai
api_router.include_router(
    ai.router,
    prefix="/ai",
    tags=["AI Engine"],
)

# ───────────────────────────────────────────────
#  Future routers — uncomment as each module is built
#  Each module follows the same pattern as auth/projects above
# ───────────────────────────────────────────────

# from app.api.v1 import ai
# api_router.include_router(
#     ai.router,
#     prefix="/ai",
#     tags=["AI Engine"],
# )

# from app.api.v1 import licences
# api_router.include_router(
#     licences.router,
#     prefix="/licences",
#     tags=["Licences"],
# )

# from app.api.v1 import marketplace
# api_router.include_router(
#     marketplace.router,
#     prefix="/marketplace",
#     tags=["Marketplace"],
# )

# from app.api.v1 import payments
# api_router.include_router(
#     payments.router,
#     prefix="/payments",
#     tags=["Payments"],
# )

# from app.api.v1 import notifications
# api_router.include_router(
#     notifications.router,
#     prefix="/notifications",
#     tags=["Notifications"],
# )

# from app.api.v1 import users
# api_router.include_router(
#     users.router,
#     prefix="/users",
#     tags=["Users"],
# )

# from app.api.v1 import templates
# api_router.include_router(
#     templates.router,
#     prefix="/templates",
#     tags=["Community Templates"],
# )

# from app.api.v1 import admin
# api_router.include_router(
#     admin.router,
#     prefix="/admin",
#     tags=["Admin"],
# )

# from app.api.v1 import webhooks
# api_router.include_router(
#     webhooks.router,
#     prefix="/webhooks",
#     tags=["Webhooks"],
# )

# ── Wizard ──
from app.api.v1 import wizard
api_router.include_router(
    wizard.router,
    prefix="/wizard",
    tags=["Wizard"],
)

# ── Requirements ──
from app.api.v1 import requirements
api_router.include_router(
    requirements.router,
    prefix="/requirements",
    tags=["Requirements"],
)

# ── UI/UX ──
from app.api.v1 import uiux
api_router.include_router(
    uiux.router,
    prefix="/uiux",
    tags=["UI/UX Design"],
)

# ── Notifications ──
from app.api.v1 import notifications
api_router.include_router(
    notifications.router,
    prefix="/notifications",
    tags=["Notifications"],
)

# ── Architecture ──
from app.api.v1 import architecture
api_router.include_router(
    architecture.router,
    prefix="/architecture",
    tags=["Architecture"],
)

# ── Code Generation ──
from app.api.v1 import codegen
api_router.include_router(
    codegen.router,
    prefix="/codegen",
    tags=["Code Generation"],
)

# ── Export ──
from app.api.v1 import export
api_router.include_router(
    export.router,
    prefix="/export",
    tags=["Export"],
)

# ── Testing ──
from app.api.v1 import testing
api_router.include_router(
    testing.router,
    prefix="/testing",
    tags=["Testing"],
)

# ── Packaging (Windows installer builds) ──
from app.api.v1 import packaging
api_router.include_router(
    packaging.router,
    prefix="/packaging",
    tags=["Packaging"],
)
