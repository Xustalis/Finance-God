"""Runtime configuration loaded from explicit environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_LOCAL_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _normalise_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if not base_url:
        raise ValueError("ARK_BASE_URL must not be empty")
    return base_url


@dataclass(frozen=True)
class Settings:
    """Runtime settings read from the process environment."""

    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_environment(cls) -> Settings:
        load_dotenv(_LOCAL_ENV_FILE, override=False)

        missing = [
            name
            for name in ("ARK_API_KEY", "ARK_BASE_URL", "ARK_MODEL")
            if not os.environ.get(name, "").strip()
        ]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

        return cls(
            api_key=os.environ["ARK_API_KEY"],
            base_url=_normalise_base_url(os.environ["ARK_BASE_URL"]),
            model=os.environ["ARK_MODEL"],
        )


class FmpConfigurationError(RuntimeError):
    """Raised when the FMP credential required by the isolated adapter is missing."""


@dataclass(frozen=True)
class FmpSettings:
    """FMP credential loaded only for an explicit, read-only FinRobot run."""

    api_key: str

    @classmethod
    def from_environment(cls) -> FmpSettings:
        load_dotenv(_LOCAL_ENV_FILE, override=False)
        api_key = os.environ.get("FMP_API_KEY", "").strip()
        if not api_key:
            raise FmpConfigurationError(
                "FMP_API_KEY is required for the isolated FinRobot FMP adapter."
            )
        return cls(api_key=api_key)


class PandaDataConfigurationError(RuntimeError):
    """Raised when PandaData credentials are missing or inconsistent."""


def _environment_value(canonical_name: str, legacy_name: str) -> str:
    canonical = os.environ.get(canonical_name, "").strip()
    legacy = os.environ.get(legacy_name, "").strip()
    if canonical and legacy and canonical != legacy:
        raise PandaDataConfigurationError(
            f"Conflicting PandaData settings: {canonical_name} and {legacy_name} differ."
        )
    return canonical or legacy


@dataclass(frozen=True)
class PandaDataSettings:
    """PandaData credentials, independent from the model-provider settings."""

    username: str
    password: str
    base_url: str | None = None

    @classmethod
    def from_environment(cls) -> PandaDataSettings:
        load_dotenv(_LOCAL_ENV_FILE, override=False)
        username = _environment_value("PANDA_DATA_USERNAME", "PANDADATA_USERNAME")
        password = _environment_value("PANDA_DATA_PASSWORD", "PANDADATA_PASSWORD")
        base_url = _environment_value("PANDA_DATA_BASE_URL", "PANDADATA_BASE_URL")
        if not username or not password:
            raise PandaDataConfigurationError(
                "PandaData credentials are required. Set PANDA_DATA_USERNAME and "
                "PANDA_DATA_PASSWORD after activating a PandaData account."
            )
        if not re.fullmatch(r"86\d{11}", username):
            raise PandaDataConfigurationError(
                "PANDA_DATA_USERNAME must be 86 followed by the 11-digit phone number "
                "registered with PandaAI."
            )
        return cls(username=username, password=password, base_url=base_url or None)
