"""Finance-God onboarding API."""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.exceptions import register_exception_handlers
from server import finance_app
from server import lifespan as finance_lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with finance_lifespan(finance_app):
        yield


app = FastAPI(
    title=settings.app_name,
    description="Typed API for investment onboarding, educational profiling, and direction selection.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册异常处理器
register_exception_handlers(app)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """为每个请求添加 request_id"""
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


# 注册路由
from app.api.v1.router import api_router  # noqa: E402

app.include_router(api_router, prefix="/api/v1")
app.mount("/api/finance", finance_app)


@app.get("/")
async def root():
    return {"name": settings.app_name, "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
