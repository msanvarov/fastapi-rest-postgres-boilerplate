"""Shared Pydantic schemas used across endpoints."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field, NonNegativeInt, PositiveInt

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for response models that read from ORM objects."""

    model_config = {"from_attributes": True}


class PaginationParams(BaseModel):
    """Cursor-style ``limit`` + ``offset``. Keep offsets small."""

    limit: PositiveInt = Field(default=20, le=100)
    offset: NonNegativeInt = 0


class Page(BaseModel, Generic[T]):
    """Generic paginated envelope."""

    items: list[T]
    total: NonNegativeInt
    limit: PositiveInt
    offset: NonNegativeInt


class ErrorResponse(BaseModel):
    """Stable error envelope; populated by the error-handler middleware."""

    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    request_id: str | None = None
