from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from finance_god.application.portfolio_query import PortfolioQueryService
from finance_god.domain.accounts import AccountStatus, SimulationAccount
from finance_god.domain.ledger import PositionProjection

NOW = datetime(2026, 7, 24, 2, tzinfo=UTC)


@dataclass(frozen=True)
class FakeFill:
    instrument_id: str
    transaction_type: str
    quantity: Decimal
    rmb_gross: Decimal
    rmb_fee: Decimal
    occurred_at: datetime


class FakeAccounts:
    def __init__(self, account: SimulationAccount | None) -> None:
        self._account = account

    async def get_current(self, owner_id: str) -> SimulationAccount | None:
        del owner_id
        return self._account


class FakePositions:
    def __init__(self, projections: tuple[PositionProjection, ...]) -> None:
        self._projections = projections

    async def list(self, account_id: str) -> tuple[PositionProjection, ...]:
        del account_id
        return self._projections


class FakeFills:
    def __init__(self, fills: tuple[FakeFill, ...]) -> None:
        self._fills = fills

    async def list(self, account_id: str) -> tuple[FakeFill, ...]:
        del account_id
        return self._fills


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        account: SimulationAccount | None,
        projections: tuple[PositionProjection, ...],
        fills: tuple[FakeFill, ...],
    ) -> None:
        self.accounts = FakeAccounts(account)
        self.position_projections = FakePositions(projections)
        self.fills = FakeFills(fills)

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args


class Clock:
    def now(self) -> datetime:
        return NOW


def account() -> SimulationAccount:
    return SimulationAccount(
        account_id="account-1",
        owner_user_id="owner-1",
        initial_cash_rmb=Decimal("1000000"),
        status=AccountStatus.ACTIVE,
        current=True,
        revision=1,
        created_at=NOW,
    )


class PortfolioQueryTest(unittest.IsolatedAsyncioTestCase):
    def _service(
        self,
        *,
        projections: tuple[PositionProjection, ...],
        fills: tuple[FakeFill, ...],
        acct: SimulationAccount | None = None,
    ) -> PortfolioQueryService:
        uow = FakeUnitOfWork(
            account=acct if acct is not None else account(),
            projections=projections,
            fills=fills,
        )
        return PortfolioQueryService(
            uow_factory=lambda: uow,
            clock=Clock(),
            rule_version="simulation-rules-v1",
        )

    async def test_missing_account_raises_lookup(self) -> None:
        service = PortfolioQueryService(
            uow_factory=lambda: FakeUnitOfWork(
                account=None, projections=(), fills=()
            ),
            clock=Clock(),
            rule_version="simulation-rules-v1",
        )
        with self.assertRaises(LookupError):
            await service.positions(owner_id="owner-1")

    async def test_positions_expose_cost_and_average(self) -> None:
        projection = PositionProjection(
            account_id="account-1",
            instrument_id="600519.SSE",
            currency="CNY",
            long_quantity=Decimal("100"),
            settled_quantity=Decimal("100"),
            frozen_quantity=Decimal("20"),
            long_cost_native=Decimal("100000"),
            long_cost_rmb=Decimal("100000"),
            revision=3,
        )
        service = self._service(projections=(projection,), fills=())
        view = await service.positions(owner_id="owner-1")

        self.assertEqual(view.account_id, "account-1")
        self.assertEqual(len(view.positions), 1)
        row = view.positions[0]
        self.assertEqual(row.quantity, Decimal("100"))
        self.assertEqual(row.available_quantity, Decimal("80"))
        self.assertEqual(row.cost_basis_rmb, Decimal("100000"))
        self.assertEqual(row.average_cost_rmb, Decimal("1000.00000000"))
        self.assertEqual(row.realized_pnl_rmb, Decimal("0.00"))

    async def test_realized_pnl_uses_average_cost(self) -> None:
        # Buy 100 @ 1000 (gross 100000), sell 40 @ 1100 (gross 44000, fee 88).
        fills = (
            FakeFill(
                instrument_id="600519.SSE",
                transaction_type="buy",
                quantity=Decimal("100"),
                rmb_gross=Decimal("100000"),
                rmb_fee=Decimal("200"),
                occurred_at=NOW,
            ),
            FakeFill(
                instrument_id="600519.SSE",
                transaction_type="sell",
                quantity=Decimal("40"),
                rmb_gross=Decimal("44000"),
                rmb_fee=Decimal("88"),
                occurred_at=NOW.replace(hour=3),
            ),
        )
        projection = PositionProjection(
            account_id="account-1",
            instrument_id="600519.SSE",
            currency="CNY",
            long_quantity=Decimal("60"),
            settled_quantity=Decimal("60"),
            frozen_quantity=Decimal("0"),
            long_cost_native=Decimal("60000"),
            long_cost_rmb=Decimal("60000"),
            revision=5,
        )
        service = self._service(projections=(projection,), fills=fills)
        view = await service.positions(owner_id="owner-1")

        row = view.positions[0]
        # proceeds 44000-88=43912; avg cost 1000 * 40 = 40000; realized 3912.
        self.assertEqual(row.realized_pnl_rmb, Decimal("3912.00"))
        self.assertEqual(view.realized_pnl_rmb, Decimal("3912.00"))

    async def test_flat_positions_are_excluded(self) -> None:
        projection = PositionProjection(
            account_id="account-1",
            instrument_id="600519.SSE",
            currency="CNY",
            long_quantity=Decimal("0"),
            settled_quantity=Decimal("0"),
            frozen_quantity=Decimal("0"),
            revision=9,
        )
        service = self._service(projections=(projection,), fills=())
        view = await service.positions(owner_id="owner-1")
        self.assertEqual(view.positions, ())


if __name__ == "__main__":
    unittest.main()
