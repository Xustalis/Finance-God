"""Finance-God application settings."""

from pathlib import Path

from pydantic import SecretStr, model_validator
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

    # SQLAlchemy SQL 语句回显日志，与 app_debug 解耦，默认关闭
    sql_echo: bool = False

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_god"
    database_url_sync: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/finance_god"

    # JWT
    secret_key: str = "change-me-in-production-please-use-a-long-random-string"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # 仅用于本地开发管理员初始化
    dev_admin_email: str = "admin@finance-god.local"
    dev_admin_password: str | None = None

    # 服务端 AI 凭据，不得序列化到 API
    deepseek_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_production_secret(self):
        if self.app_env != "development" and self.secret_key == "change-me-in-production-please-use-a-long-random-string":
            raise ValueError("SECRET_KEY must be explicitly configured outside development")
        return self

    @model_validator(mode="after")
    def validate_ai_provider_credentials(self):
        """DEEPSEEK_API_KEY 一旦显式配置就不得为空：启动时即报错，避免运行期
        选择 deepseek provider 时才暴露无效凭据。未配置（None）时保留开发环境
        mock 路径；非开发环境的 mock 适配器已在适配器解析处拒绝。"""
        if (
            self.deepseek_api_key is not None
            and not self.deepseek_api_key.get_secret_value().strip()
        ):
            raise ValueError(
                "DEEPSEEK_API_KEY is configured but empty; provide a valid key "
                "or remove the setting entirely"
            )
        return self

settings = Settings()
