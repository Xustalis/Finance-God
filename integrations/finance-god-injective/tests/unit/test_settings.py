from decimal import Decimal

import pytest
from pydantic import ValidationError

from bridge.settings import Settings


def test_defaults_are_testnet_and_execution_is_disabled_without_key() -> None:
    settings = Settings(_env_file=None)

    assert settings.network == "testnet"
    assert settings.market_ticker == "INJ/USDT"
    assert settings.max_notional == Decimal("25")
    assert settings.execution_enabled is False
    assert settings.finance_god_sync_enabled is False


def test_mainnet_and_other_markets_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, BRIDGE_NETWORK="mainnet")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, BRIDGE_MARKET_TICKER="BTC/USDT")


def test_enabled_finance_god_sync_requires_a_read_token() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, FINANCE_GOD_SYNC_ENABLED=True)
