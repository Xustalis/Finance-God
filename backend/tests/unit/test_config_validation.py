import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import ROOT_ENV_FILE, Settings, load_local_environment
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


def test_stepfun_configuration_only_accepts_benchmarked_profile_model() -> None:
    with pytest.raises(ValidationError, match="Unsupported StepFun model"):
        AISettingsUpdate(
            capability="text",
            provider="stepfun",
            model_name="step-3.7-flash",
        )


def test_stepfun_configuration_rejects_arbitrary_key_reference() -> None:
    with pytest.raises(ValidationError, match="STEPFUN_API_KEY"):
        AISettingsUpdate(
            capability="text",
            provider="stepfun",
            model_name="step-3.5-flash-2603",
            api_key_ref="ARBITRARY_KEY",
        )


def test_speech_configuration_rejects_non_browser_provider() -> None:
    with pytest.raises(ValidationError, match="browser"):
        AISettingsUpdate(
            capability="stt",
            provider="deepseek",
            model_name="deepseek-v4-flash",
        )


def test_root_env_is_the_only_implicit_local_env() -> None:
    assert ROOT_ENV_FILE == Path(__file__).resolve().parents[3] / ".env"
    assert Settings.model_config["env_file"] == str(ROOT_ENV_FILE)


def test_root_env_loader_populates_direct_os_getenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("PANDA_DATA_USERNAME=8613800000000\n")
    monkeypatch.delenv("PANDA_DATA_USERNAME", raising=False)

    load_local_environment(env_file)

    assert os.getenv("PANDA_DATA_USERNAME") == "8613800000000"
