"""Persistence layer for :class:`User`.

Repositories take an :class:`AsyncSession` per call rather than holding one as
state. This makes transaction scope a *caller* decision, which is what we want:
a service composing several repo calls inside a single ``UnitOfWork`` will get
atomicity for free, and a read-only handler can pass a sessionmaker session
without ceremony.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User


class UserRepository:
    """Data-access for users. Pure SQL — no business rules live here."""

    async def get(self, session: AsyncSession, user_id: uuid.UUID) -> User | None:
        return await session.get(User, user_id)

    async def get_by_email(self, session: AsyncSession, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_(
        self,
        session: AsyncSession,
        *,
        limit: int,
        offset: int,
        is_active: bool | None = None,
    ) -> tuple[Sequence[User], int]:
        base = select(User)
        if is_active is not None:
            base = base.where(User.is_active.is_(is_active))

        total = (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()

        result = await session.execute(
            base.order_by(User.created_at.desc()).limit(limit).offset(offset),
        )
        return result.scalars().all(), total

    async def add(self, session: AsyncSession, user: User) -> User:
        session.add(user)
        await session.flush()
        return user

    async def delete(self, session: AsyncSession, user: User) -> None:
        await session.delete(user)
        await session.flush()


__all__ = ["UserRepository"]
