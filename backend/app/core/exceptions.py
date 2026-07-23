"""全局异常定义与处理"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class FinanceGodError(Exception):
    """Finance-God 基础异常"""

    http_status: int = 400

    def __init__(self, code: str, message: str, details: dict | None = None, http_status: int | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        if http_status is not None:
            self.http_status = http_status
        super().__init__(message)


class ProfileIncompleteError(FinanceGodError):
    def __init__(self, completeness: float):
        super().__init__(
            code="PROFILE_INCOMPLETE",
            message=f"画像完整度不足: {completeness:.0%}, 需达到 60% 以上",
            details={"completeness": completeness, "required": 0.6},
            http_status=400,
        )


class MandateNotActiveError(FinanceGodError):
    def __init__(self, status: str = "draft"):
        super().__init__(
            code="MANDATE_NOT_ACTIVE",
            message="当前无有效授权书",
            details={"mandate_status": status, "required_action": "activate_mandate"},
            http_status=400,
        )


class AutonomyInsufficientError(FinanceGodError):
    def __init__(self, current_level: str, required_level: str = "L2"):
        super().__init__(
            code="AUTONOMY_INSUFFICIENT",
            message=f"自主级别不足: 当前 {current_level}, 需要 {required_level}",
            details={"current_level": current_level, "required_level": required_level},
            http_status=403,
        )


class CooldownActiveError(FinanceGodError):
    def __init__(self, cooldown_id: str):
        super().__init__(
            code="COOLDOWN_ACTIVE",
            message="冷静期生效中, 新订单已暂停",
            details={"cooldown_id": cooldown_id},
            http_status=403,
        )


class RiskBlockedError(FinanceGodError):
    def __init__(self, rule_id: str, rule_name: str, explanation: str):
        super().__init__(
            code="RISK_BLOCKED",
            message=f"风控拦截: {rule_name}",
            details={"rule_id": rule_id, "explanation": explanation},
            http_status=403,
        )


class MarketUnavailableError(FinanceGodError):
    def __init__(self, reason: str):
        super().__init__(
            code="MARKET_UNAVAILABLE",
            message=f"市场环境不可用: {reason}",
            details={"reason": reason},
            http_status=503,
        )


class ResearchInsufficientError(FinanceGodError):
    def __init__(self, reason: str):
        super().__init__(
            code="RESEARCH_INSUFFICIENT",
            message=f"研究证据不足: {reason}",
            details={"reason": reason},
            http_status=400,
        )


class LiveNotEnabledError(FinanceGodError):
    def __init__(self):
        super().__init__(
            code="LIVE_NOT_ENABLED",
            message="实盘功能未启用",
            details={"required": "account_setup"},
            http_status=403,
        )


class StrategyPausedError(FinanceGodError):
    def __init__(self, reason: str = "用户已暂停"):
        super().__init__(
            code="STRATEGY_PAUSED",
            message=f"策略已暂停: {reason}",
            details={"reason": reason},
            http_status=403,
        )


class ResourceNotFoundError(FinanceGodError):
    def __init__(self, resource: str = "resource", resource_id: str | None = None):
        super().__init__(
            code="NOT_FOUND",
            message=f"{resource}不存在",
            details={"resource": resource, "id": resource_id},
            http_status=404,
        )


class ForbiddenError(FinanceGodError):
    def __init__(self, message: str = "无权访问该资源"):
        super().__init__(
            code="FORBIDDEN",
            message=message,
            details={},
            http_status=403,
        )


class ValidationError(FinanceGodError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            details=details or {},
            http_status=400,
        )


def _error_body(request: Request, code: str, message: str, details: dict | None = None) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "meta": {"request_id": getattr(request.state, "request_id", None)},
    }


def register_exception_handlers(app):
    """注册全局异常处理器"""

    @app.exception_handler(FinanceGodError)
    async def finance_god_error_handler(request: Request, exc: FinanceGodError):
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_body(request, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            message = str(detail.get("message", detail))
            details = detail if "message" not in detail else {k: v for k, v in detail.items() if k != "message"}
        else:
            message = str(detail)
            details = {}
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, f"HTTP_{exc.status_code}", message, details),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=400,
            content=_error_body(request, "VALIDATION_ERROR", str(exc)),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=_error_body(
                request,
                "INTERNAL_ERROR",
                "服务器内部错误",
                {"type": type(exc).__name__},
            ),
        )
