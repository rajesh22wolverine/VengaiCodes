# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Logging Middleware
#  middleware/logging_middleware.py — Logs every request/response
# ═══════════════════════════════════════════════════════════════

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("vengaicode.requests")


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs method, path, status code, and duration for every request.
    Attaches a unique X-Request-ID header for tracing.
    Skips noisy health-check endpoints at DEBUG-only verbosity.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id

        log_fn = logger.debug if request.url.path in ("/health",) else logger.info
        log_fn(
            f"[{request_id}] {request.method} {request.url.path} "
            f"-> {response.status_code} ({duration_ms:.1f}ms)"
        )

        return response
