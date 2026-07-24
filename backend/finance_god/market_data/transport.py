"""PandaData 0.0.12 transport policy with one bounded HTTP attempt."""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass, replace
from importlib import import_module
from typing import Any, Protocol, cast

from .errors import MarketDataConfigurationError


@dataclass(frozen=True)
class OperationBudget:
    sdk_attempts: int = 1
    request_timeout_seconds: float = 10.0
    operation_deadline_seconds: float = 12.0

    def __post_init__(self) -> None:
        if self.sdk_attempts != 1:
            raise ValueError("PandaData transport permits exactly one SDK attempt")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request timeout must be positive")
        if self.operation_deadline_seconds < self.request_timeout_seconds:
            raise ValueError("operation deadline cannot be shorter than HTTP timeout")


class PandaTransportPolicy(Protocol):
    def configure_auth(
        self,
        sdk: Any,
        budget: OperationBudget,
        *,
        timeout_seconds: float,
    ) -> None: ...

    def configure_client(
        self,
        sdk: Any,
        budget: OperationBudget,
        *,
        timeout_seconds: float,
    ) -> None: ...


class PandaData012TransportPolicy:
    """Fail closed unless the audited SDK transport can be bounded explicitly."""

    def configure_auth(
        self,
        sdk: Any,
        budget: OperationBudget,
        *,
        timeout_seconds: float,
    ) -> None:
        del sdk
        try:
            login_module = cast(Any, import_module("panda_data.readers.init_token"))
            http_module = cast(Any, import_module("panda_data.transport.http"))
            auth_module = cast(Any, import_module("panda_data.auth_manager"))
            original_config = getattr(
                login_module,
                "_finance_god_original_http_client_config",
                login_module.HTTPClientConfig,
            )
        except (AttributeError, ModuleNotFoundError) as error:
            raise MarketDataConfigurationError(
                "panda_data login transport layout drifted"
            ) from error

        def bounded_login_config(*args: object, **kwargs: object) -> object:
            kwargs["timeout"] = min(timeout_seconds, budget.request_timeout_seconds)
            kwargs["max_retries"] = budget.sdk_attempts
            return original_config(*args, **kwargs)

        login_module._finance_god_original_http_client_config = original_config
        login_module.HTTPClientConfig = bounded_login_config
        http_module._auth_re_login = lambda: False
        auth_module.re_login = lambda: False

    def configure_client(
        self,
        sdk: Any,
        budget: OperationBudget,
        *,
        timeout_seconds: float,
    ) -> None:
        try:
            client = sdk.get_client()
            http_client = client._http_client
            config = http_client._config
            original_request = getattr(
                http_client,
                "_finance_god_original_request",
                http_client.request,
            )
        except (AttributeError, TypeError) as error:
            raise MarketDataConfigurationError(
                "panda_data 0.0.12 transport layout drifted; timeout policy not installed"
            ) from error
        if not is_dataclass(config):
            raise MarketDataConfigurationError(
                "panda_data HTTP configuration is not the audited dataclass"
            )
        fields = getattr(config, "__dataclass_fields__", {})
        if "max_retries" not in fields or "timeout" not in fields:
            raise MarketDataConfigurationError(
                "panda_data HTTP configuration lacks retry/timeout controls"
            )
        http_client._config = replace(
            cast(Any, config),
            max_retries=budget.sdk_attempts,
            timeout=min(timeout_seconds, budget.request_timeout_seconds),
        )

        def bounded_request(*args: object, **kwargs: object) -> object:
            kwargs["timeout"] = min(timeout_seconds, budget.request_timeout_seconds)
            return original_request(*args, **kwargs)

        http_client._finance_god_original_request = original_request
        http_client.request = bounded_request


class InjectedSDKTransportPolicy:
    """Explicit test policy; production construction never selects this class."""

    def __init__(self) -> None:
        self.auth_configurations: list[tuple[OperationBudget, float]] = []
        self.client_configurations: list[tuple[OperationBudget, float]] = []

    def configure_auth(
        self,
        sdk: Any,
        budget: OperationBudget,
        *,
        timeout_seconds: float,
    ) -> None:
        del sdk
        self.auth_configurations.append((budget, timeout_seconds))

    def configure_client(
        self,
        sdk: Any,
        budget: OperationBudget,
        *,
        timeout_seconds: float,
    ) -> None:
        del sdk
        self.client_configurations.append((budget, timeout_seconds))
