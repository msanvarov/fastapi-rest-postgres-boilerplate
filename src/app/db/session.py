"""Async engine + session factory + Unit-of-Work.

Two layers:

* **Engine / sessionmaker** — built once at startup, torn down at shutdown.
  Pool sizing comes from settings; asyncpg uses its own implicit prepared-
  statement cache so we disable SQLAlchemy's cache to avoid double-caching
  bugs with PgBouncer in *transaction* pool mode.

* **UnitOfWork** — explicit transaction scope. Repositories take a *session*
  (not a sessionmaker), so transaction boundaries are decided by the service
  that owns the use-case, not by the data layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.concurrency import ConcurrencyLimits
from app.core.config import Settings
from app.core.logging import get_logger

_logger = get_logger(__name__)


class Database:
    """Owns the async engine + sessionmaker for one process.

    Held on ``app.state.db``; pass into dependencies rather than reaching
    for module-level globals (makes test overrides trivial).
    """

    def __init__(self, settings: Settings, limits: ConcurrencyLimits) -> None:
        self._settings = settings
        self._limits = limits
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            msg = "Database not initialised; call connect() first"
            raise RuntimeError(msg)
        return self._engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            msg = "Database not initialised; call connect() first"
            raise RuntimeError(msg)
        return self._sessionmaker

    async def connect(self) -> Self:
        if self._engine is not None:
            return self

        s = self._settings
        self._engine = create_async_engine(
            str(s.database_url),
            echo=s.postgres_echo,
            pool_size=s.postgres_pool_size,
            max_overflow=s.postgres_max_overflow,
            pool_timeout=s.postgres_pool_timeout,
            pool_recycle=s.postgres_pool_recycle,
            pool_pre_ping=True,
            # asyncpg has its own LRU; SA's statement cache fights pgbouncer.
            connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
        )
        self._sessionmaker = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
            autoflush=False,
            class_=AsyncSession,
        )
        _logger.info(
            "database_connected",
            host=s.postgres_host,
            db=s.postgres_db,
            pool_size=s.postgres_pool_size,
        )
        return self

    async def disconnect(self) -> None:
        if self._engine is None:
            return
        await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None
        _logger.info("database_disconnected")

    async def healthcheck(self) -> bool:
        """Lightweight ``SELECT 1`` — used by ``/health/ready``."""
        from sqlalchemy import text  # local to avoid import at module load

        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            _logger.warning("database_healthcheck_failed", error=str(exc))
            return False
        else:
            return True

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session bounded by the DB semaphore — no implicit transaction.

        Use for read-only or single-statement work. For multi-statement
        transactions, use :class:`UnitOfWork`.
        """
        async with self._limits.db, self.sessionmaker() as session:
            yield session


class UnitOfWork:
    """Transactional scope around a single :class:`AsyncSession`.

    Acquired via ``async with UnitOfWork(db) as uow:``. Commits on clean exit,
    rolls back on exception, and always returns the session to the pool.

    Pattern:

        async with UnitOfWork(db) as uow:
            user = await user_repo.add(uow.session, ...)
            await audit_repo.record(uow.session, ...)
        # commit happens here on success
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._session: AsyncSession | None = None
        self._sem_ctx = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            msg = "UnitOfWork is not active; use 'async with'"
            raise RuntimeError(msg)
        return self._session

    async def __aenter__(self) -> Self:
        self._sem_ctx = self._db._limits.db  # noqa: SLF001 — intentional close-coupling
        await self._sem_ctx.acquire()
        self._session = self._db.sessionmaker()
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        assert self._session is not None  # narrow for type-checker
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None
            if self._sem_ctx is not None:
                self._sem_ctx.release()
                self._sem_ctx = None

    async def flush(self) -> None:
        await self.session.flush()


__all__ = ["Database", "UnitOfWork"]
