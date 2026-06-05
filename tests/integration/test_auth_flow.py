"""Register → login → /me happy path against a real DB."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_register_then_login_then_me(client, db):
    payload = {
        "email": "alice@example.com",
        "password": "SuperSecret-Pass-123",
        "full_name": "Alice Example",
    }

    register = await client.post("/api/v1/auth/register", json=payload)
    assert register.status_code == 201, register.text
    user = register.json()
    assert user["email"] == payload["email"]
    assert user["is_active"] is True

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200
    tokens = login.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    me = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == payload["email"]


async def test_duplicate_register_conflicts(client, db):
    payload = {
        "email": "dup@example.com",
        "password": "SuperSecret-Pass-123",
    }
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409
    assert second.json()["code"] == "conflict"


async def test_invalid_credentials_rejected(client, db):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "SuperSecret-Pass-123"},
    )

    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "wrong-password-1"},
    )
    assert bad.status_code == 401
