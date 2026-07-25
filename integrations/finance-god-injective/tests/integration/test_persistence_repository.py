from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.persistence import (
    AsyncUnitOfWork,
    Base,
    IdempotencyConflictError,
    InvalidStateTransitionError,
    RevisionConflictError,
    canonical_json_hash,
    create_engine,
    create_session_factory,
)
from bridge.persistence.database import SessionFactory
from bridge.persistence.locks import (
    UnsupportedAdvisoryLockError,
    wallet_advisory_lock,
)


@pytest.fixture
async def persistence(
    tmp_path: object,
) -> tuple[AsyncEngine, SessionFactory]:
    database_path = tmp_path / "bridge-test.db"  # type: ignore[operator]
    engine = create_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    yield engine, factory
    await engine.dispose()


def require_repository(work: AsyncUnitOfWork):
    assert work.repository is not None
    return work.repository


async def create_confirmed_plan(
    work: AsyncUnitOfWork,
    *,
    price: Decimal = Decimal("10.123456789012345678"),
    quantity: Decimal = Decimal("1.000000000000000001"),
):
    repository = require_repository(work)
    plan = await repository.create_plan(
        market_id="0xmarket",
        ticker="INJ/USDT",
        side="buy",
        price=price,
        quantity=quantity,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    reviewed = await repository.review_plan(
        plan.id,
        expected_revision=1,
        risk_report={"approved": True, "notional": "10.123456789012345688"},
        approved=True,
    )
    return await repository.confirm_plan(
        plan.id,
        expected_revision=reviewed.revision,
    )


async def test_plan_decimal_cas_and_status_listing(
    persistence: tuple[AsyncEngine, SessionFactory],
) -> None:
    _, factory = persistence
    price = Decimal("10.123456789012345678")
    quantity = Decimal("1.000000000000000001")

    async with AsyncUnitOfWork(factory) as work:
        confirmed = await create_confirmed_plan(
            work,
            price=price,
            quantity=quantity,
        )
        repository = require_repository(work)
        listed = await repository.list_plans_by_status("confirmed", limit=10)
        confirmed_for_worker = await repository.list_confirmed_plans(limit=10)
        assert [item.id for item in listed] == [confirmed.id]
        assert [item.id for item in confirmed_for_worker] == [confirmed.id]
        assert confirmed.price == price
        assert confirmed.quantity == quantity
        assert confirmed.order_type == "limit"
        assert confirmed.time_in_force == "gtc"
        with pytest.raises(RevisionConflictError):
            await repository.confirm_plan(confirmed.id, expected_revision=1)
        await work.commit()


async def test_source_snapshot_is_deduplicated_and_allowlisted(
    persistence: tuple[AsyncEngine, SessionFactory],
) -> None:
    _, factory = persistence
    projection = {
        "plan_id": "plan-1",
        "version": "3",
        "status": "confirmed",
        "draft_confirmed": True,
    }

    async with AsyncUnitOfWork(factory) as work:
        repository = require_repository(work)
        first = await repository.create_source_snapshot(
            source_plan_id="plan-1",
            source_plan_version="3",
            source_plan_status="confirmed",
            draft_confirmed=True,
            projection=projection,
        )
        second = await repository.create_source_snapshot(
            source_plan_id="plan-1",
            projection=dict(reversed(list(projection.items()))),
        )
        assert first.id == second.id
        assert first.classification == "context_only"
        assert first.asset_domain == "non_executable_asset_domain"
        assert first.normalized_hash == canonical_json_hash(projection)

        with pytest.raises(ValueError, match="not allowlisted"):
            await repository.create_source_snapshot(
                source_plan_id="plan-2",
                projection={"plan_id": "plan-2", "jwt": "secret"},
            )


async def test_idempotency_replays_only_the_same_request(
    persistence: tuple[AsyncEngine, SessionFactory],
) -> None:
    _, factory = persistence
    first_hash = canonical_json_hash({"side": "buy"})
    other_hash = canonical_json_hash({"side": "sell"})

    async with AsyncUnitOfWork(factory) as work:
        repository = require_repository(work)
        first, created = await repository.reserve_idempotency(
            operation="create-plan",
            idempotency_key="request-1",
            request_hash=first_hash,
        )
        replay, replay_created = await repository.reserve_idempotency(
            operation="create-plan",
            idempotency_key="request-1",
            request_hash=first_hash,
        )
        assert created is True
        assert replay_created is False
        assert replay.id == first.id

        with pytest.raises(IdempotencyConflictError):
            await repository.reserve_idempotency(
                operation="create-plan",
                idempotency_key="request-1",
                request_hash=other_hash,
            )

        completed = await repository.complete_idempotency(
            first.id,
            response_code=201,
            response_body={"id": "plan-1"},
            resource_type="plan",
            resource_id="plan-1",
        )
        assert completed.status == "completed"


async def test_broadcast_updates_are_atomic_and_events_are_deduplicated(
    persistence: tuple[AsyncEngine, SessionFactory],
) -> None:
    _, factory = persistence

    async with AsyncUnitOfWork(factory) as work:
        repository = require_repository(work)
        plan = await create_confirmed_plan(work)
        order, attempt = await repository.begin_broadcast(
            plan.id,
            expected_revision=plan.revision,
            market_id=plan.market_id,
            subaccount_id="0xsubaccount",
            request_hash=canonical_json_hash({"plan_id": plan.id}),
            max_active_orders=1,
            allow_sqlite_test_noop=True,
        )
        assert attempt.status == "started"
        assert order.quantity == plan.quantity
        assert await repository.count_active_orders(subaccount_id="0xsubaccount") == 1

        broadcast = await repository.complete_broadcast(
            order.id,
            tx_hash="0xtx",
            order_hash="0xorder",
            chain_projection={"tx_hash": "0xtx"},
        )
        assert broadcast.status == "broadcast"
        submitted = await repository.get_plan(plan.id)
        assert submitted.status == "submitted"

        occurred_at = datetime.now(UTC)
        opened, first_event, created = await repository.apply_order_event(
            order.id,
            event_key="block-10:order-1",
            status="open",
            payload={"status": "booked"},
            occurred_at=occurred_at,
        )
        replayed, replay_event, replay_created = await repository.apply_order_event(
            order.id,
            event_key="block-10:order-1",
            status="open",
            payload={"status": "booked"},
            occurred_at=occurred_at,
        )
        assert opened.status == "open"
        assert created is True
        assert replay_created is False
        assert replay_event.id == first_event.id
        assert replayed.id == order.id
        assert len(await repository.list_active_orders(limit=10)) == 1
        await work.commit()


async def test_order_event_rejects_state_regression_and_decreasing_fill(
    persistence: tuple[AsyncEngine, SessionFactory],
) -> None:
    _, factory = persistence

    async with AsyncUnitOfWork(factory) as work:
        repository = require_repository(work)
        plan = await create_confirmed_plan(work)
        order, _ = await repository.begin_broadcast(
            plan.id,
            expected_revision=plan.revision,
            market_id=plan.market_id,
            subaccount_id="0xsubaccount",
            request_hash=canonical_json_hash({"plan_id": plan.id}),
            max_active_orders=1,
            allow_sqlite_test_noop=True,
        )
        await repository.complete_broadcast(order.id, tx_hash="0xtx")
        now = datetime.now(UTC)
        await repository.apply_order_event(
            order.id,
            event_key="event-1",
            status="partially_filled",
            payload={"filled_quantity": "0.5"},
            occurred_at=now,
            filled_quantity=Decimal("0.5"),
        )
        with pytest.raises(InvalidStateTransitionError, match="cannot decrease"):
            await repository.apply_order_event(
                order.id,
                event_key="event-2",
                status="partially_filled",
                payload={"filled_quantity": "0.4"},
                occurred_at=now,
                filled_quantity=Decimal("0.4"),
            )
        with pytest.raises(InvalidStateTransitionError, match="cannot exceed"):
            await repository.apply_order_event(
                order.id,
                event_key="event-overfill",
                status="filled",
                payload={"filled_quantity": "2"},
                occurred_at=now,
                filled_quantity=Decimal("2"),
            )
        with pytest.raises(InvalidStateTransitionError, match="cannot transition"):
            await repository.apply_order_event(
                order.id,
                event_key="event-3",
                status="broadcast",
                payload={"status": "broadcast"},
                occurred_at=now,
            )


async def test_sqlite_advisory_lock_requires_explicit_test_opt_in(
    persistence: tuple[AsyncEngine, SessionFactory],
) -> None:
    _, factory = persistence
    async with factory() as session, session.begin():
        with pytest.raises(UnsupportedAdvisoryLockError):
            async with wallet_advisory_lock(session, "wallet"):
                pass
        async with wallet_advisory_lock(
            session,
            "wallet",
            allow_sqlite_test_noop=True,
        ):
            assert session.in_transaction()
