from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from finance_god.domain import (
    AuditReference,
    OrderDraft,
    OrderDraftStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    VersionReference,
)
from finance_god.execution import (
    DeterministicMatcher,
    DraftMode,
    SimulationExecutionService,
    StoredDraft,
)
from finance_god.infrastructure.persistence.models import Base
from finance_god.infrastructure.persistence.simulation_uow import (
    SimulationUnitOfWork,
)

NOW = datetime(2026, 7, 24, 2, tzinfo=UTC)
REQUEST_HASH = hashlib.sha256(b"simulation-transaction").hexdigest()


class TrackingAsyncSession(AsyncSession):
    opened = 0
    closed = 0

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        type(self).opened += 1

    async def close(self) -> None:
        await super().close()
        type(self).closed += 1


class Accounts:
    async def require_current_account(
        self,
        owner_id: str,
        account_id: str,
    ) -> None:
        assert (owner_id, account_id) == ("owner-1", "account-1")


class UnusedPort:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unexpected port call: {name}")


class FailingTransport:
    async def submit(self, order: object) -> object:
        del order
        raise RuntimeError("transport failed")


class Clock:
    def now(self) -> datetime:
        return NOW


class IDs:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}-generated"


def make_draft(draft_id: str) -> OrderDraft:
    return OrderDraft(
        draft_id=draft_id,
        revision=1,
        status=OrderDraftStatus.DRAFT,
        account_id="account-1",
        instrument_id="600519.SSE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        amount=None,
        limit_price=None,
        time_in_force=TimeInForce.DAY,
        fund_rule_version=None,
        valid_until=NOW + timedelta(days=1),
        input_versions=(
            VersionReference(
                object_type="market_snapshot",
                object_id="600519.SSE",
                version="snapshot-v1",
            ),
        ),
        audit_reference=AuditReference(
            audit_id=f"audit-{draft_id}",
            actor_id="owner-1",
            recorded_at=NOW,
        ),
    )


@pytest.fixture
async def simulation_session_factory(
    tmp_path,
) -> async_sessionmaker[AsyncSession]:
    TrackingAsyncSession.opened = 0
    TrackingAsyncSession.closed = 0
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'simulation.db'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=TrackingAsyncSession,
    )
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_execution_command_commits_and_next_request_reads_it(
    simulation_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SimulationExecutionService(
        uow_factory=lambda: SimulationUnitOfWork(simulation_session_factory),
        accounts=Accounts(),
        plans=UnusedPort(),
        manual_review=UnusedPort(),
        risk=UnusedPort(),
        transport=UnusedPort(),
        bars=UnusedPort(),
        ledger=UnusedPort(),
        matcher=DeterministicMatcher(),
        clock=Clock(),
        ids=IDs(),
    )

    created = await service.create_draft(
        owner_id="owner-1",
        mode=DraftMode.MANUAL,
        draft=make_draft("draft-1"),
        plan_reference=None,
        idempotency_key="draft-key",
        request_hash=REQUEST_HASH,
    )
    reread = await service.get_draft(
        owner_id="owner-1",
        draft_id=created.draft.draft_id,
    )
    replayed = await service.create_draft(
        owner_id="owner-1",
        mode=DraftMode.MANUAL,
        draft=make_draft("draft-2"),
        plan_reference=None,
        idempotency_key="draft-key",
        request_hash=REQUEST_HASH,
    )
    concurrent = await asyncio.gather(
        service.create_draft(
            owner_id="owner-1",
            mode=DraftMode.MANUAL,
            draft=make_draft("draft-3"),
            plan_reference=None,
            idempotency_key="concurrent-key",
            request_hash=REQUEST_HASH,
        ),
        service.create_draft(
            owner_id="owner-1",
            mode=DraftMode.MANUAL,
            draft=make_draft("draft-4"),
            plan_reference=None,
            idempotency_key="concurrent-key",
            request_hash=REQUEST_HASH,
        ),
    )

    assert reread == created
    assert replayed == created
    assert concurrent[0] == concurrent[1]
    assert TrackingAsyncSession.opened == TrackingAsyncSession.closed


@pytest.mark.asyncio
async def test_uow_exception_rolls_back_and_closes_session(
    simulation_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError, match="force rollback"):
        async with SimulationUnitOfWork(simulation_session_factory) as uow:
            await uow.repository.create_draft(
                _stored_draft("draft-rollback"),
                idempotency_key="rollback-key",
                request_hash=REQUEST_HASH,
            )
            raise RuntimeError("force rollback")

    async with SimulationUnitOfWork(simulation_session_factory) as uow:
        assert await uow.repository.get_draft("draft-rollback") is None
    assert TrackingAsyncSession.opened == TrackingAsyncSession.closed


@pytest.mark.asyncio
async def test_execution_failure_rolls_back_partial_order(
    simulation_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    confirmed_draft = make_draft("draft-confirmed").model_copy(
        update={"status": OrderDraftStatus.CONFIRMED}
    )
    async with SimulationUnitOfWork(simulation_session_factory) as uow:
        await uow.repository.create_draft(
            _stored_draft(
                "draft-confirmed",
                draft_value=confirmed_draft,
            ),
            idempotency_key="confirmed-key",
            request_hash=REQUEST_HASH,
        )
        await uow.commit()
    service = SimulationExecutionService(
        uow_factory=lambda: SimulationUnitOfWork(simulation_session_factory),
        accounts=Accounts(),
        plans=UnusedPort(),
        manual_review=UnusedPort(),
        risk=UnusedPort(),
        transport=FailingTransport(),
        bars=UnusedPort(),
        ledger=UnusedPort(),
        matcher=DeterministicMatcher(),
        clock=Clock(),
        ids=IDs(),
    )

    with pytest.raises(RuntimeError, match="transport failed"):
        await service.submit(
            owner_id="owner-1",
            draft_id="draft-confirmed",
            idempotency_key="order-key",
            request_hash=REQUEST_HASH,
        )

    async with SimulationUnitOfWork(simulation_session_factory) as uow:
        assert (
            await uow.repository.get_order_for_draft("draft-confirmed")
            is None
        )
    assert TrackingAsyncSession.opened == TrackingAsyncSession.closed


def _stored_draft(
    draft_id: str,
    *,
    draft_value: OrderDraft | None = None,
) -> StoredDraft:
    return StoredDraft(
        owner_id="owner-1",
        mode=DraftMode.MANUAL,
        draft=draft_value or make_draft(draft_id),
        plan_reference=None,
    )
