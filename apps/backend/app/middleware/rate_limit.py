# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Rate Limit Middleware
#  middleware/rate_limit.py — IP-based rate limiting via Redis
# ═══════════════════════════════════════════════════════════════

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.redis import rate_limit_check


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple sliding-window rate limiter, keyed by client IP.

    Skips /health endpoints so uptime monitors/Docker healthchecks
    are never blocked.
    """

    def __init__(self, app, calls: int = 100, period: int = 60):
        super().__init__(app)
        self.calls = calls
        self.period = period

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path.startswith("/health"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        identifier = f"{client_ip}:{request.url.path}"

        allowed, remaining = await rate_limit_check(identifier, self.calls, self.period)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "message": (
                        "Too many requests. Baby Tiger needs a quick breather! "
                        "Please slow down a little 🐯"
                    ),
                },
                headers={"Retry-After": str(self.period)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
