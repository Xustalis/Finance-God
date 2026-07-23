"""Application exceptions and FastAPI exception handlers.

Every domain error is represented by a subclass of ``AppException`` which
carries a machine-readable ``code``, a human-readable ``message``, and an
HTTP ``status_code``.

The two exception-handler functions at the bottom are registered in
``app/main.py`` so that *any* raised exception is converted to a uniform
JSON error response.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class AppException(Exception):
    """Base application exception.

    Attributes:
        code: Machine-readable error code (e.g. ``PROFILE_INCOMPLETE``).
        message: Human-readable description.
        status_code: HTTP status code.
        details: Optional structured payload with extra context.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


# ---------------------------------------------------------------------------
# Generic HTTP exceptions (404 / 401 / 403 / 409 / 422)
# ---------------------------------------------------------------------------


class NotFoundException(AppException):
    """Resource not found — HTTP 404."""

    def __init__(self, code: str = "NOT_FOUND", message: str = "Resource not found", **kw: Any) -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_404_NOT_FOUND, **kw)


class UnauthorizedException(AppException):
    """Authentication required — HTTP 401."""

    def __init__(self, code: str = "UNAUTHORIZED", message: str = "Authentication required", **kw: Any) -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_401_UNAUTHORIZED, **kw)


class ForbiddenException(AppException):
    """Insufficient permissions — HTTP 403."""

    def __init__(self, code: str = "FORBIDDEN", message: str = "Insufficient permissions", **kw: Any) -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_403_FORBIDDEN, **kw)


class ConflictException(AppException):
    """Optimistic-concurrency or uniqueness conflict — HTTP 409."""

    def __init__(self, code: str = "CONFLICT", message: str = "Resource conflict", **kw: Any) -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_409_CONFLICT, **kw)


class ValidationException(AppException):
    """Business-level validation failure — HTTP 422."""

    def __init__(self, code: str = "VALIDATION_ERROR", message: str = "Validation failed", **kw: Any) -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_UNPROCESSABLE_ENTITY, **kw)


# ---------------------------------------------------------------------------
# Business-rule exceptions  (PRD BR-01 … BR-15)
# ---------------------------------------------------------------------------


class ProfileIncompleteException(AppException):
    """BR-01: User profile completeness below required threshold."""

    def __init__(self, message: str = "Profile is incomplete", details: dict[str, Any] | None = None) -> None:
        super().__init__(code="PROFILE_INCOMPLETE", message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


class MandateNotActiveException(AppException):
    """BR-02 / BR-03: Mandate is not in ACTIVE state."""

    def __init__(self, message: str = "Investment mandate is not active", details: dict[str, Any] | None = None) -> None:
        super().__init__(code="MANDATE_NOT_ACTIVE", message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


class AutonomyInsufficientException(AppException):
    """BR-04: Mandate autonomy level does not permit the requested action."""

    def __init__(self, message: str = "Autonomy level insufficient", details: dict[str, Any] | None = None) -> None:
        super().__init__(code="AUTONOMY_INSUFFICIENT", message=message, status_code=status.HTTP_403_FORBIDDEN, details=details)


class RiskConstraintViolation(AppException):
    """BR-05: A risk rule has been violated."""

    def __init__(self, message: str = "Risk constraint violated", details: dict[str, Any] | None = None) -> None:
        super().__init__(code="RISK_CONSTRAINT_VIOLATION", message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


class CooldownActiveException(AppException):
    """BR-06: User is inside an active cooldown period."""

    def __init__(self, message: str = "Cooldown period is active", details: dict[str, Any] | None = None) -> None:
        super().__init__(code="COOLDOWN_ACTIVE", message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


class MarketUnavailableException(AppException):
    """BR-07: Required market data is not available."""

    def __init__(self, message: str = "Market data is unavailable", details: dict[str, Any] | None = None) -> None:
        super().__init__(code="MARKET_UNAVAILABLE", message=message, status_code=status.HTTP_503_SERVICE_UNAVAILABLE, details=details)


class ResearchInsufficientException(AppException):
    """BR-08: Not enough research context to generate a strategy."""

    def __init__(self, message: str = "Insufficient research data", details: dict[str, Any] | None = None) -> None:
        super().__init__(code="RESEARCH_INSUFFICIENT", message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


class LiveNotEnabledException(AppException):
    """BR-15: Live trading is not enabled; only simulation is permitted."""

    def __init__(self, message: str = "Live trading is not enabled", details: dict[str, Any] | None = None) -> None:
        super().__init__(code="LIVE_NOT_ENABLED", message=message, status_code=status.HTTP_403_FORBIDDEN, details=details)


# ---------------------------------------------------------------------------
# FastAPI exception handlers
# ---------------------------------------------------------------------------


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Convert any ``AppException`` into a uniform JSON error response."""
    logger.warning(
        "AppException [%s] %s — %s",
        exc.code,
        exc.message,
        request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions — returns 500 without leaking internals."""
    logger.exception("Unhandled exception on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {},
            }
        },
    )
