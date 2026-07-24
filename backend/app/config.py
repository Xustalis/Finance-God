"""Finance-God application settings."""

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 支持从 backend/ 或仓库根目录读取 .env
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
_ENV_CANDIDATES = (
    Path.cwd() / ".env",
    _BACKEND_DIR / ".env",
    _REPO_ROOT / ".env",
)
_ENV_FILES = tuple(str(p) for p in _ENV_CANDIDATES if p.is_file()) or (".env",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore")

    # 应用
    app_name: str = "Finance-God"
    app_env: str = "development"
    app_debug: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_god"
    database_url_sync: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/finance_god"

    # JWT
    secret_key: str = "change-me-in-production-please-use-a-long-random-string"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    @model_validator(mode="after")
    def validate_production_secret(self):
        if self.app_env != "development" and self.secret_key == "change-me-in-production-please-use-a-long-random-string":
            raise ValueError("SECRET_KEY must be explicitly configured outside development")
        return self

settings = Settings()
