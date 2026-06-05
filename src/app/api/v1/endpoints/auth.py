"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import AuthServiceDep, UserServiceDep
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse
from app.schemas.user import UserCreate, UserRead

router = APIRouter(tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(payload: UserCreate, users: UserServiceDep) -> UserRead:
    user = await users.register(payload)
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for tokens")
async def login(payload: LoginRequest, auth: AuthServiceDep) -> TokenResponse:
    _, access, refresh, expires_in = await auth.login(
        payload.email,
        payload.password.get_secret_value(),
    )
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=expires_in)


@router.post("/refresh", response_model=TokenResponse, summary="Rotate refresh + access tokens")
async def refresh_tokens(payload: RefreshRequest, auth: AuthServiceDep) -> TokenResponse:
    access, refresh, expires_in = await auth.refresh(payload.refresh_token)
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=expires_in)
