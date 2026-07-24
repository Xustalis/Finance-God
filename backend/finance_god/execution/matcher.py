from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from finance_god.domain import OrderDraft, OrderSide, OrderType, VersionReference
from finance_god.domain.simulation_rules import SIMULATION_RULE_VERSION

from .contracts import (
    ExecutionFailure,
    ExecutionFailureCode,
    SimulationBar,
)


@dataclass(frozen=True, slots=True)
class SimulationRuleSet:
    version: str = SIMULATION_RULE_VERSION
    model_version: str = "daily-bar-matcher-v1"
    slippage_bps: Decimal = Decimal("5")
    volume_participation: Decimal = Decimal("0.10")
    lot_size: Decimal = Decimal("1")
    fee_bps: Decimal = Decimal("3")

    def __post_init__(self) -> None:
        if self.version != SIMULATION_RULE_VERSION:
            raise ValueError("unsupported simulation rule version")
        if not Decimal("0") < self.volume_participation <= Decimal("1"):
            raise ValueError("volume participation must be in (0, 1]")
        if self.lot_size <= 0:
            raise ValueError("lot size must be positive")


@dataclass(frozen=True, slots=True)
class MatchResult:
    fill_quantity: Decimal
    fill_price: Decimal | None
    fee: Decimal
    slippage_bps: Decimal
    triggered: bool
    market_evidence: VersionReference
    model_version: str
    rule_version: str


class DeterministicMatcher:
    def __init__(self, rules: SimulationRuleSet | None = None) -> None:
        self._rules = rules or SimulationRuleSet()

    def match(
        self,
        draft: OrderDraft,
        bar: SimulationBar,
        *,
        remaining_quantity: Decimal,
    ) -> MatchResult:
        if bar.instrument_id != draft.instrument_id:
            raise ExecutionFailure(
                ExecutionFailureCode.MARKET_DATA_CONFLICT,
                "bar instrument does not match order draft",
            )
        if bar.conflict:
            raise ExecutionFailure(
                ExecutionFailureCode.MARKET_DATA_CONFLICT,
                "PandaData bar has unresolved conflicts",
            )
        if bar.stale:
            raise ExecutionFailure(
                ExecutionFailureCode.MARKET_DATA_STALE,
                "PandaData bar is stale",
            )
        if draft.order_type is OrderType.FUND:
            raise ExecutionFailure(
                ExecutionFailureCode.UNSUPPORTED_OPERATION,
                "fund orders do not use exchange matcher",
            )
        if remaining_quantity <= 0:
            raise ValueError("remaining quantity must be positive")

        triggered = self._triggered(draft, bar)
        if not triggered:
            return MatchResult(
                fill_quantity=Decimal("0"),
                fill_price=None,
                fee=Decimal("0"),
                slippage_bps=self._rules.slippage_bps,
                triggered=False,
                market_evidence=bar.evidence,
                model_version=self._rules.model_version,
                rule_version=self._rules.version,
            )
        capacity = self._lot_floor(bar.volume * self._rules.volume_participation)
        fill_quantity = min(remaining_quantity, capacity)
        if fill_quantity <= 0:
            return MatchResult(
                fill_quantity=Decimal("0"),
                fill_price=None,
                fee=Decimal("0"),
                slippage_bps=self._rules.slippage_bps,
                triggered=True,
                market_evidence=bar.evidence,
                model_version=self._rules.model_version,
                rule_version=self._rules.version,
            )
        price = self._price(draft, bar)
        fee = (
            price * fill_quantity * self._rules.fee_bps / Decimal("10000")
        ).quantize(Decimal("0.00000001"))
        return MatchResult(
            fill_quantity=fill_quantity,
            fill_price=price,
            fee=fee,
            slippage_bps=self._rules.slippage_bps,
            triggered=True,
            market_evidence=bar.evidence,
            model_version=self._rules.model_version,
            rule_version=self._rules.version,
        )

    def _triggered(self, draft: OrderDraft, bar: SimulationBar) -> bool:
        if draft.order_type is OrderType.MARKET:
            return True
        assert draft.limit_price is not None
        if draft.side in {OrderSide.BUY, OrderSide.COVER}:
            return bar.low <= draft.limit_price
        return bar.high >= draft.limit_price

    def _price(self, draft: OrderDraft, bar: SimulationBar) -> Decimal:
        if draft.order_type is OrderType.LIMIT:
            assert draft.limit_price is not None
            return draft.limit_price
        direction = (
            Decimal("1")
            if draft.side in {OrderSide.BUY, OrderSide.COVER}
            else Decimal("-1")
        )
        return (
            bar.open
            * (Decimal("1") + direction * self._rules.slippage_bps / Decimal("10000"))
        ).quantize(Decimal("0.00000001"))

    def _lot_floor(self, quantity: Decimal) -> Decimal:
        lots = (quantity / self._rules.lot_size).to_integral_value(
            rounding=ROUND_DOWN
        )
        return lots * self._rules.lot_size
