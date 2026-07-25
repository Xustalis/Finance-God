"""Finance-God onboarding API."""

import uuid
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from server import finance_app
from server import lifespan as finance_lifespan

from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.session import dispose_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with finance_lifespan(finance_app):
            yield
    finally:
        await dispose_database()


app = FastAPI(
    title=settings.app_name,
    description="Typed API for investment onboarding, educational profiling, and direction selection.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS：origins 来自逗号分隔配置；凭据模式下禁止通配符，剔除空项与 "*"，
# 方法与请求头收敛到实际使用的集合（Bearer 鉴权 + JSON/NDJSON 请求体）。
_cors_origins = [
    origin.strip()
    for origin in settings.cors_origins.split(",")
    if origin.strip() and origin.strip() != "*"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Idempotency-Key"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

# 注册异常处理器
register_exception_handlers(app)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Attach stable request correlation and server processing time."""
    started_at = perf_counter()
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Server-Timing"] = (
        f"app;dur={(perf_counter() - started_at) * 1000:.2f}"
    )
    return response


# 注册路由
from app.api.v1.router import api_router  # noqa: E402

app.include_router(api_router, prefix="/api/v1")
app.mount("/api/finance", finance_app)
# 双路径族兼容：前端以 baseURL='/api' 直接调用 /api/market/*、/api/simulation/*、
# /api/workspace/* 等端点。/api 挂载必须放在 /api/finance 之后（避免吞掉该前缀），
# 且 /api/v1 路由已先通过 include_router 注册，仍会优先匹配。
app.mount("/api", finance_app)


@app.get("/")
async def root():
    return {"name": settings.app_name, "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
