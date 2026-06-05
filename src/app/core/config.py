"""Typed, environment-driven settings.

Settings are loaded once at import time via ``pydantic-settings`` and cached
through ``@lru_cache`` so every consumer reads the same immutable instance.
This keeps configuration explicit, testable, and trivially overridable in
tests (just call ``get_settings.cache_clear()`` after monkey-patching env).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import (
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    computed_field,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Runtime environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class LogLevel(StrEnum):
    """Standard log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Top-level settings — keep flat; group via prefix where useful."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- App ---------------------------------------------------------------
    app_name: str = "FastAPI Async Boilerplate"
    app_env: Environment = Environment.DEVELOPMENT
    app_debug: bool = False
    app_host: str = "0.0.0.0"  # noqa: S104 — bind-all is intentional for container deploys
    app_port: int = Field(default=8000, ge=1, le=65_535)
    app_log_level: LogLevel = LogLevel.INFO
    app_log_json: bool = False
    api_v1_prefix: str = "/api/v1"
    project_root: Path = Path(__file__).resolve().parents[3]

    # ---- Security ----------------------------------------------------------
    secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1)
    refresh_token_expire_days: int = Field(default=7, ge=1)
    cors_origins: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] = Field(default_factory=lambda: ["*"])

    # ---- Postgres ----------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65_535)
    postgres_user: str = "postgres"
    postgres_password: SecretStr = SecretStr("postgres")
    postgres_db: str = "app"
    postgres_pool_size: int = Field(default=20, ge=1)
    postgres_max_overflow: int = Field(default=10, ge=0)
    postgres_pool_timeout: int = Field(default=30, ge=1)
    postgres_pool_recycle: int = Field(default=1800, ge=60)
    postgres_echo: bool = False

    # ---- Redis -------------------------------------------------------------
    redis_url: RedisDsn = Field(default=RedisDsn("redis://localhost:6379/0"))

    # ---- Concurrency -------------------------------------------------------
    db_semaphore_limit: int = Field(default=50, ge=1)
    http_semaphore_limit: int = Field(default=100, ge=1)
    cpu_semaphore_limit: int = Field(default=4, ge=1)
    task_queue_max_size: int = Field(default=1_000, ge=1)
    request_timeout_seconds: float = Field(default=30.0, gt=0)

    # ---- Rate limiting -----------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = Field(default=120, ge=1)

    # -----------------------------------------------------------------------
    # Validators
    # -----------------------------------------------------------------------
    @field_validator("secret_key")
    @classmethod
    def _secret_must_be_strong(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            msg = "secret_key must be at least 32 characters"
            raise ValueError(msg)
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    # -----------------------------------------------------------------------
    # Derived properties
    # -----------------------------------------------------------------------
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> PostgresDsn:
        """Async SQLAlchemy URL — uses asyncpg driver."""
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_sync(self) -> PostgresDsn:
        """Sync URL for Alembic — uses psycopg/psycopg2 only at migration time."""
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so we read env exactly once. Tests should call
    ``get_settings.cache_clear()`` after mutating the environment.
    """
    return Settings()  # type: ignore[call-arg]


SettingsDep = Annotated[Settings, "Settings"]
