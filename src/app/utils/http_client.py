"""Shared outbound HTTP client.

A single :class:`httpx.AsyncClient` per process — connection pooling, HTTP/2
re-use, DNS caching. Calls are guarded by the HTTP semaphore so a burst of
outbound traffic doesn't melt a downstream or exhaust local file descriptors.
Retries with exponential back-off + jitter via tenacity for idempotent verbs.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.concurrency import ConcurrencyLimits
from app.core.logging import get_logger

_logger = get_logger(__name__)

_IDEMPOTENT = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


class HttpClient:
    """Thin wrapper around httpx.AsyncClient — pool + semaphore + retries."""

    def __init__(
        self,
        limits: ConcurrencyLimits,
        *,
        timeout: float = 10.0,
        max_keepalive_connections: int = 20,
        max_connections: int = 100,
    ) -> None:
        self._limits = limits
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(
                max_keepalive_connections=max_keepalive_connections,
                max_connections=max_connections,
            ),
            http2=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        url: str,
        *,
        retries: int = 3,
        **kwargs: Any,
    ) -> httpx.Response:
        @retry(
            stop=stop_after_attempt(retries if method.upper() in _IDEMPOTENT else 1),
            wait=wait_exponential_jitter(initial=0.1, max=2.0),
            retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
            reraise=True,
        )
        async def _do() -> httpx.Response:
            async with self._limits.http:
                response = await self._client.request(method, url, **kwargs)
            return response

        return await _do()

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)


__all__ = ["HttpClient"]
