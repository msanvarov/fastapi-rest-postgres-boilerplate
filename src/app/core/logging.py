"""Structured logging with context-vars for request correlation.

We use ``structlog`` because:

* It gives us key/value records that are trivially routable to any log
  aggregator (Datadog, Loki, ELK) without parsing.
* ``contextvars.ContextVar`` bindings flow across ``await`` boundaries,
  so a request id set at middleware-entry shows up in every log line
  emitted during that request — even from background tasks spawned
  with ``asyncio.create_task``.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars
from structlog.types import EventDict, Processor

from app.core.config import LogLevel, get_settings

# Public context vars — middleware writes, every log line reads via merge_contextvars
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)


def _drop_color_message_key(_: object, __: str, event_dict: EventDict) -> EventDict:
    """Uvicorn injects 'color_message' — drop it so it doesn't leak into JSON."""
    event_dict.pop("color_message", None)
    return event_dict


def _build_processors(*, json_logs: bool) -> list[Processor]:
    shared: list[Processor] = [
        merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.stdlib.add_logger_name,
        _drop_color_message_key,
    ]
    if json_logs:
        shared.extend(
            [
                structlog.processors.format_exc_info,
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ],
        )
    else:
        shared.extend(
            [
                structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
            ],
        )
    return shared


def configure_logging() -> None:
    """Install structlog as the single source of truth for app + stdlib logs."""
    settings = get_settings()
    level = logging.getLevelNamesMapping()[settings.app_log_level.value]
    json_logs = settings.app_log_json or settings.is_production

    processors = _build_processors(json_logs=json_logs)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logs (uvicorn, sqlalchemy, etc.) through the same pipeline.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=processors[:-1],
            processor=processors[-1],
        ),
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy loggers — keep only what we want.
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = False

    for inherited in ("uvicorn", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(inherited).handlers.clear()
        logging.getLogger(inherited).propagate = True

    # SQLAlchemy log level is independent of app log level.
    logging.getLogger("sqlalchemy.engine").setLevel(
        LogLevel.INFO.value if settings.postgres_echo else LogLevel.WARNING.value,
    )


def get_logger(name: str | None = None, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """Return a configured logger pre-bound with ``initial_values``."""
    return structlog.get_logger(name).bind(**initial_values)


__all__ = [
    "bind_contextvars",
    "clear_contextvars",
    "configure_logging",
    "get_logger",
    "request_id_ctx",
    "user_id_ctx",
]
