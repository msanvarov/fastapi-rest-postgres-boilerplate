"""Smoke endpoint must answer on both the prefixed and unprefixed paths."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("path", ["/ping", "/api/v1/ping"])
async def test_ping_returns_pong(client, path):
    response = await client.get(path)
    assert response.status_code == 200
    assert response.json() == {"ping": "pong"}


async def test_ping_has_request_id_header(client):
    response = await client.get("/ping")
    assert response.headers.get("X-Request-ID")


async def test_ping_is_fast(client):
    """Sanity check: cold endpoint stays well under our request-timeout budget."""
    import time

    start = time.perf_counter()
    response = await client.get("/ping")
    elapsed = time.perf_counter() - start

    assert response.status_code == 200
    # Generous bound — flaky CI runners still finish in <500ms.
    assert elapsed < 0.5
