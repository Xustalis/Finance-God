from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from finance_god.domain import WorkflowRun

from .uow import create_session_factory
from .workflow_models import (
    WorkflowAuditRow,
    WorkflowEventRow,
    WorkflowExecutionAuditRow,
    WorkflowOutboxRow,
)
from .workflow_repository import WorkflowRepository


class WorkflowRepositoryProtocol(Protocol):
    async def get(self, run_id: str) -> WorkflowRun | None: ...
    async def get_owner_id(self, run_id: str) -> str | None: ...
    async def create_queued(
        self,
        *,
        run: WorkflowRun,
        idempotency_key: str,
        request_hash: str,
        request_intent: str,
        owner_id: str,
        scope: dict[str, str],
        requested_at: datetime,
        audit_payload: Mapping[str, object],
        outbox_payload: Mapping[str, object],
    ) -> tuple[WorkflowRun, bool]: ...
    async def compare_and_append(
        self,
        *,
        run: WorkflowRun,
        expected_revision: int,
        event_type: str,
        event_payload: dict[str, object],
        outbox_topic: str,
    ) -> WorkflowRun: ...
    async def append_audit(
        self,
        *,
        audit_id: str,
        run_id: str,
        event_type: str,
        payload_json: Mapping[str, object],
        occurred_at: datetime,
        actor_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None: ...
    async def list_events(self, run_id: str) -> tuple[WorkflowEventRow, ...]: ...
    async def list_audits(self, run_id: str) -> tuple[WorkflowAuditRow, ...]: ...
    async def list_execution_audits(
        self,
        run_id: str,
    ) -> tuple[WorkflowExecutionAuditRow, ...]: ...
    async def list_outbox(self, run_id: str) -> tuple[WorkflowOutboxRow, ...]: ...


def create_workflow_session_factory(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    return create_session_factory(database_url)


class WorkflowUnitOfWork:
    workflows: WorkflowRepositoryProtocol

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("workflow unit of work is already active")
        self._session = self._session_factory()
        if self._session.get_bind().dialect.name == "sqlite":
            # SQLite otherwise lets a first SAVEPOINT become the physical
            # transaction, which would escape the UoW rollback on release.
            await self._session.execute(text("BEGIN IMMEDIATE"))
            transaction = self._session.get_transaction()
            if transaction is None:
                raise RuntimeError("SQLite workflow transaction did not start")
            self._transaction = transaction
        else:
            self._transaction = await self._session.begin()
        self.workflows = WorkflowRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        session = self._require_session()
        if self._transaction.is_active:
            await self._transaction.rollback()
        await session.close()
        self._session = None

    async def flush(self) -> None:
        await self._require_session().flush()

    async def commit(self) -> None:
        await self._transaction.commit()

    async def rollback(self) -> None:
        if self._transaction.is_active:
            await self._transaction.rollback()

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("workflow unit of work is not active")
        return self._session
