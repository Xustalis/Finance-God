"""Production composition root for durable workflow commands."""

from __future__ import annotations

import os
from types import TracebackType
from typing import Self
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, AsyncSession

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
)
from .workflow_registry import FormalWorkflowRegistry

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
    engine, session_factory = create_workflow_session_factory(
        resolved_url.strip()
    )
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
