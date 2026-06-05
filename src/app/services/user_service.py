"""User business logic.

Services orchestrate repositories and own transaction boundaries (via
:class:`UnitOfWork`). Argon2 hashing is CPU-bound, so it's offloaded to the
shared CPU executor via :func:`run_cpu_bound` — under load this prevents the
event loop from stalling while many concurrent registrations all try to
hash passwords on the main thread.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.core.concurrency import ConcurrencyLimits, run_cpu_bound
from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import PasswordHasher
from app.db.models.user import User
from app.db.session import Database, UnitOfWork
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate

_logger = get_logger(__name__)


class UserService:
    def __init__(
        self,
        db: Database,
        limits: ConcurrencyLimits,
        repo: UserRepository,
        hasher: PasswordHasher,
    ) -> None:
        self._db = db
        self._limits = limits
        self._repo = repo
        self._hasher = hasher

    # ------------------------------------------------------------------ reads
    async def get(self, user_id: uuid.UUID) -> User:
        async with self._db.session() as session:
            user = await self._repo.get(session, user_id)
        if user is None:
            raise NotFoundError(f"user {user_id} not found")
        return user

    async def list_(
        self,
        *,
        limit: int,
        offset: int,
        is_active: bool | None = None,
    ) -> tuple[Sequence[User], int]:
        async with self._db.session() as session:
            return await self._repo.list_(
                session,
                limit=limit,
                offset=offset,
                is_active=is_active,
            )

    # ---------------------------------------------------------------- writes
    async def register(self, payload: UserCreate) -> User:
        """Create a new user. Hashes the password off-loop."""
        # Hash before opening the txn so we don't hold a DB connection while
        # the CPU executor chews on argon2 (~50ms).
        hashed = await run_cpu_bound(
            self._limits,
            self._hasher.hash,
            payload.password.get_secret_value(),
        )
        email = payload.email.lower()

        async with UnitOfWork(self._db) as uow:
            existing = await self._repo.get_by_email(uow.session, email)
            if existing is not None:
                raise ConflictError("a user with that email already exists")
            user = await self._repo.add(
                uow.session,
                User.new(
                    email=email,
                    hashed_password=hashed,
                    full_name=payload.full_name,
                ),
            )
            _logger.info("user_registered", user_id=str(user.id), email=email)
            return user

    async def update(self, user_id: uuid.UUID, payload: UserUpdate) -> User:
        async with UnitOfWork(self._db) as uow:
            user = await self._repo.get(uow.session, user_id)
            if user is None:
                raise NotFoundError(f"user {user_id} not found")
            data = payload.model_dump(exclude_unset=True)
            for field, value in data.items():
                setattr(user, field, value)
            await uow.flush()
            return user

    async def delete(self, user_id: uuid.UUID) -> None:
        async with UnitOfWork(self._db) as uow:
            user = await self._repo.get(uow.session, user_id)
            if user is None:
                raise NotFoundError(f"user {user_id} not found")
            await self._repo.delete(uow.session, user)

    # ----------------------------------------------------------------- auth
    async def authenticate(self, email: str, password: str) -> User:
        async with self._db.session() as session:
            user = await self._repo.get_by_email(session, email.lower())

        # Always run verify, even on miss, to neutralise user-enumeration timing.
        candidate_hash = user.hashed_password if user else _DUMMY_HASH
        is_valid = await run_cpu_bound(
            self._limits,
            self._hasher.verify,
            candidate_hash,
            password,
        )
        if user is None or not is_valid or not user.is_active:
            raise UnauthorizedError("invalid credentials")

        if self._hasher.needs_rehash(user.hashed_password):
            new_hash = await run_cpu_bound(self._limits, self._hasher.hash, password)
            async with UnitOfWork(self._db) as uow:
                refreshed = await self._repo.get(uow.session, user.id)
                if refreshed is not None:
                    refreshed.hashed_password = new_hash
                    await uow.flush()
        return user


# Pre-computed dummy hash for timing-attack defence on email lookup misses.
# Cost: one verify per failed lookup, paid in the CPU pool, not the loop.
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "ZmFrZXNhbHRmYWtlc2FsdA$"
    "iJ1jM3GxQ4xJj7Z2cJqfqgKQwYJzJk4mC6HhYxQ8w0c"
)


__all__ = ["UserService"]
