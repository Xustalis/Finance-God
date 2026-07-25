from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base as AppBase
from finance_god.domain import (
    AuditReference,
    DomainInvariantViolation,
    ExchangeOrder,
    ExchangeOrderStatus,
    OrderDraft,
    OrderDraftStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    VersionReference,
)
from finance_god.execution import (
    DraftMode,
    SimulationFill,
    StoredDraft,
    StoredOrder,
    TradeDecisionContext,
)
from finance_god.infrastructure.persistence import Base as TradingBase
from finance_god.infrastructure.persistence.simulation_models import (
    SimulationExecutionOutboxRow,
)
from finance_god.infrastructure.persistence.simulation_uow import (
    SimulationUnitOfWork,
)
from finance_god.infrastructure.persistence.trade_review_models import (
    TradeDecisionSnapshotRow,
)
from finance_god.trade_review import TradeDecisionSnapshot, TradeReviewService

NOW = datetime(2026, 7, 25, 1, tzinfo=UTC)
REQUEST_HASH = hashlib.sha256(b"trade-review-outbox").hexdigest()
MARKET_EVIDENCE = VersionReference(
    object_type="market_quote",
    object_id="600519.SSE",
    version="2026-07-25T01:00:00Z",
)
DECISION_CONTEXT = TradeDecisionContext(
    thesis="估值处于历史低位且盈利改善",
    expected_return="三个月目标收益 10%",
    primary_risks="盈利修复不及预期",
    contrary_evidence="行业净息差仍在收窄",
    expected_holding_period="三个月",
    confidence="中等",
)


