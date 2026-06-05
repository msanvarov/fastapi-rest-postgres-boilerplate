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

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("SECRET_KEY", "test-secret-must-be-at-least-32-characters-long-ok")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_DB", "app_test")

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def app_instance():
    """Fresh app per test; lifespan runs via the ASGI transport."""
    return create_app()


@pytest.fixture
async def client(app_instance) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app_instance),
        base_url="http://test",
    ) as ac:
        # Trigger lifespan by hitting the live endpoint (HTTPX runs it on first req).
        yield ac


@pytest.fixture
async def db(settings) -> AsyncIterator[Database]:
    from app.core.concurrency import ConcurrencyLimits

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
