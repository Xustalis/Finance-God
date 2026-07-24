"""PandaData 0.0.12 transport policy with one bounded HTTP attempt."""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass, replace
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
    def configure(self, sdk: Any, budget: OperationBudget) -> None: ...


class PandaData012TransportPolicy:
    """Fail closed unless the audited SDK transport can be bounded explicitly."""

    def configure(self, sdk: Any, budget: OperationBudget) -> None:
        try:
            client = sdk.get_client()
            http_client = client._http_client
            config = http_client._config
            original_request = http_client.request
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
            timeout=budget.request_timeout_seconds,
        )

        def bounded_request(*args: object, **kwargs: object) -> object:
            kwargs["timeout"] = budget.request_timeout_seconds
            return original_request(*args, **kwargs)

        http_client.request = bounded_request


class InjectedSDKTransportPolicy:
    """Explicit test policy; production construction never selects this class."""

    def __init__(self) -> None:
        self.configured_budgets: list[OperationBudget] = []

    def configure(self, sdk: Any, budget: OperationBudget) -> None:
        del sdk
        self.configured_budgets.append(budget)
