"""User-management endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentSuperuser, CurrentUser, UserServiceDep
from app.schemas.common import Page, PaginationParams
from app.schemas.user import UserRead, UserUpdate

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserRead, summary="Current authenticated user")
async def read_me(current: CurrentUser) -> UserRead:
    return UserRead.model_validate(current)


@router.patch("/me", response_model=UserRead, summary="Update current user")
async def update_me(
    payload: UserUpdate,
    current: CurrentUser,
    users: UserServiceDep,
) -> UserRead:
    updated = await users.update(current.id, payload)
    return UserRead.model_validate(updated)


@router.get("", response_model=Page[UserRead], summary="List users (superuser only)")
async def list_users(
    _: CurrentSuperuser,
    users: UserServiceDep,
    pagination: Annotated[PaginationParams, Depends()],
) -> Page[UserRead]:
    items, total = await users.list_(limit=pagination.limit, offset=pagination.offset)
    return Page(
        items=[UserRead.model_validate(u) for u in items],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{user_id}", response_model=UserRead, summary="Get user by id (superuser only)")
async def get_user(
    user_id: uuid.UUID,
    _: CurrentSuperuser,
    users: UserServiceDep,
) -> UserRead:
    user = await users.get(user_id)
    return UserRead.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user (superuser only)",
)
async def delete_user(
    user_id: uuid.UUID,
    _: CurrentSuperuser,
    users: UserServiceDep,
) -> None:
    await users.delete(user_id)
