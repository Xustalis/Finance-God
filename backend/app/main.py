"""FastAPI 应用入口"""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.exceptions import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动: 初始化插件
    from app.plugins import init_all_plugins
    init_all_plugins()
    yield
    # 关闭: 清理资源


app = FastAPI(
    title=settings.app_name,
    description="心智驱动的 AI 投资顾问 - Hackathon MVP",
    version="0.1.0",
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


@app.get("/")
async def root():
    return {"name": settings.app_name, "version": "0.1.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
