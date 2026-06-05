"""Per-request timeout middleware.

Wraps every request in :func:`asyncio.timeout`. A hung downstream or runaway
query is converted to a 504 instead of holding a worker indefinitely.

The timeout cooperates with the bounded concurrency semaphores: if a request
is cancelled here, any ``async with semaphore`` it owns is correctly released.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from http import HTTPStatus

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.core.logging import get_logger
from app.schemas.common import ErrorResponse

_logger = get_logger(__name__)


class TimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, timeout_seconds: float) -> None:
        super().__init__(app)
        self._timeout = timeout_seconds

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            async with asyncio.timeout(self._timeout):
                return await call_next(request)
        except TimeoutError:
            _logger.warning("request_timeout", timeout_s=self._timeout)
            return JSONResponse(
                ErrorResponse(
                    code="request_timeout",
                    message=f"Request exceeded {self._timeout}s timeout.",
                ).model_dump(),
                status_code=HTTPStatus.GATEWAY_TIMEOUT,
            )


__all__ = ["TimeoutMiddleware"]
