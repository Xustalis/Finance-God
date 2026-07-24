"""Explicit, redacted and stable market-data failure taxonomy."""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from uuid import uuid4

_URL_PATTERN = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_API_KEY_PATTERN = re.compile(
    r"\b(?:api[_-]?key|token|secret)\s*[:=]\s*[A-Za-z0-9._~+/=-]{8,}",
    re.IGNORECASE,
)
_SECRET_TOKEN_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_HTTP_STATUS_PATTERN = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)


class ErrorKind(StrEnum):
    CONFIGURATION = "configuration"
    TRANSIENT = "transient"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    PARAMETER = "parameter"
    SCHEMA = "schema"
    EMPTY = "empty"
    CAPABILITY = "capability"
    DEADLINE = "deadline"
    INTERNAL = "internal"


class PublicErrorCode(StrEnum):
    CONFIGURATION_ERROR = "MARKET_DATA_CONFIGURATION_ERROR"
    UPSTREAM_TEMPORARY = "MARKET_DATA_UPSTREAM_TEMPORARY"
    AUTHENTICATION_FAILED = "MARKET_DATA_AUTHENTICATION_FAILED"
    PERMISSION_DENIED = "MARKET_DATA_PERMISSION_DENIED"
    INVALID_REQUEST = "MARKET_DATA_INVALID_REQUEST"
    SCHEMA_INVALID = "MARKET_DATA_SCHEMA_INVALID"
    CAPABILITY_UNAVAILABLE = "MARKET_DATA_CAPABILITY_UNAVAILABLE"
    DEADLINE_EXCEEDED = "MARKET_DATA_DEADLINE_EXCEEDED"
    INTERNAL_ERROR = "MARKET_DATA_INTERNAL_ERROR"


_PUBLIC = {
    ErrorKind.CONFIGURATION: (
        PublicErrorCode.CONFIGURATION_ERROR,
        "The market-data service is not fully configured.",
    ),
    ErrorKind.TRANSIENT: (
        PublicErrorCode.UPSTREAM_TEMPORARY,
        "PandaData is temporarily unavailable.",
    ),
    ErrorKind.AUTHENTICATION: (
        PublicErrorCode.AUTHENTICATION_FAILED,
        "PandaData authentication failed.",
    ),
    ErrorKind.PERMISSION: (
        PublicErrorCode.PERMISSION_DENIED,
        "PandaData denied access to this dataset.",
    ),
    ErrorKind.PARAMETER: (
        PublicErrorCode.INVALID_REQUEST,
        "The market-data request is invalid.",
    ),
    ErrorKind.SCHEMA: (
        PublicErrorCode.SCHEMA_INVALID,
        "PandaData returned data outside the accepted schema.",
    ),
    ErrorKind.EMPTY: (
        PublicErrorCode.SCHEMA_INVALID,
        "PandaData returned an unexpected empty result.",
    ),
    ErrorKind.CAPABILITY: (
        PublicErrorCode.CAPABILITY_UNAVAILABLE,
        "The requested market-data capability is not enabled.",
    ),
    ErrorKind.DEADLINE: (
        PublicErrorCode.DEADLINE_EXCEEDED,
        "The market-data request exceeded its deadline.",
    ),
    ErrorKind.INTERNAL: (
        PublicErrorCode.INTERNAL_ERROR,
        "The market-data request failed internally.",
    ),
}


class MarketDataError(RuntimeError):
    def __init__(
        self,
        kind: ErrorKind,
        internal_message: str,
        *,
        endpoint: str | None = None,
        trace_id: str | None = None,
        secrets: Iterable[str] = (),
    ) -> None:
        self.kind = kind
        self.endpoint = endpoint
        self.trace_id = trace_id or uuid4().hex
        self.internal_message = redact_text(internal_message, secrets=secrets)
        self.public_code, self.public_message = _PUBLIC[kind]
        super().__init__(f"{self.public_code.value} trace_id={self.trace_id}")

    @property
    def retryable(self) -> bool:
        return self.kind is ErrorKind.TRANSIENT

    def public_payload(self) -> dict[str, str]:
        return {
            "code": self.public_code.value,
            "message": self.public_message,
            "trace_id": self.trace_id,
        }


