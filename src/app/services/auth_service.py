"""Authentication service — token issuance and refresh."""

from __future__ import annotations

from app.core.config import Settings
from app.core.security import TokenType, create_token, decode_token
from app.db.models.user import User
from app.services.user_service import UserService


class AuthService:
    def __init__(self, settings: Settings, user_service: UserService) -> None:
        self._settings = settings
        self._users = user_service

    async def login(self, email: str, password: str) -> tuple[User, str, str, int]:
        user = await self._users.authenticate(email, password)
        access = create_token(
            subject=str(user.id),
            token_type=TokenType.ACCESS,
            settings=self._settings,
            scopes=["superuser"] if user.is_superuser else [],
        )
        refresh = create_token(
            subject=str(user.id),
            token_type=TokenType.REFRESH,
            settings=self._settings,
        )
        return user, access, refresh, self._settings.access_token_expire_minutes * 60

    async def refresh(self, refresh_token: str) -> tuple[str, str, int]:
        payload = decode_token(
            refresh_token,
            expected_type=TokenType.REFRESH,
            settings=self._settings,
        )
        # Re-issue access *and* refresh — refresh rotation reduces replay window.
        access = create_token(
            subject=payload.sub,
            token_type=TokenType.ACCESS,
            settings=self._settings,
        )
        new_refresh = create_token(
            subject=payload.sub,
            token_type=TokenType.REFRESH,
            settings=self._settings,
        )
        return access, new_refresh, self._settings.access_token_expire_minutes * 60


__all__ = ["AuthService"]
