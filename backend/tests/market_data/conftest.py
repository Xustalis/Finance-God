from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from finance_god.market_data import (
    ALL_ENDPOINTS,
    EXPECTED_SDK_VERSION,
    PandaCredentials,
    PandaDataAdapter,
    PandaDataCapabilityCatalog,
)
from finance_god.market_data.transport import InjectedSDKTransportPolicy

NOW = datetime(2026, 7, 23, 2, 31, tzinfo=ZoneInfo("UTC"))
US_NOW = datetime(2026, 7, 24, 2, 31, tzinfo=ZoneInfo("UTC"))


class FakeSDK:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.responses: dict[str, object] = {}
        self.errors: dict[str, Exception] = {}
        self.auth_error: Exception | None = None

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(ALL_ENDPOINTS))

    def __getattr__(self, name: str) -> Any:
        if name not in ALL_ENDPOINTS:
            raise AttributeError(name)

        def endpoint(**kwargs: object) -> object:
            self.calls.append((name, kwargs))
            error = self.errors.get(name)
            if error is not None:
                raise error
            return self.responses.get(name, [])

        return endpoint

    def init_token(self, **kwargs: object) -> str:
        self.calls.append(("init_token", kwargs))
        if self.auth_error is not None:
            raise self.auth_error
        return "redacted-token"


def adapter(
    sdk: FakeSDK,
    *,
    username: str = "test-user",
    password: str = "test-password",
    now: datetime = NOW,
) -> PandaDataAdapter:
    return PandaDataAdapter(
        sdk=sdk,
        sdk_version=EXPECTED_SDK_VERSION,
        credentials=PandaCredentials(username=username, password=password),
        transport_policy=InjectedSDKTransportPolicy(),
        catalog=PandaDataCapabilityCatalog.for_injected_test_sdk(sdk),
        now=lambda: now,
    )


def stock_snapshot(
    symbol: str = "000001.SZ",
    *,
    data_time: str = "20260723 10:31:00",
    previous_close: float = 10.0,
    close: float = 10.3,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": data_time,
        "pre_close": previous_close,
        "open": 10.0,
        "high": 10.5,
        "low": 9.9,
        "close": close,
        "volume": 1000,
        "amount": 10_300,
    }


def bar(
    data_time: str,
    *,
    symbol: str = "000001.SZ",
    close: float = 10.2,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": data_time,
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": close,
        "volume": 1000,
        "amount": 10_200,
    }
