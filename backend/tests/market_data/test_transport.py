from __future__ import annotations

from dataclasses import dataclass

import pytest
from finance_god.market_data import (
    EXPECTED_SDK_VERSION,
    ErrorKind,
    InjectedSDKTransportPolicy,
    MarketDataError,
    OperationBudget,
    PandaCredentials,
    PandaData012TransportPolicy,
    PandaDataAdapter,
    PandaDataCapabilityCatalog,
    ReleaseState,
)
from finance_god.market_data.errors import classify_upstream_error
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER

from .conftest import NOW, FakeSDK, stock_snapshot


def test_adapter_configures_one_attempt_budget_once_after_authentication() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    policy = InjectedSDKTransportPolicy()
    subject = PandaDataAdapter(
        sdk=sdk,
        sdk_version=EXPECTED_SDK_VERSION,
        credentials=PandaCredentials("user", "password"),
        transport_policy=policy,
        catalog=PandaDataCapabilityCatalog.for_injected_test_sdk(sdk),
        now=lambda: NOW,
    )
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")

    subject.fetch_snapshot(instrument, release_state=ReleaseState.RELEASED)
    subject.fetch_snapshot(instrument, release_state=ReleaseState.RELEASED)

    assert policy.configured_budgets == [OperationBudget()]
    assert [name for name, _ in sdk.calls].count("init_token") == 1


def test_transport_policy_is_installed_before_authentication() -> None:
    events: list[str] = []

    class OrderedSDK(FakeSDK):
        def init_token(self, **kwargs: object) -> str:
            events.append("authenticate")
            return super().init_token(**kwargs)

    class OrderedPolicy(InjectedSDKTransportPolicy):
        def configure(self, sdk: object, budget: OperationBudget) -> None:
            events.append("configure_transport")
            super().configure(sdk, budget)

    sdk = OrderedSDK()
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    subject = PandaDataAdapter(
        sdk=sdk,
        sdk_version=EXPECTED_SDK_VERSION,
        credentials=PandaCredentials("user", "password"),
        transport_policy=OrderedPolicy(),
        catalog=PandaDataCapabilityCatalog.for_injected_test_sdk(sdk),
        now=lambda: NOW,
    )

    subject.fetch_snapshot(
        DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ"),
        release_state=ReleaseState.RELEASED,
    )

    assert events == ["configure_transport", "authenticate"]


def test_adapter_reports_deadline_without_fabricating_success() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    ticks = iter((0.0, 13.0))
    subject = PandaDataAdapter(
        sdk=sdk,
        sdk_version=EXPECTED_SDK_VERSION,
        credentials=PandaCredentials("user", "password"),
        transport_policy=InjectedSDKTransportPolicy(),
        catalog=PandaDataCapabilityCatalog.for_injected_test_sdk(sdk),
        now=lambda: NOW,
        operation_clock=lambda: next(ticks),
    )

    with pytest.raises(MarketDataError) as captured:
        subject.fetch_snapshot(
            DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ"),
            release_state=ReleaseState.RELEASED,
        )

    assert captured.value.kind is ErrorKind.DEADLINE
    assert captured.value.public_payload()["code"] == "MARKET_DATA_DEADLINE_EXCEEDED"
    assert [name for name, _ in sdk.calls] == []


@dataclass(frozen=True)
class FakeHTTPConfig:
    max_retries: int = 3
    timeout: float = 30.0


def test_production_transport_overrides_sdk_retry_and_streaming_timeout() -> None:
    class HTTPClient:
        def __init__(self) -> None:
            self._config = FakeHTTPConfig()
            self.timeouts: list[float] = []

        def request(self, **kwargs: object) -> object:
            self.timeouts.append(float(kwargs["timeout"]))
            return {"ok": True}

    class Client:
        def __init__(self) -> None:
            self._http_client = HTTPClient()

    class SDK:
        def __init__(self) -> None:
            self.client = Client()

        def get_client(self) -> Client:
            return self.client

    sdk = SDK()
    policy = PandaData012TransportPolicy()

    policy.configure(sdk, OperationBudget())
    result = sdk.client._http_client.request(timeout=5000.0)

    assert result == {"ok": True}
    assert sdk.client._http_client._config.max_retries == 1
    assert sdk.client._http_client._config.timeout == 10.0
    assert sdk.client._http_client.timeouts == [10.0]


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        (100_003, ErrorKind.PARAMETER),
        (200_001, ErrorKind.AUTHENTICATION),
        (200_101, ErrorKind.PERMISSION),
        (400_002, ErrorKind.TRANSIENT),
        (600_001, ErrorKind.TRANSIENT),
    ],
)
def test_sdk_service_codes_map_to_stable_safe_errors(
    code: int,
    kind: ErrorKind,
) -> None:
    class ServiceError(Exception):
        def __init__(self) -> None:
            self.code = code
            super().__init__(
                "Bearer abcdefghijklmnop at https://private.example.test/data"
            )

    error = classify_upstream_error(
        ServiceError(),
        endpoint="get_stock_daily",
    )

    assert error.kind is kind
    assert "abcdefghijklmnop" not in error.internal_message
    assert "private.example.test" not in error.internal_message
    assert set(error.public_payload()) == {"code", "message", "trace_id"}
