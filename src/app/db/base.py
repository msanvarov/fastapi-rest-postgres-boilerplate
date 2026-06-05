"""Declarative base + shared column mixins.

SQLAlchemy 2.0 typed declarative style. The :class:`Base` uses
:class:`MappedAsDataclass` so every model behaves like a Python dataclass
(``__init__``, ``__repr__``, ``__eq__``) while still being a proper ORM mapped
class. This keeps construction explicit and avoids the ``**kwargs`` foot-gun.

All timestamps are timezone-aware UTC. The DB column defaults use
``func.now()`` (server-side) so writes from any client land consistently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column

# Consistent constraint naming → cleaner Alembic diffs, fewer migration foot-guns.
_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_`%(constraint_name)s`",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(MappedAsDataclass, DeclarativeBase):
    """Declarative base — all ORM models inherit from this."""

    metadata = MetaData(naming_convention=_NAMING_CONVENTION)


# Reusable column types ------------------------------------------------------
uuid_pk = Annotated[
    uuid.UUID,
    mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid.uuid4,
        sort_order=-100,
    ),
]

created_at = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        sort_order=100,
        init=False,
    ),
]

updated_at = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        sort_order=101,
        init=False,
    ),
]


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns."""

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]
