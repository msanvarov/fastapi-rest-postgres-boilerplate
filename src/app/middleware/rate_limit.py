"""Sliding-window rate limiter backed by Redis.

Algorithm: ZSET per client key, scored by request timestamp.

* Append timestamp.
* Drop entries older than the window.
* Count remaining entries.

All four ops are issued in a single ``MULTI/EXEC`` pipeline → one RTT per
request. The pipeline is *atomic* per client; concurrent requests for the
same key are serialised by Redis.

For low-volume APIs an in-process :class:`asyncio.Semaphore` would be enough,
but per-worker limits don't help when you scale horizontally. Redis gives us a
shared view across replicas.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from http import HTTPStatus

import redis.asyncio as redis
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.core.logging import get_logger
from app.schemas.common import ErrorResponse

_logger = get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter — denies once a client crosses ``per_minute``."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        redis_client: redis.Redis,
        per_minute: int,
        window_seconds: int = 60,
        key_prefix: str = "ratelimit",
    ) -> None:
        super().__init__(app)
        self._redis = redis_client
        self._limit = per_minute
        self._window = window_seconds
        self._prefix = key_prefix

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        client = _client_identity(request)
        key = f"{self._prefix}:{client}"
        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - self._window * 1000

        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, window_start_ms)
                pipe.zadd(key, {f"{now_ms}-{id(request)}": now_ms})
                pipe.zcard(key)
                pipe.expire(key, self._window)
                _, _, count, _ = await pipe.execute()
        except redis.RedisError:
            # Fail-open: if Redis is down, don't take the API down with it.
            _logger.warning("ratelimit_redis_unavailable", client=client)
            return await call_next(request)

        if count > self._limit:
            return JSONResponse(
                ErrorResponse(
                    code="rate_limited",
                    message=f"Rate limit exceeded ({self._limit}/{self._window}s).",
                ).model_dump(),
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
                headers={"Retry-After": str(self._window)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self._limit - int(count)))
        return response


def _client_identity(request: Request) -> str:
    """Prefer authenticated subject, fall back to forwarded IP, then peer IP."""
    auth_user = getattr(request.state, "user_id", None)
    if auth_user:
        return f"user:{auth_user}"

    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # Trust only the left-most hop; the proxy is expected to have stripped
        # any client-supplied header before adding its own.
        return f"ip:{fwd.split(',')[0].strip()}"

    return f"ip:{request.client.host}" if request.client else "ip:unknown"


__all__ = ["RateLimitMiddleware"]
