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
