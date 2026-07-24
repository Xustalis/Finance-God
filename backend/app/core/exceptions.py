import logging

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class FinanceGodError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict | None = None,
        http_status: int = 400,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status
        super().__init__(message)


def _error_body(request: Request, code: str, message: str, details=None) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": {"request_id": getattr(request.state, "request_id", None)},
    }


def register_exception_handlers(app) -> None:
    @app.exception_handler(FinanceGodError)
    async def finance_god_error_handler(request: Request, exc: FinanceGodError):
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_body(request, exc.code, exc.message, exc.details),
        )
    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError):
        errors = [
            {
                "location": list(error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_body(request, "VALIDATION_ERROR", "Request validation failed", {"errors": errors}),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            message = str(detail.get("message", "Request failed"))
            details = {key: value for key, value in detail.items() if key != "message"}
        else:
            message = str(detail)
            details = {}
        code = "VALIDATION_ERROR" if exc.status_code == 422 else f"HTTP_{exc.status_code}"
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, code, message, details),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        # 不将异常原文透传给客户端，原始异常仅记录服务端日志
        logger.warning("Unhandled ValueError on %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=400,
            content=_error_body(request, "VALIDATION_ERROR", "请求参数校验失败，请检查后重试"),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=_error_body(
                request,
                "INTERNAL_ERROR",
                "Internal server error",
                {"type": type(exc).__name__},
            ),
        )
