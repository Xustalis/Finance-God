"""Stable application command for durable workflow creation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Protocol, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from finance_god.agents.contracts import WorkflowKey
from finance_god.domain.models import (
    AuditReference,
    VersionReference,
    WorkflowRun,
    WorkflowRunStatus,
)

from .workflow_registry import FormalWorkflowRegistry, FrozenModel


class WorkflowCreateCommand(FrozenModel):
    idempotency_key: str = Field(
        pattern=r"^[A-Za-z0-9_.:-]+$",
        min_length=8,
        max_length=160,
    )
    workflow_key: WorkflowKey
    request_intent: str = Field(min_length=1, max_length=500)
    owner_id: str = Field(min_length=1, max_length=160)
    scope: dict[str, str] = Field(default_factory=dict)
    input_versions: tuple[VersionReference, ...] = Field(min_length=1)
    requested_at: AwareDatetime
    permissions: tuple[str, ...] = ()
    task_plan_reference: VersionReference | None = None
    parent_run_id: str | None = Field(default=None, min_length=1, max_length=160)
    retry_mode: str | None = Field(default=None, pattern=r"^(full|resume_failed)$")
    resumed_from_node_id: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("scope", mode="before")
    @classmethod
    def normalize_scope(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ValueError("scope must be a string mapping")
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not isinstance(raw_value, str):
                raise ValueError("scope keys and values must be strings")
            key = raw_key.strip()
            item = raw_value.strip()
            if not key or not item or len(key) > 80 or len(item) > 500:
                raise ValueError("scope keys and values must be bounded non-blank text")
            if key in normalized:
                raise ValueError("scope keys conflict after normalization")
            normalized[key] = item
        return dict(sorted(normalized.items()))

    @model_validator(mode="after")
    def canonicalize_versions(self) -> Self:
        if self.requested_at.utcoffset() != timedelta(0):
            raise ValueError("requested_at must be UTC")
        ordered = tuple(
            sorted(
                self.input_versions,
                key=lambda item: (
                    item.object_type,
                    item.object_id,
                    item.version,
                ),
            )
        )
        if len(ordered) != len(set(ordered)):
            raise ValueError("input versions must be unique")
        if ordered != self.input_versions:
            raise ValueError("input versions must use canonical ordering")
        return self

    @property
    def request_hash(self) -> str:
        stable_semantics = self.model_dump(mode="json")
        stable_semantics.pop("requested_at")
        material = json.dumps(
            stable_semantics,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode()).hexdigest()


class WorkflowCreationReceipt(FrozenModel):
    run: WorkflowRun
    created: bool
    idempotency_key: str
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class WorkflowExecutionAudit(FrozenModel):
    event_type: str
    payload: dict[str, object]
    occurred_at: AwareDatetime


class WorkflowRunRepository(Protocol):
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
        audit_payload: dict[str, object],
        outbox_payload: dict[str, object],
        parent_run_id: str | None = None,
        retry_mode: str | None = None,
        resumed_from_node_id: str | None = None,
    ) -> tuple[WorkflowRun, bool]: ...

    async def get(self, run_id: str) -> WorkflowRun | None: ...

    async def get_owner_id(self, run_id: str) -> str | None: ...

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
        payload_json: dict[str, object],
        occurred_at: datetime,
        actor_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None: ...

    async def list_execution_audits(
        self,
        run_id: str,
    ) -> tuple: ...

    async def list_queued(
        self,
        *,
        limit: int = 1,
    ) -> tuple[tuple[str, str, str, str], ...]: ...

    async def get_record(self, run_id: str) -> dict[str, object] | None: ...

    async def list_records(
        self, *, owner_id: str, limit: int, cursor: str | None, status: str | None
    ) -> tuple[tuple[dict[str, object], ...], str | None]: ...


class WorkflowCommandPort(Protocol):
    async def create(
        self,
        command: WorkflowCreateCommand,
    ) -> WorkflowCreationReceipt: ...

    async def get(self, run_id: str) -> WorkflowRun | None: ...

    async def get_owner_id(self, run_id: str) -> str | None: ...

    async def list_execution_audits(
        self,
        run_id: str,
    ) -> tuple[WorkflowExecutionAudit, ...]: ...

    async def claim(
        self,
        run_id: str,
        *,
        actor_id: str,
        claimed_at: datetime,
    ) -> WorkflowRun: ...

    async def claim_next(
        self,
        *,
        actor_id: str,
        claimed_at: datetime,
    ) -> WorkflowRun | None: ...

    async def get_record(self, run_id: str) -> dict[str, object] | None: ...

    async def list_records(
        self, *, owner_id: str, limit: int, cursor: str | None, status: str | None
    ) -> tuple[tuple[dict[str, object], ...], str | None]: ...

    async def cancel(
        self, run_id: str, *, actor_id: str, cancelled_at: datetime
    ) -> WorkflowRun: ...

    async def retry(
        self,
        run_id: str,
        *,
        owner_id: str,
        idempotency_key: str,
        mode: str,
        requested_at: datetime,
    ) -> WorkflowCreationReceipt: ...


class RunIdFactory(Protocol):
    def new(self) -> str: ...


class WorkflowCommandService:
    def __init__(
        self,
        *,
        registry: FormalWorkflowRegistry,
        repository: WorkflowRunRepository,
        run_ids: RunIdFactory,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._run_ids = run_ids

    async def create(
        self,
        command: WorkflowCreateCommand,
    ) -> WorkflowCreationReceipt:
        definition = self._registry.get(command.workflow_key)
        run_id = self._run_ids.new()
        run = WorkflowRun(
            run_id=run_id,
            revision=1,
            status=WorkflowRunStatus.QUEUED,
            audit_reference=AuditReference(
                audit_id=f"workflow:{run_id}:queued:1",
                actor_id=command.owner_id,
                recorded_at=command.requested_at,
            ),
            input_versions=command.input_versions,
            invalidated_by_versions=(),
            workflow_key=definition.workflow_key.value,
            workflow_version=definition.version,
            trade_eligible=False,
            final_artifact=None,
            evidence_references=(),
            node_contribution_references=(),
            completed_node_artifacts=(),
            errors=(),
            permissions=command.permissions,
            block_reason=None,
            cancellation_reason=None,
        )
        persisted, created = await self._repository.create_queued(
            run=run,
            idempotency_key=command.idempotency_key,
            request_hash=command.request_hash,
            request_intent=command.request_intent,
            owner_id=command.owner_id,
            scope=command.scope,
            requested_at=command.requested_at,
            audit_payload={
                "correlation_id": f"workflow-create:{command.idempotency_key}",
                "causation_id": f"workflow-command:{command.request_hash[:32]}",
                "workflow_key": definition.workflow_key.value,
                "workflow_version": definition.version,
                "input_versions": [
                    item.model_dump(mode="json") for item in command.input_versions
                ],
                "task_plan_reference": (
                    None
                    if command.task_plan_reference is None
                    else command.task_plan_reference.model_dump(mode="json")
                ),
            },
            outbox_payload={
                "run_id": run_id,
                "workflow_key": definition.workflow_key.value,
                "status": WorkflowRunStatus.QUEUED.value,
            },
            parent_run_id=command.parent_run_id,
            retry_mode=command.retry_mode,
            resumed_from_node_id=command.resumed_from_node_id,
        )
        return WorkflowCreationReceipt(
            run=persisted,
            created=created,
            idempotency_key=command.idempotency_key,
            request_hash=command.request_hash,
        )

    async def get(self, run_id: str) -> WorkflowRun | None:
        return await self._repository.get(run_id)

    async def get_owner_id(self, run_id: str) -> str | None:
        return await self._repository.get_owner_id(run_id)

    async def get_record(self, run_id: str) -> dict[str, object] | None:
        return await self._repository.get_record(run_id)

    async def list_records(
        self, *, owner_id: str, limit: int, cursor: str | None, status: str | None
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        return await self._repository.list_records(
            owner_id=owner_id, limit=limit, cursor=cursor, status=status
        )

    async def cancel(
        self, run_id: str, *, actor_id: str, cancelled_at: datetime
    ) -> WorkflowRun:
        run = await self._repository.get(run_id)
        if run is None:
            raise LookupError("workflow run was not found")
        if run.status in {
            WorkflowRunStatus.CANCEL_REQUESTED,
            WorkflowRunStatus.CANCELLING,
            WorkflowRunStatus.CANCELLED,
        }:
            return run
        if run.status not in {WorkflowRunStatus.QUEUED, WorkflowRunStatus.RUNNING}:
            raise ValueError(f"workflow run cannot be cancelled from {run.status.value}")
        target = (
            WorkflowRunStatus.CANCELLED
            if run.status is WorkflowRunStatus.QUEUED
            else WorkflowRunStatus.CANCEL_REQUESTED
        )
        from finance_god.domain.models import WorkflowCancellationReason
        transitioned = run.transition(
            target,
            audit_reference=AuditReference(
                audit_id=f"workflow:{run_id}:cancel:{run.revision + 1}",
                actor_id=actor_id,
                recorded_at=cancelled_at,
            ),
            cancellation_reason=WorkflowCancellationReason.USER_PAUSED,
        )
        return await self._repository.compare_and_append(
            run=transitioned,
            expected_revision=run.revision,
            event_type="workflow_cancelled" if target is WorkflowRunStatus.CANCELLED else "workflow_cancel_requested",
            event_payload={"run_id": run_id, "status": target.value},
            outbox_topic=f"workflow.{target.value}",
        )

    async def retry(
        self,
        run_id: str,
        *,
        owner_id: str,
        idempotency_key: str,
        mode: str,
        requested_at: datetime,
    ) -> WorkflowCreationReceipt:
        record = await self._repository.get_record(run_id)
        run = await self._repository.get(run_id)
        if record is None or run is None or record["owner_id"] != owner_id:
            raise LookupError("workflow run was not found")
        if mode not in {"full", "resume_failed"}:
            raise ValueError("retry mode must be full or resume_failed")
        if mode == "resume_failed" and run.status not in {
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.TIMED_OUT,
            WorkflowRunStatus.ATTENTION_REQUIRED,
        }:
            raise ValueError("workflow run is not eligible to resume")
        audits = await self._repository.list_execution_audits(run_id)
        completed = {
            str(row.payload_json.get("node_id"))
            for row in audits
            if row.event_type == "node_attempt_completed"
        }
        failed = next(
            (
                str(row.payload_json.get("node_id"))
                for row in reversed(audits)
                if row.event_type in {"node_attempt_failed", "node_attempt_timed_out"}
            ),
            None,
        )
        if mode == "resume_failed" and (not completed or not failed):
            raise ValueError("completed node artifacts are insufficient to resume; use full retry")
        if mode == "resume_failed":
            current_definition = self._registry.get(WorkflowKey(run.workflow_key))
            if current_definition.version != run.workflow_version:
                raise ValueError("workflow version changed; use full retry")
        return await self.create(
            WorkflowCreateCommand(
                idempotency_key=idempotency_key,
                workflow_key=WorkflowKey(run.workflow_key),
                request_intent=str(record["request_intent"]),
                owner_id=owner_id,
                scope=dict(record["scope"]),
                input_versions=run.input_versions,
                requested_at=requested_at,
                parent_run_id=run_id,
                retry_mode=mode,
                resumed_from_node_id=failed if mode == "resume_failed" else None,
            )
        )

    async def list_execution_audits(
        self,
        run_id: str,
    ) -> tuple[WorkflowExecutionAudit, ...]:
        rows = await self._repository.list_execution_audits(run_id)
        return tuple(
            WorkflowExecutionAudit(
                event_type=row.event_type,
                payload=dict(row.payload_json),
                occurred_at=row.occurred_at,
            )
            for row in rows
        )

    async def claim(
        self,
        run_id: str,
        *,
        actor_id: str,
        claimed_at: datetime,
    ) -> WorkflowRun:
        """Transition a queued run to running via domain CAS. No node execution."""

        run = await self._repository.get(run_id)
        if run is None:
            raise LookupError("workflow run was not found")
        if run.status is not WorkflowRunStatus.QUEUED:
            if run.status is WorkflowRunStatus.RUNNING:
                return run
            raise ValueError(
                f"workflow run cannot be claimed from status {run.status.value}"
            )
        actor = actor_id.strip()
        if not actor:
            raise ValueError("actor_id is required to claim a workflow run")
        transitioned = run.transition(
            WorkflowRunStatus.RUNNING,
            audit_reference=AuditReference(
                audit_id=f"workflow:{run.run_id}:started:{run.revision + 1}",
                actor_id=actor,
                recorded_at=claimed_at,
            ),
        )
        return await self._repository.compare_and_append(
            run=transitioned,
            expected_revision=run.revision,
            event_type="workflow_started",
            event_payload={
                "run_id": run.run_id,
                "status": WorkflowRunStatus.RUNNING.value,
                "claimed_by": actor,
            },
            outbox_topic="workflow.started",
        )

    async def claim_next(
        self,
        *,
        actor_id: str,
        claimed_at: datetime,
    ) -> WorkflowRun | None:
        """Claim the oldest queued run, if any. Worker-oriented; no ownership filter."""

        queued = await self._repository.list_queued(limit=1)
        if not queued:
            return None
        run_id, _owner_id, _intent, _workflow_key = queued[0]
        return await self.claim(
            run_id,
            actor_id=actor_id,
            claimed_at=claimed_at,
        )


class DataQualityWorkflowCreationPort:
    """Small stable port for a PandaData adapter; contains no repository details."""

    def __init__(
        self,
        *,
        commands: WorkflowCommandPort,
        owner_id: str,
    ) -> None:
        self._commands = commands
        self._owner_id = owner_id

    async def create(
        self,
        *,
        workflow_key: WorkflowKey,
        stable_trigger_key: str,
        input_versions: tuple[VersionReference, ...],
        scope: dict[str, str],
        requested_at: datetime,
    ) -> WorkflowCreationReceipt:
        if workflow_key is not WorkflowKey.DATA_QUALITY_REVIEW:
            raise ValueError(
                "data-quality creation port only accepts data_quality_review"
            )
        return await self._commands.create(
            WorkflowCreateCommand(
                idempotency_key=stable_trigger_key,
                workflow_key=workflow_key,
                request_intent="PandaData quality gate requested diagnostic review.",
                owner_id=self._owner_id,
                scope=scope,
                input_versions=input_versions,
                requested_at=requested_at,
            )
        )
