"""Shared pytest fixtures.

The strategy:

* **Unit tests** never touch a real DB. They mock at the repository boundary
  and/or use the service directly.
* **Integration tests** spin the full ASGI app (via :class:`AsyncClient` with
  :class:`ASGITransport`) and talk to a real Postgres provided either by
  ``docker compose`` locally or the CI service container.

Each test gets its own DB schema reset via ``Base.metadata.create_all`` /
``drop_all`` on a session-scoped engine. For larger suites, swap this for the
SAVEPOINT-rollback pattern.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

# Env must be primed before any ``app.*`` import — Settings reads it eagerly.
os.environ.setdefault("SECRET_KEY", "test-secret-must-be-at-least-32-characters-long-ok")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_DB", "app_test")
# Disable the redis-backed rate limiter in tests — we don't want to depend on a
# live redis just to exercise the request path. The middleware is exercised by
# its own dedicated tests.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.concurrency import ConcurrencyLimits
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import Database
from app.main import create_app


@pytest.fixture(scope="session")
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def app_instance() -> FastAPI:
    """Fresh app per test; lifespan is driven by :class:`LifespanManager`."""
    return create_app()


@pytest.fixture
async def client(app_instance: FastAPI) -> AsyncIterator[AsyncClient]:
    # LifespanManager runs the lifespan context the same way uvicorn would —
    # without it, ASGITransport never fires startup and app.state is empty.
    async with (
        LifespanManager(app_instance),
        AsyncClient(
            transport=ASGITransport(app=app_instance),
            base_url="http://test",
        ) as ac,
    ):
        yield ac


@pytest.fixture
async def db(settings) -> AsyncIterator[Database]:
    limits = ConcurrencyLimits.create()
    instance = await Database(settings, limits).connect()
    async with instance.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield instance
    finally:
        await instance.disconnect()
        await limits.aclose()
