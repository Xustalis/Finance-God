"""统一响应格式"""

from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool = True
    data: Any = None
    error: dict | None = None
    meta: dict = {}

    @classmethod
    def ok(cls, data: Any = None, meta: dict | None = None) -> "ApiResponse":
        return cls(success=True, data=data, error=None, meta=meta or {})

    @classmethod
    def fail(cls, code: str, message: str, details: dict | None = None) -> "ApiResponse":
        return cls(success=False, data=None, error={"code": code, "message": message, "details": details or {}})
