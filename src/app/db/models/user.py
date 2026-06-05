"""User ORM model."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk


class User(Base, TimestampMixin):
    """Application user."""

    __tablename__ = "users"

    id: Mapped[uuid_pk]
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<User id={self.id} email={self.email!r}>"

    @classmethod
    def new(
        cls,
        *,
        email: str,
        hashed_password: str,
        full_name: str | None = None,
        is_superuser: bool = False,
    ) -> User:
        """Factory — keeps the dataclass init signature out of caller code."""
        return cls(
            id=uuid.uuid4(),
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            is_active=True,
            is_superuser=is_superuser,
        )
