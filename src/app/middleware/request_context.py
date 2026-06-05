"""Request-id + timing + structured access log middleware.

A single middleware does three things on one pass for performance:

1. Generates / accepts an ``X-Request-ID`` and binds it to the
   ``request_id`` context-var (and structlog contextvars), so every log line
   emitted during this request carries it automatically.
2. Times the request.
3. Emits an access log on completion with method, path, status, duration.

We also catch :class:`AppError` and unhandled exceptions and translate them
to a stable JSON envelope (the global error handler). Doing this here, in a
single middleware, lets us guarantee a request id is on every error response.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.core.exceptions import AppError
from app.core.logging import bind_contextvars, clear_contextvars, get_logger, request_id_ctx
from app.schemas.common import ErrorResponse

_logger = get_logger(__name__)

_REQUEST_ID_HEADER = "X-Request-ID"
_HEALTH_PATHS = frozenset(
    {
        "/ping",
        "/api/v1/ping",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/metrics",
    },
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request-scoped context, time the request, log once on completion."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or str(uuid.uuid4())
        token = request_id_ctx.set(request_id)
        bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        start = time.perf_counter()
        response: Response
        try:
            response = await call_next(request)
        except AppError as exc:
            response = _render_app_error(exc, request_id)
        except Exception:  # noqa: BLE001 — final safety net
            _logger.exception("unhandled_exception")
            response = JSONResponse(
                ErrorResponse(
                    code="internal_error",
                    message="An unexpected error occurred.",
                    request_id=request_id,
                ).model_dump(),
                status_code=500,
            )

        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        # Skip noisy health/metrics paths; everything else gets logged once.
        if request.url.path not in _HEALTH_PATHS:
            _logger.info(
                "http_request",
                status=response.status_code,
                duration_ms=duration_ms,
                client=request.client.host if request.client else None,
            )
        request_id_ctx.reset(token)
        clear_contextvars()

        response.headers[_REQUEST_ID_HEADER] = request_id
        return response


def _render_app_error(exc: AppError, request_id: str) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=request_id,
        ).model_dump(),
        status_code=exc.status_code,
    )


__all__ = ["RequestContextMiddleware"]
