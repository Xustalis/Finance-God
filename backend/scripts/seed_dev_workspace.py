"""Seed a small, internally consistent workspace for the development test user."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_factory
from app.models.user import User
from finance_god.api.simulation import SimulationAccountCreate
from finance_god.application.ledger_service import SimulationLedgerService
from finance_god.application.simulation_clock import SimulationClockService
from finance_god.domain import OrderSide, VersionReference, WatchlistGroup
from finance_god.domain.simulation_rules import SIMULATION_RULE_VERSION
from finance_god.execution import DeterministicMatcher, SimulationExecutionService
from finance_god.infrastructure.persistence import SqlAlchemyUnitOfWork
from finance_god.infrastructure.persistence.simulation_uow import SimulationUnitOfWork
from finance_god.infrastructure.persistence.workspace_uow import WorkspaceUnitOfWork
from finance_god.infrastructure.simulation_wiring import (
    AutoPassManualReview,
    LedgerAccountOwnership,
    LedgerFillAdapter,
    SimulationAccountApplicationImpl,
    SimulationRiskAdapter,
    SimulationSubmissionTransport,
    SystemClock,
    UuidIdGenerator,
)
from finance_god.infrastructure.trade_plan_port import PersistentTradePlanPort
from finance_god.trade_review import TradeReviewService

SessionFactory = Callable[[], AsyncSession]
INITIAL_CASH = Decimal("500000")
SEED_SOURCE = VersionReference(
    object_type="development_seed",
    object_id="workspace",
    version="1",
)


class _Rules:
    simulation_rule_version = SIMULATION_RULE_VERSION


class _UnusedBars:
    async def next_bar(self, *_args: object, **_kwargs: object) -> None:
        return None


def _request_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def seed_dev_workspace(
    session_factory: SessionFactory,
    *,
    app_env: str,
    email: str,
) -> dict[str, int | str]:
    if app_env != "development":
        raise RuntimeError("Development workspace seeding requires APP_ENV=development")

    normalized_email = email.strip().lower()
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        raise LookupError(
            f"development test user {normalized_email} not found; run make seed-dev-user first"
        )
    owner_id = str(user.id)

    clock = SystemClock()
    ids = UuidIdGenerator()

    def ledger_uow() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    ledger = SimulationLedgerService(
        uow_factory=ledger_uow,
        clock=clock,
        ids=ids,
        rules=_Rules(),
    )
    simulation_clock = SimulationClockService(session_factory)
    accounts = _account_application(
        ledger=ledger,
        ledger_uow=ledger_uow,
        session_factory=session_factory,
        clock=clock,
        ids=ids,
        simulation_clock=simulation_clock,
    )
    account = await accounts.current(owner_id=owner_id)
    if account is None:
        account = await accounts.create(
            owner_id=owner_id,
            request=SimulationAccountCreate(
                initial_cash_rmb=INITIAL_CASH,
                simulation_start_at=datetime(2026, 7, 20, 1, 31, tzinfo=UTC),
            ),
            idempotency_key="dev-workspace-account-v1",
            request_hash=_request_hash("dev-workspace-account-v1"),
        )

    execution = _execution_service(
        ledger=ledger,
        ledger_uow=ledger_uow,
        session_factory=session_factory,
        clock=clock,
        ids=ids,
    )
    review = TradeReviewService(session_factory)
    orders = (
        (
            "closed-buy",
            "000001.SZ",
            OrderSide.BUY,
            Decimal("1000"),
            Decimal("10.20"),
            Decimal("1000"),
        ),
        (
            "closed-sell",
            "000001.SZ",
            OrderSide.SELL,
            Decimal("1000"),
            Decimal("11.05"),
            Decimal("0"),
        ),
        (
            "open-buy",
            "600519.SH",
            OrderSide.BUY,
            Decimal("10"),
            Decimal("1418.60"),
            Decimal("10"),
        ),
    )
    seeded_orders = 0
    for key, instrument_id, side, quantity, price, position_after in orders:
        evidence = VersionReference(
            object_type="development_seed_trade",
            object_id=instrument_id,
            version=f"workspace-v1:{key}",
        )
        order = await execution.execute_immediate_market_order(
            owner_id=owner_id,
            account_id=account.account_id,
            instrument_id=instrument_id,
            side=side,
            quantity=quantity,
            trusted_price=price,
            market_evidence=evidence,
            idempotency_key=f"dev-workspace-{key}-v1",
            request_hash=_request_hash(f"dev-workspace-{key}-v1"),
        )
        await review.record_filled_order(
            owner_id=owner_id,
            account_id=account.account_id,
            order=order,
            market_evidence=evidence.model_dump(mode="json"),
            position_quantity_after=position_after,
            profile_version=None,
        )
        seeded_orders += 1

    seeded_groups, seeded_instruments = await _seed_watchlists(
        session_factory,
        owner_id=owner_id,
    )
    return {
        "owner_id": owner_id,
        "account_id": account.account_id,
        "orders": seeded_orders,
        "watchlist_groups": seeded_groups,
        "watchlist_instruments": seeded_instruments,
    }


def _account_application(
    *,
    ledger: SimulationLedgerService,
    ledger_uow: Callable[[], SqlAlchemyUnitOfWork],
    session_factory: SessionFactory,
    clock: SystemClock,
    ids: UuidIdGenerator,
    simulation_clock: SimulationClockService,
) -> SimulationAccountApplicationImpl:
    return SimulationAccountApplicationImpl(
        ledger,
        ledger_uow,
        clock,
        ids,
        simulation_clock,
    )


def _execution_service(
    *,
    ledger: SimulationLedgerService,
    ledger_uow: Callable[[], SqlAlchemyUnitOfWork],
    session_factory: SessionFactory,
    clock: SystemClock,
    ids: UuidIdGenerator,
) -> SimulationExecutionService:
    return SimulationExecutionService(
        uow_factory=lambda: SimulationUnitOfWork(session_factory),
        accounts=LedgerAccountOwnership(ledger_uow),
        plans=PersistentTradePlanPort(session_factory, clock),
        manual_review=AutoPassManualReview(),
        risk=SimulationRiskAdapter(clock, ids),
        transport=SimulationSubmissionTransport(),
        bars=_UnusedBars(),
        ledger=LedgerFillAdapter(ledger, clock, ids),
        matcher=DeterministicMatcher(),
        clock=clock,
        ids=ids,
    )


async def _seed_watchlists(
    session_factory: SessionFactory,
    *,
    owner_id: str,
) -> tuple[int, int]:
    definitions = (
        (
            "dev-watchlist-core-v1",
            "重点跟踪",
            "近期持续观察的核心标的",
            ("600519.SH", "000001.SZ"),
        ),
        (
            "dev-watchlist-valuation-v1",
            "等待估值",
            "等待价格与基本面条件改善",
            ("000333.SZ",),
        ),
    )
    created_groups = 0
    created_instruments = 0
    async with WorkspaceUnitOfWork(session_factory) as uow:
        for group_id, name, description, instruments in definitions:
            group = await uow.watchlists.get_group(owner_id, group_id)
            if group is None:
                now = datetime.now(UTC)
                group = await uow.watchlists.create_group(
                    WatchlistGroup(
                        group_id=group_id,
                        owner_user_id=owner_id,
                        name=name,
                        description=description,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                created_groups += 1
            existing = {
                item.instrument_id
                for item in await uow.watchlists.list_instruments(owner_id, group_id)
            }
            for instrument_id in instruments:
                if instrument_id in existing:
                    continue
                await uow.watchlists.add_instrument(
                    owner_user_id=owner_id,
                    group_id=group.group_id,
                    instrument_id=instrument_id,
                    added_by=owner_id,
                )
                created_instruments += 1
        await uow.commit()
    return created_groups, created_instruments


async def _run() -> None:
    result = await seed_dev_workspace(
        async_session_factory,
        app_env=settings.app_env,
        email=settings.dev_test_user_email,
    )
    print(
        "Seeded development workspace "
        f"for {settings.dev_test_user_email}: "
        f"account={result['account_id']}, orders={result['orders']}, "
        f"groups+={result['watchlist_groups']}, "
        f"instruments+={result['watchlist_instruments']}"
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
