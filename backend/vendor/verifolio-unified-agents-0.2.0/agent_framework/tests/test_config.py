from __future__ import annotations

import pytest

import research_runtime.config as runtime_config
from research_runtime.config import (
    FmpConfigurationError,
    FmpSettings,
    PandaDataConfigurationError,
    PandaDataSettings,
    Settings,
)


def test_loads_required_environment_and_normalises_base_url(monkeypatch) -> None:
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setenv("ARK_BASE_URL", "https://api.example.test/api/v3/")
    monkeypatch.setenv("ARK_MODEL", "ep-20260722093003-7swj9")

    settings = Settings.from_environment()

    assert settings.base_url == "https://api.example.test/api/v3"
    assert settings.model == "ep-20260722093003-7swj9"


def test_loads_required_fmp_key_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("FMP_API_KEY", "test-fmp-key")

    assert FmpSettings.from_environment().api_key == "test-fmp-key"


def test_fmp_settings_fail_without_a_key(monkeypatch) -> None:
    monkeypatch.setattr(runtime_config, "load_dotenv", lambda *_args, **_kwargs: False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    with pytest.raises(FmpConfigurationError, match="FMP_API_KEY is required"):
        FmpSettings.from_environment()


def test_loads_pandadata_settings_and_rejects_conflicting_legacy_names(monkeypatch) -> None:
    monkeypatch.setenv("PANDA_DATA_USERNAME", "8613812345678")
    monkeypatch.setenv("PANDA_DATA_PASSWORD", "test-password")
    monkeypatch.setenv("PANDADATA_USERNAME", "8613812345678")
    monkeypatch.setenv("PANDADATA_PASSWORD", "test-password")

    settings = PandaDataSettings.from_environment()

    assert settings.username == "8613812345678"
    assert settings.password == "test-password"

    monkeypatch.setenv("PANDADATA_PASSWORD", "different-password")
    with pytest.raises(PandaDataConfigurationError, match="Conflicting PandaData settings"):
        PandaDataSettings.from_environment()


def test_pandadata_settings_require_the_documented_phone_number_format(monkeypatch) -> None:
    monkeypatch.setenv("PANDA_DATA_USERNAME", "13812345678")
    monkeypatch.setenv("PANDA_DATA_PASSWORD", "test-password")

    with pytest.raises(PandaDataConfigurationError, match="must be 86 followed"):
        PandaDataSettings.from_environment()


def test_pandadata_settings_fail_without_credentials(monkeypatch) -> None:
    monkeypatch.setattr(runtime_config, "load_dotenv", lambda *_args, **_kwargs: False)
    for variable in (
        "PANDA_DATA_USERNAME",
        "PANDA_DATA_PASSWORD",
        "PANDADATA_USERNAME",
        "PANDADATA_PASSWORD",
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(PandaDataConfigurationError, match="PandaData credentials are required"):
        PandaDataSettings.from_environment()
