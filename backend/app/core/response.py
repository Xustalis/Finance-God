"""统一响应格式"""

from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, JsonValue, RootModel

DataT = TypeVar("DataT")


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    HTTP_400 = "HTTP_400"
    HTTP_401 = "HTTP_401"
    HTTP_403 = "HTTP_403"
    HTTP_404 = "HTTP_404"
    HTTP_409 = "HTTP_409"
    HTTP_500 = "HTTP_500"
    HTTP_502 = "HTTP_502"
    HTTP_503 = "HTTP_503"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetails(RootModel[dict[str, JsonValue]]):
    pass


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str
    details: ErrorDetails = Field(default_factory=lambda: ErrorDetails({}))


class ResponseMeta(BaseModel):
    request_id: str | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    data: None = None
    error: ErrorInfo
    meta: ResponseMeta = Field(default_factory=ResponseMeta)


STANDARD_ERROR_RESPONSES = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        401: "Authentication required or inactive user",
        400: "Malformed request or domain validation failure",
        403: "Insufficient role or prohibited action",
        404: "Owned resource not found",
        409: "Resource state conflict",
        422: "Typed request validation failed",
        502: "AI provider returned invalid structured output",
        503: "AI provider timed out",
        500: "Unexpected server error",
    }.items()
}


class ApiResponse(BaseModel, Generic[DataT]):
    success: bool = True
    data: DataT | None = None
    error: ErrorInfo | None = None
    meta: ResponseMeta = Field(default_factory=ResponseMeta)

    @classmethod
    def ok(cls, data: Any = None, meta: dict | None = None) -> "ApiResponse":
        return cls(success=True, data=data, error=None, meta=meta or {})

    @classmethod
    def fail(cls, code: str, message: str, details: dict | None = None) -> "ApiResponse":
        return cls(success=False, data=None, error={"code": code, "message": message, "details": details or {}})
