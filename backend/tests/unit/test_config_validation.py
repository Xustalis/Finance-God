import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas.admin import AISettingsUpdate


def test_non_development_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production")


def test_non_development_accepts_explicit_strong_jwt_secret() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        secret_key="production-only-secret-that-is-long-and-random-123456",
    )
    assert settings.app_env == "production"


def test_deepseek_configuration_rejects_unknown_model() -> None:
    with pytest.raises(ValidationError, match="Unsupported DeepSeek model"):
        AISettingsUpdate(
            capability="text",
            provider="deepseek",
            model_name="arbitrary-model",
        )


def test_speech_configuration_rejects_non_browser_provider() -> None:
    with pytest.raises(ValidationError, match="browser"):
        AISettingsUpdate(
            capability="stt",
            provider="deepseek",
            model_name="deepseek-v4-flash",
        )
