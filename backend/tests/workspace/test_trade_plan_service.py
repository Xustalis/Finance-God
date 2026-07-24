from __future__ import annotations

import asyncio
import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from finance_god.application.candidate_service import Candidate, CandidateResponse
from finance_god.application.portfolio_query import PortfolioPosition, PortfolioView
from finance_god.application.trade_plan_service import (
    TradePlanActionRevision,
    TradePlanService,
)
from finance_god.domain import (
    AuditReference,
    ConcurrentCommandConflict,
    OrderDraft,
    OrderDraftStatus,
    VersionReference,
)
from finance_god.execution import StoredDraft
from finance_god.infrastructure.persistence.models import Base
from finance_god.infrastructure.trade_plan_port import PersistentTradePlanPort
from finance_god.market_data.service import MarketQuote, QuoteBatch

NOW = datetime(2026, 7, 24, 8, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        return self.value

    def advance(self) -> None:
        self.value += timedelta(seconds=1)


class _IDs:
    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._counter)}"


class _Candidates:
    async def candidates(
        self, *, owner_id: str, now: datetime, ignored=None
    ) -> CandidateResponse:
        del owner_id, ignored
        return CandidateResponse(
            generated_at=now,
            rule_version="simulation-rules-v1",
            purpose_summary="test",
            candidates=(
                Candidate(
                    instrument_id="600519.SH",
                    symbol="600519.SH",
                    name="贵州茅台",
                    asset_type="stock",
                    market="CN",
                    currency="CNY",
                    direction="equities",
                    direction_label="权益股票",
                    purpose="补充权益方向候选。",
                    dimensions=(),
                    tradable=True,
                    as_of=NOW.isoformat(),
                    provider="PandaData",
                ),
            ),
        )


class _Portfolio:
    async def positions(self, *, owner_id: str) -> PortfolioView:
        return PortfolioView(
            account_id="account-1",
            owner_id=owner_id,
            as_of=NOW,
            rule_version="simulation-rules-v1",
            positions=(
                PortfolioPosition(
                    instrument_id="600519.SH",
                    currency="CNY",
                    quantity=Decimal("100"),
                    settled_quantity=Decimal("100"),
                    frozen_quantity=Decimal("0"),
                    available_quantity=Decimal("100"),
                    cost_basis_rmb=Decimal("100000"),
                    average_cost_rmb=Decimal("1000"),
                    realized_pnl_rmb=Decimal("0"),
                    revision=1,
                ),
            ),
        )


class _Drafts:
    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.calls: list[dict[str, object]] = []

    async def create_order_draft(self, **kwargs: object) -> StoredDraft:
        self.calls.append(kwargs)
        draft = OrderDraft(
            draft_id=f"draft-{len(self.calls)}",
            revision=1,
            status=OrderDraftStatus.DRAFT,
            account_id=str(kwargs["account_id"]),
            instrument_id=str(kwargs["instrument_id"]),
            side=kwargs["side"],
            order_type=kwargs["order_type"],
            quantity=kwargs["quantity"],
            amount=kwargs["amount"],
            limit_price=kwargs["limit_price"],
            time_in_force=kwargs["time_in_force"],
            fund_rule_version=None,
            valid_until=kwargs["valid_until"],
            input_versions=kwargs["input_versions"],
            audit_reference=AuditReference(
                audit_id=f"draft-audit-{len(self.calls)}",
                actor_id=str(kwargs["owner_id"]),
                recorded_at=self.clock.now(),
            ),
        )
        return StoredDraft(
            owner_id=str(kwargs["owner_id"]),
            mode=kwargs["mode"],
            draft=draft,
            plan_reference=kwargs["plan_reference"],
            reference_price=kwargs["reference_price"],
        )


def _quote(symbol: str = "600519.SH") -> MarketQuote:
    return MarketQuote(
        symbol=symbol,
        name="贵州茅台",
        asset_type="stock",
        market="CN",
        currency="CNY",
        last=Decimal("1500"),
        open=Decimal("1490"),
        high=Decimal("1510"),
        low=Decimal("1480"),
        previous_close=Decimal("1495"),
        change=Decimal("5"),
        change_percent=Decimal("0.33"),
        volume=Decimal("1000"),
        amount=Decimal("1500000"),
        provider_time=NOW.isoformat(),
        retrieved_at=NOW,
        frequency="snapshot",
        freshness="current",
        market_status="in_session",
        source_endpoint="stock.market",
        capability_version="v1",
        instrument_master_identity=symbol,
        instrument_master_version="v1",
    )


