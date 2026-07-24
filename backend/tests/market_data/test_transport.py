from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Any

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

    assert policy.auth_configurations == [(OperationBudget(), 10.0)]
    assert policy.client_configurations == [
        (OperationBudget(), 10.0),
        (OperationBudget(), 10.0),
    ]
    assert [name for name, _ in sdk.calls].count("init_token") == 1


def test_transport_policy_is_installed_before_authentication() -> None:
    events: list[str] = []

    class OrderedSDK(FakeSDK):
        def init_token(self, **kwargs: object) -> str:
            events.append("authenticate")
            return super().init_token(**kwargs)

    class OrderedPolicy(InjectedSDKTransportPolicy):
        def configure_auth(
            self,
            sdk: object,
            budget: OperationBudget,
            *,
            timeout_seconds: float,
        ) -> None:
            events.append("configure_auth_transport")
            super().configure_auth(
                sdk,
                budget,
                timeout_seconds=timeout_seconds,
            )

        def configure_client(
            self,
            sdk: object,
            budget: OperationBudget,
            *,
            timeout_seconds: float,
        ) -> None:
            events.append("configure_client_transport")
            super().configure_client(
                sdk,
                budget,
                timeout_seconds=timeout_seconds,
            )

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

    assert events == [
        "configure_auth_transport",
        "authenticate",
        "configure_client_transport",
    ]


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
            timeout = kwargs["timeout"]
            assert isinstance(timeout, (int, float))
            self.timeouts.append(float(timeout))
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

    policy.configure_client(
        sdk,
        OperationBudget(),
        timeout_seconds=2.0,
    )
    result = sdk.client._http_client.request(timeout=5000.0)

    assert result == {"ok": True}
    assert sdk.client._http_client._config.max_retries == 1
    assert sdk.client._http_client._config.timeout == 2.0
    assert sdk.client._http_client.timeouts == [2.0]


def test_authentication_is_interrupted_at_shared_absolute_deadline() -> None:
    class SlowAuthSDK(FakeSDK):
        def init_token(self, **kwargs: object) -> str:
            self.calls.append(("init_token", kwargs))
            sleep(0.11)
            return "late-token"

    sdk = SlowAuthSDK()
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    subject = PandaDataAdapter(
        sdk=sdk,
        sdk_version=EXPECTED_SDK_VERSION,
        credentials=PandaCredentials("user", "password"),
        transport_policy=InjectedSDKTransportPolicy(),
        catalog=PandaDataCapabilityCatalog.for_injected_test_sdk(sdk),
        now=lambda: NOW,
        operation_budget=OperationBudget(
            request_timeout_seconds=0.06,
            operation_deadline_seconds=0.06,
        ),
    )

    started = monotonic()
    with pytest.raises(MarketDataError) as captured:
        subject.fetch_snapshot(
            DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ"),
            release_state=ReleaseState.RELEASED,
        )
    elapsed = monotonic() - started

    assert captured.value.kind is ErrorKind.DEADLINE
    assert elapsed < 0.1
    assert [name for name, _ in sdk.calls] == ["init_token"]


def test_request_uses_only_deadline_remaining_after_authentication() -> None:
    class SlowCombinedSDK(FakeSDK):
        def init_token(self, **kwargs: object) -> str:
            self.calls.append(("init_token", kwargs))
            sleep(0.04)
            return "token"

        def __getattr__(self, name: str) -> Any:
            endpoint = super().__getattr__(name)

            def slow_endpoint(**kwargs: object) -> object:
                sleep(0.04)
                return endpoint(**kwargs)

            return slow_endpoint

    sdk = SlowCombinedSDK()
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    policy = InjectedSDKTransportPolicy()
    subject = PandaDataAdapter(
        sdk=sdk,
        sdk_version=EXPECTED_SDK_VERSION,
        credentials=PandaCredentials("user", "password"),
        transport_policy=policy,
        catalog=PandaDataCapabilityCatalog.for_injected_test_sdk(sdk),
        now=lambda: NOW,
        operation_budget=OperationBudget(
            request_timeout_seconds=0.06,
            operation_deadline_seconds=0.06,
        ),
    )

    started = monotonic()
    with pytest.raises(MarketDataError) as captured:
        subject.fetch_snapshot(
            DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ"),
            release_state=ReleaseState.RELEASED,
        )
    elapsed = monotonic() - started

    assert captured.value.kind is ErrorKind.DEADLINE
    assert elapsed < 0.09
    assert policy.client_configurations
    assert 0 < policy.client_configurations[0][1] < 0.04


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
