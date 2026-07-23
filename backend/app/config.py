"""Finance-God 应用配置 - Pydantic Settings"""

from pathlib import Path

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
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_god"
    database_url_sync: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/finance_god"

    # JWT
    secret_key: str = "change-me-in-production-please-use-a-long-random-string"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # LLM
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    volcengine_api_key: str = ""
    volcengine_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    volcengine_model: str = "doubao-pro-32k"
    llm_provider: str = "mock"

    # 数据源
    pandaai_api_key: str = ""
    data_provider: str = "mock"

    # 仿真账户
    sim_initial_cash: float = 1000000


settings = Settings()
