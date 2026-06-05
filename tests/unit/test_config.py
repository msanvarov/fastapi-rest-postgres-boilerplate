"""Settings validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings

pytestmark = pytest.mark.unit


def test_short_secret_rejected():
    with pytest.raises(ValidationError):
        Settings(secret_key="too-short")  # type: ignore[call-arg]


def test_cors_origins_csv_split():
    settings = Settings(  # type: ignore[call-arg]
        secret_key="x" * 64,
        cors_origins="https://a.test, https://b.test",  # type: ignore[arg-type]
    )
    assert settings.cors_origins == ["https://a.test", "https://b.test"]


def test_production_flag():
    settings = Settings(secret_key="x" * 64, app_env=Environment.PRODUCTION)  # type: ignore[call-arg]
    assert settings.is_production is True


def test_database_url_uses_asyncpg():
    settings = Settings(secret_key="x" * 64)  # type: ignore[call-arg]
    assert str(settings.database_url).startswith("postgresql+asyncpg://")
