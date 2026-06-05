"""End-to-end liveness check — confirms the app boots and serves a request."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_liveness(client):
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


async def test_request_id_header_is_returned(client):
    response = await client.get("/api/v1/health/live")
    assert response.headers.get("X-Request-ID")


async def test_request_id_header_is_preserved(client):
    response = await client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "test-correlation-id-1234"},
    )
    assert response.headers["X-Request-ID"] == "test-correlation-id-1234"
