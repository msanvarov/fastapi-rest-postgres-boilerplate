"""User ORM model."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """Application user."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # ``id`` is excluded from __init__ so the dataclass field-ordering rule
    # (non-default before default) doesn't force every required column to the
    # bottom. SQLAlchemy still populates it on insert via default_factory.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid.uuid4,
        init=False,
        sort_order=-100,
    )

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
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            is_active=True,
            is_superuser=is_superuser,
        )
