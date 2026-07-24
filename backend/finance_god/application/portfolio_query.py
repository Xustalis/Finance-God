"""Authoritative simulation portfolio read model.

This query service exposes the *facts* a portfolio view needs — quantity,
settled/available quantity, cost basis and realized profit and loss — derived
exclusively from the event-sourced ledger projections and recorded fills.

Market value and unrealized profit and loss are deliberately **not** computed
here: they depend on live PandaData quotes, which are polled by the browser and
must never be mixed into simulated business facts.  The frontend multiplies the
authoritative ``quantity`` by the polled quote to obtain market value, and
subtracts ``cost_basis_rmb`` to obtain unrealized profit and loss.

Cost accounting mirrors the ledger projection (``_project_trade``): a buy adds
its gross RMB notional to the position cost basis (entry commissions are
expensed to cash, not capitalized), and a sell removes cost using the average
cost method.  Realized profit and loss for a sell is therefore the net proceeds
(``rmb_gross - rmb_fee``) minus the average cost of the quantity sold.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from finance_god.domain import Fill

ZERO = Decimal("0")
CENTS = Decimal("0.01")
PRICE_QUANTUM = Decimal("0.00000001")


class Clock(Protocol):
    def now(self) -> datetime: ...


class PortfolioUnitOfWork(Protocol):
    accounts: object
    position_projections: object
    fills: object

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None: ...


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PortfolioPosition(StrictModel):
    instrument_id: str = Field(min_length=1, max_length=160)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    quantity: Decimal = Field(ge=0)
    settled_quantity: Decimal = Field(ge=0)
    frozen_quantity: Decimal = Field(ge=0)
    available_quantity: Decimal = Field(ge=0)
    cost_basis_rmb: Decimal = Field(ge=0)
    average_cost_rmb: Decimal | None = Field(default=None, ge=0)
    realized_pnl_rmb: Decimal
    revision: int = Field(ge=0)


class PortfolioView(StrictModel):
    account_id: str = Field(min_length=1, max_length=160)
    owner_id: str = Field(min_length=1, max_length=160)
    as_of: AwareDatetime
    rule_version: str = Field(min_length=1, max_length=80)
    positions: tuple[PortfolioPosition, ...] = ()
    realized_pnl_rmb: Decimal = ZERO


class PortfolioQueryService:
    """Read positions and realized P&L for an owner's current account."""

    def __init__(
        self,
        *,
        uow_factory: object,
        clock: Clock,
        rule_version: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._rule_version = rule_version

    async def positions(self, *, owner_id: str) -> PortfolioView:
        async with self._uow_factory() as uow:  # type: ignore[operator]
            account = await uow.accounts.get_current(owner_id)
            if account is None:
                raise LookupError("simulation account not found")
            projections = await uow.position_projections.list(account.account_id)
            fills = await uow.fills.list(account.account_id)
        realized = _realized_by_instrument(fills)
        rows = tuple(
            _to_row(projection, realized.get(projection.instrument_id, ZERO))
            for projection in projections
            if projection.long_quantity > 0 or projection.short_quantity > 0
        )
        return PortfolioView(
            account_id=account.account_id,
            owner_id=account.owner_user_id,
            as_of=self._clock.now(),
            rule_version=self._rule_version,
            positions=rows,
            realized_pnl_rmb=sum(realized.values(), ZERO).quantize(CENTS),
        )


def _to_row(projection: object, realized: Decimal) -> PortfolioPosition:
    quantity: Decimal = projection.long_quantity  # type: ignore[attr-defined]
    settled: Decimal = projection.settled_quantity  # type: ignore[attr-defined]
    frozen: Decimal = projection.frozen_quantity  # type: ignore[attr-defined]
    cost_basis: Decimal = projection.long_cost_rmb  # type: ignore[attr-defined]
    average = (
        (cost_basis / quantity).quantize(PRICE_QUANTUM) if quantity > 0 else None
    )
    return PortfolioPosition(
        instrument_id=projection.instrument_id,  # type: ignore[attr-defined]
        currency=projection.currency,  # type: ignore[attr-defined]
        quantity=quantity,
        settled_quantity=settled,
        frozen_quantity=frozen,
        available_quantity=settled - frozen,
        cost_basis_rmb=cost_basis,
        average_cost_rmb=average,
        realized_pnl_rmb=realized.quantize(CENTS),
        revision=projection.revision,  # type: ignore[attr-defined]
    )


def _realized_by_instrument(fills: tuple[Fill, ...]) -> dict[str, Decimal]:
    """Replay fills per instrument (average cost) to derive realized P&L.

    Only exchange buy/sell transactions occur in the simulation ledger; other
    transaction types are ignored so this never fabricates realized figures for
    flows it cannot account for.
    """
    ordered = sorted(fills, key=lambda fill: fill.occurred_at)
    cost_pool: dict[str, Decimal] = {}
    quantity: dict[str, Decimal] = {}
    realized: dict[str, Decimal] = {}
    for fill in ordered:
        instrument = fill.instrument_id
        if fill.transaction_type == "buy":
            cost_pool[instrument] = cost_pool.get(instrument, ZERO) + fill.rmb_gross
            quantity[instrument] = quantity.get(instrument, ZERO) + fill.quantity
        elif fill.transaction_type == "sell":
            held = quantity.get(instrument, ZERO)
            pool = cost_pool.get(instrument, ZERO)
            proceeds = fill.rmb_gross - fill.rmb_fee
            if held > 0:
                unit_cost = pool / held
                cost_removed = unit_cost * fill.quantity
                cost_pool[instrument] = pool - cost_removed
                quantity[instrument] = held - fill.quantity
            else:
                cost_removed = ZERO
            realized[instrument] = (
                realized.get(instrument, ZERO) + proceeds - cost_removed
            )
    return realized
