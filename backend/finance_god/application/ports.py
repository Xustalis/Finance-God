from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol, Self

from finance_god.domain import (
    AccountEventEnvelope,
    CashProjection,
    Fill,
    JournalEntry,
    PositionProjection,
    Reservation,
    SimulationAccount,
)


class IdempotencyRecord(Protocol):
    scope: str
    owner_user_id: str
    key: str
    request_hash: str
    result_reference: str


class AccountRepository(Protocol):
    async def get(self, account_id: str) -> SimulationAccount | None: ...
    async def get_current(self, owner_user_id: str) -> SimulationAccount | None: ...
    async def add(self, account: SimulationAccount) -> None: ...
    async def save(
        self, account: SimulationAccount, *, expected_revision: int
    ) -> None: ...


class AccountEventRepository(Protocol):
    async def list(self, account_id: str) -> tuple[AccountEventEnvelope, ...]: ...
    async def last(self, account_id: str) -> AccountEventEnvelope | None: ...
    async def append(self, event: AccountEventEnvelope) -> None: ...


class JournalRepository(Protocol):
    async def append(self, entry: JournalEntry) -> None: ...
    async def get_by_event(self, event_id: str) -> JournalEntry | None: ...
    async def list(self, account_id: str) -> tuple[JournalEntry, ...]: ...


class AccountProjectionRepository(Protocol):
    async def get(self, account_id: str, currency: str) -> CashProjection | None: ...
    async def add(self, projection: CashProjection) -> None: ...
    async def save(
        self, projection: CashProjection, *, expected_revision: int
    ) -> None: ...
    async def list(self, account_id: str) -> tuple[CashProjection, ...]: ...
    async def clear(self, account_id: str) -> None: ...


class PositionProjectionRepository(Protocol):
    async def get(
        self, account_id: str, instrument_id: str
    ) -> PositionProjection | None: ...
    async def add(self, projection: PositionProjection) -> None: ...
    async def save(
        self, projection: PositionProjection, *, expected_revision: int
    ) -> None: ...
    async def list(self, account_id: str) -> tuple[PositionProjection, ...]: ...
    async def clear(self, account_id: str) -> None: ...


class ReservationRepository(Protocol):
    async def get(self, reservation_id: str) -> Reservation | None: ...
    async def add(self, reservation: Reservation) -> None: ...
    async def save(
        self, reservation: Reservation, *, expected_revision: int
    ) -> None: ...
    async def list(self, account_id: str) -> tuple[Reservation, ...]: ...
    async def clear(self, account_id: str) -> None: ...


class FillRepository(Protocol):
    async def append(self, fill: Fill) -> None: ...
    async def get_by_event(self, event_id: str) -> Fill | None: ...
    async def list(self, account_id: str) -> tuple[Fill, ...]: ...


class IdempotencyRepository(Protocol):
    async def get(
        self, scope: str, owner_user_id: str, key: str
    ) -> IdempotencyRecord | None: ...
    async def add(
        self,
        *,
        scope: str,
        owner_user_id: str,
        key: str,
        request_hash: str,
        result_reference: str,
        created_at: datetime,
    ) -> None: ...


class AuditRepository(Protocol):
    async def append(
        self,
        *,
        audit_id: str,
        owner_user_id: str,
        account_id: str,
        event_id: str | None,
        event_hash: str,
        journal_hash: str | None,
        action: str,
        correlation_id: str,
        occurred_at: datetime,
    ) -> None: ...
    async def list_for_event(self, event_id: str) -> tuple[object, ...]: ...
    async def count_action(self, account_id: str, action: str) -> int: ...


class OutboxRepository(Protocol):
    async def append(
        self,
        *,
        message_id: str,
        topic: str,
        aggregate_id: str,
        event_id: str,
        event_hash: str,
        occurred_at: datetime,
    ) -> None: ...
    async def get_by_event(self, event_id: str) -> object | None: ...


class AggregateLockRepository(Protocol):
    async def owner(self, owner_user_id: str) -> None: ...
    async def account(self, account_id: str) -> None: ...


class AccountActivityRepository(Protocol):
    async def has_open(self, account_id: str) -> bool: ...
    async def open(
        self,
        *,
        activity_id: str,
        account_id: str,
        activity_type: str,
        reference_id: str,
        occurred_at: datetime,
    ) -> None: ...
    async def complete(
        self, reference_id: str, *, occurred_at: datetime
    ) -> None: ...
    async def reopen(self, reference_id: str) -> None: ...


class UnitOfWork(Protocol):
    accounts: AccountRepository
    events: AccountEventRepository
    journals: JournalRepository
    account_projections: AccountProjectionRepository
    position_projections: PositionProjectionRepository
    reservations: ReservationRepository
    fills: FillRepository
    idempotency: IdempotencyRepository
    audits: AuditRepository
    outbox: OutboxRepository
    locks: AggregateLockRepository
    activities: AccountActivityRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None: ...
    async def flush(self) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self, prefix: str) -> str: ...


class RuleCatalog(Protocol):
    @property
    def simulation_rule_version(self) -> str: ...
