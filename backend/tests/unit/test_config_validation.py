import pytest
from pydantic import ValidationError

from app.config import Settings


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
