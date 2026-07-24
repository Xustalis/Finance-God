"""Finance-God application settings."""

from pathlib import Path

from dotenv import load_dotenv
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_ENV_FILE = _BACKEND_DIR.parent / ".env"


def load_local_environment(env_file: Path = ROOT_ENV_FILE) -> None:
    """Load the repository-root env for settings and direct os.getenv users."""
    load_dotenv(env_file, override=False)


load_local_environment()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV_FILE),
        extra="ignore",
    )

    # 应用
    app_name: str = "Finance-God"
    app_env: str = "development"
    app_debug: bool = True
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # SQLAlchemy SQL 语句回显日志，与 app_debug 解耦，默认关闭
    sql_echo: bool = False

    # 数据库
    # 全环境统一使用 PostgreSQL；本地开发需先启动 postgres（docker compose up db
    # 或本机实例），再执行 alembic upgrade head。
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
    stepfun_api_key: SecretStr | None = None

    # 火山方舟 ARK（OpenAI 兼容）凭据；env 配置后作为默认文本提供方替代 mock
    ark_api_key: SecretStr | None = None
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_model: str | None = None

    # AI /chat/completions 读超时（秒）。结构化 JSON 输出叠加大提示词时，
    # 部分模型（如豆包 lite）单轮延迟可超过 30s，默认放宽到 60s，可按需覆盖。
    ai_request_timeout_seconds: float = 60.0

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
        if (
            self.stepfun_api_key is not None
            and not self.stepfun_api_key.get_secret_value().strip()
        ):
            raise ValueError(
                "STEPFUN_API_KEY is configured but empty; provide a valid key "
                "or remove the setting entirely"
            )
        if (
            self.ark_api_key is not None
            and not self.ark_api_key.get_secret_value().strip()
        ):
            raise ValueError(
                "ARK_API_KEY is configured but empty; provide a valid key "
                "or remove the setting entirely"
            )
        return self

settings = Settings()