@pytest.fixture
async def sessions() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(AppBase.metadata.create_all)
        await connection.run_sync(TradingBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_delayed_fill_projects_submission_facts_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    draft, order, fill = _execution_facts(
        prefix="delayed",
        side=OrderSide.BUY,
        quantity=Decimal("25"),
    )
    await _persist_accepted_then_filled(sessions, draft, order, fill)
    service = TradeReviewService(sessions)

    first = await service.project_execution_outbox(owner_id="owner-1")
    replay = await service.project_execution_outbox(owner_id="owner-1")

    assert len(first) == 1
    assert replay == ()
    async with sessions() as session:
        snapshot_row = await session.scalar(
            select(TradeDecisionSnapshotRow).where(
                TradeDecisionSnapshotRow.fill_id == fill.fill_id
            )
        )
        outbox = await session.scalar(
            select(SimulationExecutionOutboxRow).where(
                SimulationExecutionOutboxRow.topic
                == "simulation.execution.fill_recorded",
                SimulationExecutionOutboxRow.aggregate_id == fill.fill_id,
            )
        )
    assert snapshot_row is not None
    snapshot = TradeDecisionSnapshot.model_validate(snapshot_row.payload_json)
    assert snapshot.profile_version == 7
    assert snapshot.thesis.value == DECISION_CONTEXT.thesis
    assert snapshot.expected_return.value == DECISION_CONTEXT.expected_return
    assert outbox is not None
    assert outbox.published_at is not None
    assert outbox.attempt_count == 1
    assert outbox.last_error is None


@pytest.mark.asyncio
async def test_failed_projection_is_observable_and_retryable(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    draft, order, fill = _execution_facts(
        prefix="sell",
        side=OrderSide.SELL,
        quantity=Decimal("5"),
    )
    await _persist_accepted_then_filled(sessions, draft, order, fill)
    service = TradeReviewService(sessions)

    assert await service.project_execution_outbox(owner_id="owner-1") == ()

    async with sessions() as session:
        failed = await session.scalar(
            select(SimulationExecutionOutboxRow).where(
                SimulationExecutionOutboxRow.aggregate_id == fill.fill_id
            )
        )
    assert failed is not None
    assert failed.published_at is None
    assert failed.attempt_count == 1
    assert failed.last_error is not None
    assert "ValueError" in failed.last_error

    await service.record_filled_order(
        owner_id="owner-1",
        account_id="account-1",
        order={
            "order_id": "opening-order",
            "instrument_id": "600519.SSE",
            "side": "buy",
            "fills": [
                {
                    "fill_id": "opening-fill",
                    "quantity": "5",
                    "price": "10",
                    "fee": "1",
                    "occurred_at": (NOW - timedelta(minutes=1)).isoformat(),
                }
            ],
        },
        market_evidence=MARKET_EVIDENCE.model_dump(mode="json"),
        position_quantity_after=Decimal("5"),
        profile_version=7,
        decision_context=DECISION_CONTEXT,
    )
    retried = await service.project_execution_outbox(owner_id="owner-1")

    assert len(retried) == 1
    assert retried[0]["review_triggered"] is True
    async with sessions() as session:
        delivered = await session.scalar(
            select(SimulationExecutionOutboxRow).where(
                SimulationExecutionOutboxRow.aggregate_id == fill.fill_id
            )
        )
    assert delivered is not None
    assert delivered.published_at is not None
    assert delivered.attempt_count == 2
    assert delivered.last_error is None


@pytest.mark.asyncio
async def test_outbox_payload_tampering_is_rejected(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    draft, order, fill = _execution_facts(
        prefix="tampered",
        side=OrderSide.BUY,
        quantity=Decimal("10"),
    )
    await _persist_accepted_then_filled(sessions, draft, order, fill)
    async with sessions() as session:
        async with session.begin():
            row = await session.scalar(
                select(SimulationExecutionOutboxRow).where(
                    SimulationExecutionOutboxRow.aggregate_id == fill.fill_id
                )
            )
            assert row is not None
            row.payload_json = {"owner_id": "attacker"}

    service = TradeReviewService(sessions)
    assert await service.project_execution_outbox(owner_id="owner-1") == ()

    async with sessions() as session:
        row = await session.scalar(
            select(SimulationExecutionOutboxRow).where(
                SimulationExecutionOutboxRow.aggregate_id == fill.fill_id
            )
        )
        snapshot = await session.scalar(
            select(TradeDecisionSnapshotRow).where(
                TradeDecisionSnapshotRow.fill_id == fill.fill_id
            )
        )
    assert row is not None
    assert row.published_at is None
    assert row.last_error is not None
    assert "immutable execution event" in row.last_error
    assert snapshot is None


@pytest.mark.asyncio
async def test_poison_message_does_not_block_later_fill(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    sell_draft, sell_order, sell_fill = _execution_facts(
        prefix="poison",
        side=OrderSide.SELL,
        quantity=Decimal("5"),
    )
    buy_draft, buy_order, buy_fill = _execution_facts(
        prefix="healthy",
        side=OrderSide.BUY,
        quantity=Decimal("5"),
    )
    await _persist_accepted_then_filled(
        sessions,
        sell_draft,
        sell_order,
        sell_fill,
    )
    await _persist_accepted_then_filled(
        sessions,
        buy_draft,
        buy_order,
        buy_fill,
    )

    projected = await TradeReviewService(sessions).project_execution_outbox(
        owner_id="owner-1"
    )

    assert len(projected) == 1
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(SimulationExecutionOutboxRow).where(
                    SimulationExecutionOutboxRow.aggregate_id.in_(
                        {sell_fill.fill_id, buy_fill.fill_id}
                    )
                )
            )
        ).all()
    by_fill = {row.aggregate_id: row for row in rows}
    assert by_fill[sell_fill.fill_id].published_at is None
    assert by_fill[sell_fill.fill_id].last_error is not None
    assert by_fill[buy_fill.fill_id].published_at is not None


@pytest.mark.asyncio
async def test_submission_facts_cannot_change_on_later_revisions(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    draft, order, _fill = _execution_facts(
        prefix="immutable",
        side=OrderSide.BUY,
        quantity=Decimal("5"),
    )
    async with SimulationUnitOfWork(sessions) as uow:
        await uow.repository.create_draft(
            draft,
            idempotency_key="immutable-draft:create",
            request_hash=REQUEST_HASH,
        )
        await uow.repository.create_order(
            order,
            idempotency_key="immutable-order:submit",
            request_hash=REQUEST_HASH,
        )
        await uow.commit()

    changed_context = DECISION_CONTEXT.model_copy(update={"thesis": "事后改写"})
    changed_draft = draft.model_copy(
        update={
            "record_revision": 2,
            "decision_context": changed_context,
        }
    )
    async with SimulationUnitOfWork(sessions) as uow:
        with pytest.raises(DomainInvariantViolation, match="immutable"):
            await uow.repository.save_draft(changed_draft, expected_revision=1)

    exchange = order.exchange_order
    assert exchange is not None
    changed_order = order.model_copy(
        update={
            "decision_context": changed_context,
            "exchange_order": exchange.model_copy(update={"revision": 2}),
        }
    )
    async with SimulationUnitOfWork(sessions) as uow:
        with pytest.raises(DomainInvariantViolation, match="immutable"):
            await uow.repository.save_order(changed_order, expected_revision=1)


async def _persist_accepted_then_filled(
    sessions: async_sessionmaker[AsyncSession],
    draft: StoredDraft,
    order: StoredOrder,
    fill: SimulationFill,
) -> None:
    async with SimulationUnitOfWork(sessions) as uow:
        await uow.repository.create_draft(
            draft,
            idempotency_key=f"{draft.draft.draft_id}:create",
            request_hash=REQUEST_HASH,
        )
        await uow.repository.create_order(
            order,
            idempotency_key=f"{order.order_id}:submit",
            request_hash=REQUEST_HASH,
        )
        await uow.commit()
    exchange = order.exchange_order
    assert exchange is not None
    filled_exchange = exchange.record_fill(
        fill.quantity,
        audit_reference=AuditReference(
            audit_id=f"audit-{fill.fill_id}",
            actor_id="simulation-execution-service",
            recorded_at=fill.occurred_at,
        ),
    )
    filled_order = order.model_copy(update={"exchange_order": filled_exchange})
    async with SimulationUnitOfWork(sessions) as uow:
        await uow.repository.save_order(
            filled_order,
            expected_revision=exchange.revision,
        )
        await uow.repository.append_fill(fill)
        await uow.commit()


def _execution_facts(
    *,
    prefix: str,
    side: OrderSide,
    quantity: Decimal,
) -> tuple[StoredDraft, StoredOrder, SimulationFill]:
    draft_id = f"draft-{prefix}"
    order_id = f"order-{prefix}"
    order_draft = OrderDraft(
        draft_id=draft_id,
        revision=1,
        status=OrderDraftStatus.CONFIRMED,
        account_id="account-1",
        instrument_id="600519.SSE",
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        amount=None,
        limit_price=None,
        time_in_force=TimeInForce.DAY,
        fund_rule_version=None,
        valid_until=NOW + timedelta(minutes=30),
        input_versions=(MARKET_EVIDENCE,),
        audit_reference=AuditReference(
            audit_id=f"audit-{draft_id}",
            actor_id="owner-1",
            recorded_at=NOW,
        ),
    )
    stored_draft = StoredDraft(
        owner_id="owner-1",
        mode=DraftMode.MANUAL,
        draft=order_draft,
        confirmed_at=NOW,
        decision_context=DECISION_CONTEXT,
        submission_profile_version=7,
    )
    exchange = ExchangeOrder(
        order_id=order_id,
        revision=1,
        status=ExchangeOrderStatus.ACCEPTED,
        idempotency_key=f"{order_id}:submit",
        draft_reference=VersionReference(
            object_type="order_draft",
            object_id=draft_id,
            version="1",
        ),
        quantity=quantity,
        cumulative_filled=Decimal("0"),
        audit_reference=AuditReference(
            audit_id=f"audit-{order_id}",
            actor_id="simulation-transport",
            recorded_at=NOW,
        ),
    )
    stored_order = StoredOrder(
        owner_id="owner-1",
        draft_reference=exchange.draft_reference,
        decision_context=DECISION_CONTEXT,
        submission_profile_version=7,
        exchange_order=exchange,
    )
    fill = SimulationFill(
        fill_id=f"fill-{prefix}",
        order_id=order_id,
        account_id="account-1",
        instrument_id="600519.SSE",
        side=side,
        quantity=quantity,
        price=Decimal("11"),
        fee=Decimal("1"),
        slippage_bps=Decimal("0"),
        market_evidence=MARKET_EVIDENCE,
        model_version="deterministic-matcher-v1",
        rule_version="simulation-rules-v1",
        occurred_at=NOW + timedelta(minutes=1),
        ledger_fill_id=f"ledger-{prefix}",
    )
    return stored_draft, stored_order, fill
