"""Strongly typed deterministic node results consumed by the executor."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from finance_god.domain.models import (
    RiskCheckResult,
    VersionReference,
)

from .workflow_registry import FrozenModel

SimulationServiceId = Literal[
    "simulation.order_accept",
    "simulation.market_validate",
    "simulation.match",
    "simulation.ledger_update",
]


class OrderRiskCheckNodeResult(FrozenModel):
    result_kind: Literal["order_risk_check"] = "order_risk_check"
    owner_id: str = Field(min_length=1, max_length=160)
    order_reference: VersionReference
    risk_check_reference: VersionReference
    risk_check: RiskCheckResult

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        if self.risk_check.order_version != self.order_reference:
            raise ValueError("risk check is not bound to the reviewed order version")
        expected = VersionReference(
            object_type="RiskCheckResult",
            object_id=self.risk_check.risk_check_id,
            version=str(self.risk_check.revision),
        )
        if self.risk_check_reference != expected:
            raise ValueError("risk check reference does not identify the typed result")
        if self.order_reference not in self.risk_check.input_versions:
            raise ValueError("risk check inputs omit the reviewed order version")
        return self


class SimulationFactNodeResult(FrozenModel):
    result_kind: Literal["simulation_fact"] = "simulation_fact"
    service_id: SimulationServiceId
    owner_id: str = Field(min_length=1, max_length=160)
    order_reference: VersionReference
    accepted: bool
    result_reference: VersionReference
    fact_references: tuple[VersionReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_fact_types(self) -> Self:
        expected_result_type, expected_fact_type = {
            "simulation.order_accept": (
                "SimulationOrderAcceptance",
                "SimulationOrder",
            ),
            "simulation.market_validate": (
                "SimulationMarketValidation",
                "MarketValidation",
            ),
            "simulation.match": ("SimulationMatch", "SimulationFill"),
            "simulation.ledger_update": (
                "SimulationLedgerUpdate",
                "LedgerEntry",
            ),
        }[self.service_id]
        if self.result_reference.object_type != expected_result_type:
            raise ValueError(
                f"{self.service_id} result reference has the wrong artifact type"
            )
        if any(
            reference.object_type != expected_fact_type
            for reference in self.fact_references
        ):
            raise ValueError(
                f"{self.service_id} fact reference has the wrong artifact type"
            )
        return self


DeterministicNodeResult = OrderRiskCheckNodeResult | SimulationFactNodeResult

__all__ = [
    "DeterministicNodeResult",
    "OrderRiskCheckNodeResult",
    "SimulationFactNodeResult",
]
