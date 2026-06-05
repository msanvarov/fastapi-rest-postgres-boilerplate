"""Domain-level exception hierarchy + FastAPI mappers.

We keep service/repository code free of FastAPI imports. They raise plain
:class:`AppError` subclasses; a single handler in
:mod:`app.middleware.error_handlers` translates them to HTTP responses.

This split keeps the domain testable in isolation and makes it trivial to
re-expose the same services over a non-HTTP transport (CLI, gRPC, worker).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class AppError(Exception):
    """Base for all application-defined errors.

    Subclass per failure mode; the HTTP layer maps :attr:`status_code` and
    :attr:`code` to the response.
    """

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# 4xx — client errors
# ---------------------------------------------------------------------------
class ValidationError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "validation_error"
    message = "Request failed validation."


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    code = "conflict"
    message = "The request conflicts with current resource state."


class UnauthorizedError(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "unauthorized"
    message = "Authentication is required."


class ForbiddenError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = "forbidden"
    message = "You do not have permission to perform this action."


class RateLimitError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Rate limit exceeded; slow down."


# ---------------------------------------------------------------------------
# 5xx — server / infra
# ---------------------------------------------------------------------------
class ServiceUnavailableError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "A dependency is temporarily unavailable."


class DependencyTimeoutError(ServiceUnavailableError):
    code = "dependency_timeout"
    message = "A dependency did not respond within the allotted time."


__all__ = [
    "AppError",
    "ConflictError",
    "DependencyTimeoutError",
    "ForbiddenError",
    "NotFoundError",
    "RateLimitError",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "ValidationError",
]
