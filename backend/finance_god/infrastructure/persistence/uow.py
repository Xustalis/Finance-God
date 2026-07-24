from __future__ import annotations

from collections.abc import Callable
from typing import Self

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from finance_god.application.ports import (
    AccountActivityRepository as AccountActivityRepositoryPort,
    AccountEventRepository as AccountEventRepositoryPort,
    AccountProjectionRepository as AccountProjectionRepositoryPort,
    AccountRepository as AccountRepositoryPort,
    AggregateLockRepository as AggregateLockRepositoryPort,
    AuditRepository as AuditRepositoryPort,
    FillRepository as FillRepositoryPort,
    IdempotencyRepository as IdempotencyRepositoryPort,
    JournalRepository as JournalRepositoryPort,
    OutboxRepository as OutboxRepositoryPort,
    PositionProjectionRepository as PositionProjectionRepositoryPort,
    ReservationRepository as ReservationRepositoryPort,
)

from .models import AccountRow
from .repositories import (
    AccountProjectionRepository,
    AccountRepository,
    ActivityRepository,
    AuditRepository,
    EventRepository,
    FillRepository,
    IdempotencyRepository,
    JournalRepository,
    OutboxRepository,
    PositionProjectionRepository,
    ReservationRepository,
)


def create_session_factory(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_foreign_keys(
            connection: object, connection_record: object
        ) -> None:
            cursor = connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine, async_sessionmaker(engine, expire_on_commit=False)


class AggregateLocks:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def owner(self, owner_user_id: str) -> None:
        if self._session.bind and self._session.bind.dialect.name == "postgresql":
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"owner:{owner_user_id}"},
            )

    async def account(self, account_id: str) -> None:
        row = await self._session.scalar(
            select(AccountRow.account_id)
            .where(AccountRow.account_id == account_id)
            .with_for_update()
        )
        if row is None:
            return


class SqlAlchemyUnitOfWork:
    accounts: AccountRepositoryPort
    events: AccountEventRepositoryPort
    journals: JournalRepositoryPort
    account_projections: AccountProjectionRepositoryPort
    position_projections: PositionProjectionRepositoryPort
    reservations: ReservationRepositoryPort
    fills: FillRepositoryPort
    idempotency: IdempotencyRepositoryPort
    audits: AuditRepositoryPort
    outbox: OutboxRepositoryPort
    locks: AggregateLockRepositoryPort
    activities: AccountActivityRepositoryPort

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self.session = self._session_factory()
        self._transaction = await self.session.begin()
        self.accounts = AccountRepository(self.session)
        self.events = EventRepository(self.session)
        self.journals = JournalRepository(self.session)
        self.account_projections = AccountProjectionRepository(self.session)
        self.position_projections = PositionProjectionRepository(self.session)
        self.reservations = ReservationRepository(self.session)
        self.fills = FillRepository(self.session)
        self.idempotency = IdempotencyRepository(self.session)
        self.audits = AuditRepository(self.session)
        self.outbox = OutboxRepository(self.session)
        self.locks = AggregateLocks(self.session)
        self.activities = ActivityRepository(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        if self._transaction.is_active:
            await self._transaction.rollback()
        await self.session.close()

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self._transaction.commit()

    async def rollback(self) -> None:
        if self._transaction.is_active:
            await self._transaction.rollback()
