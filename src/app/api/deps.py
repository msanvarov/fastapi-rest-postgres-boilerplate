"""FastAPI dependencies.

Dependencies are kept thin: they pull objects off ``request.app.state`` (where
the lifespan hook stored them) and assemble the per-request service graph.
This avoids module-level globals and keeps every dependency injectable in tests
via ``app.dependency_overrides``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.core.concurrency import BackgroundTaskSupervisor, ConcurrencyLimits
from app.core.config import Settings, get_settings
from app.core.security import (
    InvalidTokenError,
    TokenPayload,
    TokenType,
    decode_token,
    password_hasher,
)
from app.db.models.user import User
from app.db.session import Database
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.user_service import UserService

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


# ---------------------------------------------------------------------------
# Singletons (resolved from app state)
# ---------------------------------------------------------------------------
def get_db(request: Request) -> Database:
    return request.app.state.db


def get_limits(request: Request) -> ConcurrencyLimits:
    return request.app.state.limits


def get_supervisor(request: Request) -> BackgroundTaskSupervisor:
    return request.app.state.supervisor


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
def get_user_service(
    db: Annotated[Database, Depends(get_db)],
    limits: Annotated[ConcurrencyLimits, Depends(get_limits)],
) -> UserService:
    return UserService(db=db, limits=limits, repo=UserRepository(), hasher=password_hasher)


def get_auth_service(
    settings: Annotated[Settings, Depends(get_settings)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> AuthService:
    return AuthService(settings=settings, user_service=user_service)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
async def get_current_token(
    token: Annotated[str | None, Depends(_oauth2_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenPayload:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(token, expected_type=TokenType.ACCESS, settings=settings)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    payload: Annotated[TokenPayload, Depends(get_current_token)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    request: Request,
) -> User:
    user = await user_service.get(uuid.UUID(payload.sub))
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user account is disabled",
        )
    # Expose to downstream middleware (e.g. rate-limit identity).
    request.state.user_id = str(user.id)
    return user


async def get_current_superuser(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="superuser privileges required",
        )
    return user


# Convenience aliases for readable endpoint signatures.
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentSuperuser = Annotated[User, Depends(get_current_superuser)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
DbDep = Annotated[Database, Depends(get_db)]
SettingsAnnotated = Annotated[Settings, Depends(get_settings)]
