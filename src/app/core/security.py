"""Password hashing and JWT token plumbing.

Argon2id is used for passwords (OWASP recommendation as of 2024). It's
memory-hard, side-channel resistant, and has tunable cost. Hashing is CPU-bound,
so callers should run it via :func:`app.core.concurrency.run_cpu_bound` when
processing many requests concurrently — see :class:`PasswordHasher`.

JWT signing uses HS256 by default. Switch to RS256/EdDSA when you have a KMS
to manage the keypair; the code paths are otherwise identical.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final

import jwt
from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import VerifyMismatchError
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings

# Tuned per OWASP 2024 cheat-sheet — ~50ms on modern CPUs.
_ARGON2: Final = Argon2Hasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


class TokenType(StrEnum):
    """Discriminator for access vs refresh tokens — embedded in the JWT ``typ`` claim."""

    ACCESS = "access"
    REFRESH = "refresh"  # noqa: S105 — not a secret


class TokenPayload(BaseModel):
    """Validated claims extracted from a verified JWT."""

    sub: str
    typ: TokenType
    exp: datetime
    iat: datetime
    jti: str
    scopes: list[str] = Field(default_factory=list)


class InvalidTokenError(Exception):
    """Raised when a token fails signature, expiry, or schema validation."""


class PasswordHasher:
    """Async-friendly wrapper around argon2-cffi.

    Hashing is CPU-bound; calling it directly on the event loop will stall
    every other request. We expose it as a method that callers must invoke via
    :func:`run_cpu_bound`. The wrapper exists so the cost params live in
    a single place and so we can swap the algorithm later.
    """

    def hash(self, password: str) -> str:
        return _ARGON2.hash(password)

    def verify(self, hashed: str, password: str) -> bool:
        try:
            return _ARGON2.verify(hashed, password)
        except VerifyMismatchError:
            return False

    def needs_rehash(self, hashed: str) -> bool:
        """True if argon2 params have changed since this hash was created."""
        return _ARGON2.check_needs_rehash(hashed)


def create_token(
    *,
    subject: str,
    token_type: TokenType,
    settings: Settings | None = None,
    scopes: list[str] | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    expires_delta = (
        timedelta(minutes=settings.access_token_expire_minutes)
        if token_type is TokenType.ACCESS
        else timedelta(days=settings.refresh_token_expire_days)
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
        "scopes": scopes or [],
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(
    token: str,
    *,
    expected_type: TokenType | None = None,
    settings: Settings | None = None,
) -> TokenPayload:
    settings = settings or get_settings()
    try:
        raw = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "typ", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        msg = "token has expired"
        raise InvalidTokenError(msg) from exc
    except jwt.InvalidTokenError as exc:
        msg = "token signature or claims invalid"
        raise InvalidTokenError(msg) from exc

    try:
        payload = TokenPayload.model_validate(raw)
    except Exception as exc:
        msg = "token claims failed schema validation"
        raise InvalidTokenError(msg) from exc

    if expected_type is not None and payload.typ is not expected_type:
        msg = f"expected token type {expected_type.value}, got {payload.typ.value}"
        raise InvalidTokenError(msg)

    return payload


# Module-level singleton — stateless, safe to share.
password_hasher = PasswordHasher()


__all__ = [
    "InvalidTokenError",
    "PasswordHasher",
    "TokenPayload",
    "TokenType",
    "create_token",
    "decode_token",
    "password_hasher",
]
