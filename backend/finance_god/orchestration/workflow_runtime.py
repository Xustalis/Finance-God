"""Production composition root for durable workflow commands."""

from __future__ import annotations

import os
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finance_god.domain.models import WorkflowRun
from finance_god.infrastructure.persistence.workflow_persistence import (
    WorkflowUnitOfWork,
    create_workflow_session_factory,
)

from .workflow_commands import (
    DataQualityWorkflowCreationPort,
    WorkflowCommandService,
    WorkflowCreateCommand,
    WorkflowCreationReceipt,
    WorkflowExecutionAudit,
)
from .workflow_registry import FormalWorkflowRegistry, WorkflowDefinition

WORKFLOW_DATABASE_URL_ENV = "FINANCE_GOD_DATABASE_URL"


class UuidWorkflowRunIds:
    def new(self) -> str:
        return f"workflow-{uuid4().hex}"


class WorkflowCommandRuntime:
    """Owns async DB lifecycle and exposes only the stable command surface."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
        registry: FormalWorkflowRegistry,
    ) -> None:
        self._engine = engine
        self._session_factory = session_factory
        self._registry = registry
        self._run_ids = UuidWorkflowRunIds()
        self._closed = False

    async def create(
        self,
        command: WorkflowCreateCommand,
    ) -> WorkflowCreationReceipt:
        self._ensure_open()
        async with WorkflowUnitOfWork(self._session_factory) as uow:
            service = WorkflowCommandService(
                registry=self._registry,
                repository=uow.workflows,
                run_ids=self._run_ids,
            )
            receipt = await service.create(command)
            await uow.commit()
            return receipt

    async def __aenter__(self) -> Self:
        self._ensure_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        await self.close()

    async def get(self, run_id: str) -> WorkflowRun | None:
        self._ensure_open()
        async with WorkflowUnitOfWork(self._session_factory) as uow:
            run = await uow.workflows.get(run_id)
            await uow.commit()
            return run

    async def get_owner_id(self, run_id: str) -> str | None:
        self._ensure_open()
        async with WorkflowUnitOfWork(self._session_factory) as uow:
            owner_id = await uow.workflows.get_owner_id(run_id)
            await uow.commit()
            return owner_id

    async def get_record(self, run_id: str) -> dict[str, object] | None:
        self._ensure_open()
        async with WorkflowUnitOfWork(self._session_factory) as uow:
            record = await uow.workflows.get_record(run_id)
            await uow.commit()
            return record

    async def list_records(
        self,
        *,
        owner_id: str,
        limit: int,
        cursor: str | None,
        status: str | None,
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        self._ensure_open()
        async with WorkflowUnitOfWork(self._session_factory) as uow:
            records = await uow.workflows.list_records(
                owner_id=owner_id,
                limit=limit,
                cursor=cursor,
                status=status,
            )
            await uow.commit()
            return records

    async def cancel(
        self,
        run_id: str,
        *,
        actor_id: str,
        cancelled_at: datetime,
    ) -> WorkflowRun:
        self._ensure_open()
        async with WorkflowUnitOfWork(self._session_factory) as uow:
            service = WorkflowCommandService(
                registry=self._registry,
                repository=uow.workflows,
                run_ids=self._run_ids,
            )
            run = await service.cancel(
                run_id,
                actor_id=actor_id,
                cancelled_at=cancelled_at,
            )
            await uow.commit()
            return run

    async def retry(
        self,
        run_id: str,
        *,
        owner_id: str,
        idempotency_key: str,
        mode: str,
        requested_at: datetime,
    ) -> WorkflowCreationReceipt:
        self._ensure_open()
        async with WorkflowUnitOfWork(self._session_factory) as uow:
            service = WorkflowCommandService(
                registry=self._registry,
                repository=uow.workflows,
                run_ids=self._run_ids,
            )
            receipt = await service.retry(
                run_id,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                mode=mode,
                requested_at=requested_at,
            )
            await uow.commit()
            return receipt

    async def list_execution_audits(
        self,
        run_id: str,
    ) -> tuple[WorkflowExecutionAudit, ...]:
        self._ensure_open()
        async with WorkflowUnitOfWork(self._session_factory) as uow:
            service = WorkflowCommandService(
                registry=self._registry,
                repository=uow.workflows,
                run_ids=self._run_ids,
            )
            audits = await service.list_execution_audits(run_id)
            await uow.commit()
            return audits

    async def claim(
        self,
        run_id: str,
        *,
        actor_id: str,
        claimed_at: datetime,
    ) -> WorkflowRun:
        """Claim one queued run into running. Does not execute nodes."""

        self._ensure_open()
        async with WorkflowUnitOfWork(self._session_factory) as uow:
            service = WorkflowCommandService(
                registry=self._registry,
                repository=uow.workflows,
                run_ids=self._run_ids,
            )
            run = await service.claim(
                run_id,
                actor_id=actor_id,
                claimed_at=claimed_at,
            )
            await uow.commit()
            return run

    async def claim_next(
        self,
        *,
        actor_id: str,
        claimed_at: datetime,
    ) -> WorkflowRun | None:
        """Claim the oldest queued run, if any. Worker-oriented."""

        self._ensure_open()
        async with WorkflowUnitOfWork(self._session_factory) as uow:
            service = WorkflowCommandService(
                registry=self._registry,
                repository=uow.workflows,
                run_ids=self._run_ids,
            )
            run = await service.claim_next(
                actor_id=actor_id,
                claimed_at=claimed_at,
            )
            await uow.commit()
            return run

    def definition(self, workflow_key: str) -> WorkflowDefinition:
        """Return the registered definition used to calculate honest progress."""
        self._ensure_open()
        return self._registry.get(workflow_key)

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Shared session factory for co-located workers (same engine/pool)."""
        self._ensure_open()
        return self._session_factory

    @property
    def registry(self) -> FormalWorkflowRegistry:
        self._ensure_open()
        return self._registry

    def data_quality_port(
        self,
        *,
        owner_id: str = "pandadata-system",
    ) -> DataQualityWorkflowCreationPort:
        self._ensure_open()
        return DataQualityWorkflowCreationPort(
            commands=self,
            owner_id=owner_id,
        )

    async def close(self) -> None:
        if self._closed:
            return
        await self._engine.dispose()
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("workflow command runtime is closed")


def create_workflow_command_runtime_from_environment(
    *,
    database_url: str | None = None,
) -> WorkflowCommandRuntime:
    """Build the production runtime; a database URL is mandatory and explicit."""

    resolved_url = database_url or os.getenv(WORKFLOW_DATABASE_URL_ENV)
    if resolved_url is None or not resolved_url.strip():
        raise RuntimeError(
            f"{WORKFLOW_DATABASE_URL_ENV} is required for durable workflows"
        )
    engine, session_factory = create_workflow_session_factory(resolved_url.strip())
    return WorkflowCommandRuntime(
        engine=engine,
        session_factory=session_factory,
        registry=FormalWorkflowRegistry.build_default(),
    )


__all__ = [
    "WORKFLOW_DATABASE_URL_ENV",
    "WorkflowCommandRuntime",
    "create_workflow_command_runtime_from_environment",
]
