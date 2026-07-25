from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Finance-God Injective Bridge"
    database_url: str = Field(
        default="sqlite+aiosqlite:///./bridge.db",
        validation_alias="BRIDGE_DATABASE_URL",
    )
    admin_token: SecretStr = Field(
        default=SecretStr("development-only-change-me"),
        validation_alias="BRIDGE_ADMIN_TOKEN",
    )
    network: Literal["testnet"] = Field(
        default="testnet",
        validation_alias="BRIDGE_NETWORK",
    )
    market_ticker: str = Field(
        default="INJ/USDT",
        validation_alias="BRIDGE_MARKET_TICKER",
    )
    max_notional: Decimal = Field(
        default=Decimal("25"),
        gt=0,
        validation_alias="BRIDGE_MAX_NOTIONAL",
    )
    max_price_deviation_bps: Decimal = Field(
        default=Decimal("100"),
        gt=0,
        validation_alias="BRIDGE_MAX_PRICE_DEVIATION_BPS",
    )
    plan_ttl_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        validation_alias="BRIDGE_PLAN_TTL_SECONDS",
    )
    max_active_orders: int = Field(
        default=1,
        ge=1,
        le=10,
        validation_alias="BRIDGE_MAX_ACTIVE_ORDERS",
    )
    private_key_hex: SecretStr | None = Field(
        default=None,
        validation_alias="INJECTIVE_PRIVATE_KEY_HEX",
    )
    subaccount_index: int = Field(
        default=0,
        ge=0,
        validation_alias="INJECTIVE_SUBACCOUNT_INDEX",
    )
    finance_god_sync_enabled: bool = Field(
        default=False,
        validation_alias="FINANCE_GOD_SYNC_ENABLED",
    )
    finance_god_base_url: str = Field(
        default="http://host.docker.internal:8000",
        validation_alias="FINANCE_GOD_BASE_URL",
    )
    finance_god_read_token: SecretStr | None = Field(
        default=None,
        validation_alias="FINANCE_GOD_READ_TOKEN",
    )
    reconciliation_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        validation_alias="BRIDGE_RECONCILIATION_INTERVAL_SECONDS",
    )
    broadcast_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        validation_alias="BRIDGE_BROADCAST_TIMEOUT_SECONDS",
    )
    auto_create_schema: bool = Field(
        default=False,
        validation_alias="BRIDGE_AUTO_CREATE_SCHEMA",
    )

    @field_validator("market_ticker")
    @classmethod
    def validate_market_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized != "INJ/USDT":
            raise ValueError("v1 only supports the INJ/USDT Testnet spot market")
        return normalized

    @field_validator("finance_god_base_url")
    @classmethod
    def validate_finance_god_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("FINANCE_GOD_BASE_URL must be an HTTP(S) origin")
        return normalized

    @model_validator(mode="after")
    def validate_secrets(self) -> Settings:
        if self.finance_god_sync_enabled and not self.finance_god_read_token:
            raise ValueError("FINANCE_GOD_READ_TOKEN is required when Finance-God sync is enabled")
        if not self.admin_token.get_secret_value().strip():
            raise ValueError("BRIDGE_ADMIN_TOKEN cannot be blank")
        return self

    @property
    def execution_enabled(self) -> bool:
        if self.private_key_hex is None:
            return False
        return bool(self.private_key_hex.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
