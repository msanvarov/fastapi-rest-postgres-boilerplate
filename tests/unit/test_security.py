"""Token + password hashing — pure functions, easy to unit test."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    TokenType,
    create_token,
    decode_token,
    password_hasher,
)

pytestmark = pytest.mark.unit


def test_password_roundtrip():
    hashed = password_hasher.hash("correct horse battery staple")
    assert password_hasher.verify(hashed, "correct horse battery staple")
    assert not password_hasher.verify(hashed, "wrong password")


def test_password_hashes_are_salted():
    a = password_hasher.hash("same-password")
    b = password_hasher.hash("same-password")
    assert a != b


def test_token_roundtrip():
    token = create_token(subject="user-123", token_type=TokenType.ACCESS)
    payload = decode_token(token, expected_type=TokenType.ACCESS)
    assert payload.sub == "user-123"
    assert payload.typ is TokenType.ACCESS


def test_token_type_mismatch_rejected():
    token = create_token(subject="u", token_type=TokenType.ACCESS)
    with pytest.raises(InvalidTokenError):
        decode_token(token, expected_type=TokenType.REFRESH)


def test_tampered_token_rejected():
    token = create_token(subject="u", token_type=TokenType.ACCESS)
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(InvalidTokenError):
        decode_token(tampered)


def test_expired_token_rejected():
    """Hand-mint a token with an exp in the past — no monkey-patching needed."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": "u",
        "typ": TokenType.ACCESS.value,
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),
        "jti": str(uuid.uuid4()),
        "scopes": [],
    }
    expired = jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_token(expired)