async def _quotes(symbols: list[str]) -> QuoteBatch:
    return QuoteBatch(
        requested_at=NOW,
        cache_hit=False,
        quotes=tuple(_quote(symbol) for symbol in symbols),
        errors={},
    )


async def _service(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'plans.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    clock = _Clock()
    drafts = _Drafts(clock)
    service = TradePlanService(
        session_factory=factory,
        clock=clock,
        ids=_IDs(),
        candidates=_Candidates(),
        portfolio=_Portfolio(),
        quotes_provider=_quotes,
        drafts=drafts,
    )
    return engine, factory, clock, drafts, service


def test_candidate_plan_versions_confirm_and_generate_planned_draft(tmp_path) -> None:
    async def run() -> None:
        engine, factory, clock, drafts, service = await _service(tmp_path)
        try:
            created = await service.create_from_candidate(
                owner_id="owner-1",
                instrument_id="600519.SH",
                idempotency_key="candidate-plan-1",
            )
            assert created.object.revision == 1
            assert created.object.status.value == "pending_review"
            assert not next(
                item
                for item in created.capabilities
                if item.action == "confirm_and_generate"
            ).enabled

            clock.advance()
            revised = await service.revise(
                owner_id="owner-1",
                plan_id=created.object.plan_id,
                expected_revision=1,
                actions=(
                    TradePlanActionRevision(
                        action_id=created.object.actions[0].action_id,
                        quantity=Decimal("10"),
                    ),
                ),
            )
            assert revised.object.revision == 2
            assert revised.object.estimated_fee_rmb == Decimal("4.50")

            clock.advance()
            confirmed = await service.confirm_and_generate(
                owner_id="owner-1",
                plan_id=created.object.plan_id,
                expected_revision=2,
                idempotency_key="confirm-1",
            )
            assert confirmed.object.revision == 3
            assert confirmed.object.status.value == "confirmed"
            assert len(confirmed.draft_links) == 1
            assert len(drafts.calls) == 1
            reference = drafts.calls[0]["plan_reference"]
            assert reference == VersionReference(
                object_type="trade_plan",
                object_id=created.object.plan_id,
                version="3",
            )

            port = PersistentTradePlanPort(factory, clock)
            await port.require_executable(reference)
            with pytest.raises(ValueError, match="not confirmed"):
                await port.require_executable(
                    VersionReference(
                        object_type="trade_plan",
                        object_id=created.object.plan_id,
                        version="2",
                    )
                )

            retried = await service.confirm_and_generate(
                owner_id="owner-1",
                plan_id=created.object.plan_id,
                expected_revision=3,
                idempotency_key="confirm-1",
            )
            assert len(retried.draft_links) == 1
            assert len(drafts.calls) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_portfolio_deviation_creates_server_calculated_sell_action(tmp_path) -> None:
    async def run() -> None:
        engine, _factory, _clock, _drafts, service = await _service(tmp_path)
        try:
            created = await service.create_from_portfolio_deviation(
                owner_id="owner-1",
                idempotency_key="deviation-plan-1",
            )
            action = created.object.actions[0]
            assert created.source_type == "portfolio_deviation"
            assert action.side == "sell"
            assert action.quantity == Decimal("80.00000000")
            assert action.reference_price == Decimal("1500")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_revise_rejects_stale_plan_revision(tmp_path) -> None:
    async def run() -> None:
        engine, _factory, clock, _drafts, service = await _service(tmp_path)
        try:
            created = await service.create_from_candidate(
                owner_id="owner-1",
                instrument_id="600519.SH",
                idempotency_key="candidate-plan-2",
            )
            clock.advance()
            await service.revise(
                owner_id="owner-1",
                plan_id=created.object.plan_id,
                expected_revision=1,
                actions=(
                    TradePlanActionRevision(
                        action_id=created.object.actions[0].action_id,
                        quantity=Decimal("1"),
                    ),
                ),
            )
            with pytest.raises(ConcurrentCommandConflict, match="has changed"):
                await service.revise(
                    owner_id="owner-1",
                    plan_id=created.object.plan_id,
                    expected_revision=1,
                    actions=(
                        TradePlanActionRevision(
                            action_id=created.object.actions[0].action_id,
                            quantity=Decimal("2"),
                        ),
                    ),
                )
        finally:
            await engine.dispose()

    asyncio.run(run())