class MarketDataConfigurationError(MarketDataError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorKind.CONFIGURATION, message)


class MarketDataResponseError(MarketDataError):
    def __init__(self, message: str, *, endpoint: str | None = None) -> None:
        super().__init__(ErrorKind.SCHEMA, message, endpoint=endpoint)


def redact_text(value: object, *, secrets: Iterable[str] = ()) -> str:
    text = str(value)
    text = _URL_PATTERN.sub("[redacted-url]", text)
    text = _BEARER_PATTERN.sub("Bearer [redacted-secret]", text)
    text = _JWT_PATTERN.sub("[redacted-jwt]", text)
    text = _API_KEY_PATTERN.sub("[redacted-api-key]", text)
    text = _SECRET_TOKEN_PATTERN.sub("[redacted-api-key]", text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted-secret]")
    return text[:320]


def classify_upstream_error(
    error: Exception,
    *,
    endpoint: str,
    secrets: Iterable[str] = (),
) -> MarketDataError:
    chain = _cause_chain(error)
    service_code = next(
        (
            code
            for item in chain
            if (code := _integer(getattr(item, "code", None))) is not None
            and code >= 100_000
        ),
        None,
    )
    status = _http_status(chain)
    lowered = " | ".join(str(item).lower() for item in chain)
    if service_code is not None:
        kind = _service_code_kind(service_code)
    elif status in {408, 429, 500, 502, 503, 504}:
        kind = ErrorKind.TRANSIENT
    elif status == 401:
        kind = ErrorKind.AUTHENTICATION
    elif status == 403:
        kind = ErrorKind.PERMISSION
    elif status in {400, 404, 409, 422}:
        kind = ErrorKind.PARAMETER
    elif any(
        isinstance(item, (TimeoutError, ConnectionError))
        or type(item).__name__
        in {
            "Timeout",
            "ReadTimeout",
            "ConnectTimeout",
            "ConnectionError",
            "URLError",
        }
        for item in chain
    ):
        kind = ErrorKind.TRANSIENT
    elif "authentication" in lowered or "unauthor" in lowered:
        kind = ErrorKind.AUTHENTICATION
    elif (
        any(isinstance(item, PermissionError) for item in chain)
        or "permission" in lowered
    ):
        kind = ErrorKind.PERMISSION
    elif any(isinstance(item, (TypeError, ValueError)) for item in chain):
        kind = ErrorKind.PARAMETER
    else:
        kind = ErrorKind.SCHEMA
    safe = redact_text(" <- ".join(str(item) for item in chain), secrets=secrets)
    return MarketDataError(
        kind,
        f"PandaData {endpoint} failed: {safe}",
        endpoint=endpoint,
        secrets=secrets,
    )


def _cause_chain(error: Exception) -> tuple[Exception, ...]:
    result: list[Exception] = []
    current: BaseException | None = error
    while isinstance(current, Exception) and current not in result:
        result.append(current)
        current = current.__cause__ or current.__context__
    return tuple(result)


def _http_status(chain: Iterable[Exception]) -> int | None:
    for error in chain:
        code = _integer(getattr(error, "code", None))
        for value in (
            _integer(getattr(error, "status_code", None)),
            code if code is not None and 100 <= code <= 599 else None,
        ):
            if isinstance(value, int) and 100 <= value <= 599:
                return value
        match = _HTTP_STATUS_PATTERN.search(str(error))
        if match:
            return int(match.group(1))
    return None


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _service_code_kind(code: int) -> ErrorKind:
    if 100_000 <= code <= 100_008 or code == 600_002:
        return ErrorKind.PARAMETER
    if 200_001 <= code <= 200_007:
        return ErrorKind.AUTHENTICATION
    if 200_101 <= code <= 200_104:
        return ErrorKind.PERMISSION
    if code in {
        400_002,
        500_001,
        500_002,
        500_003,
        500_004,
        500_005,
        500_006,
        600_001,
        900_001,
    }:
        return ErrorKind.TRANSIENT
    return ErrorKind.SCHEMA
