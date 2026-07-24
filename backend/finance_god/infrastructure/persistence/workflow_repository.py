from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.domain import (
    ConcurrentCommandConflict,
    DomainInvariantViolation,
    WorkflowRun,
    WorkflowRunStatus,
)

from .workflow_models import (
    WorkflowAuditRow,
    WorkflowEventRow,
    WorkflowExecutionAuditRow,
    WorkflowOutboxRow,
    WorkflowRunRow,
)

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _required_text(value: str, field_name: str, *, max_length: int = 160) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be blank")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return normalized


class WorkflowRepository:
    """Async persistence for the authoritative domain WorkflowRun aggregate.

    Methods only flush. The owning async unit of work controls commit/rollback so
    projection, event, audit and outbox changes share one database transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._write_lock = asyncio.Lock()

    async def get(self, run_id: str) -> WorkflowRun | None:
        row = await self._session.get(WorkflowRunRow, run_id)
        return _workflow(row) if row is not None else None

    async def get_owner_id(self, run_id: str) -> str | None:
        row = await self._session.get(WorkflowRunRow, run_id)
        return None if row is None else row.owner_id

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
    ) -> tuple[WorkflowRun, bool]:
        """Create a queued run, or replay the stored run for the same request."""

        async with self._write_lock:
            return await self._create_queued_unlocked(
                run=run,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                request_intent=request_intent,
                owner_id=owner_id,
                scope=scope,
                requested_at=requested_at,
                audit_payload=audit_payload,
                outbox_payload=outbox_payload,
            )

    async def _create_queued_unlocked(
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
    ) -> tuple[WorkflowRun, bool]:
        if run.status is not WorkflowRunStatus.QUEUED:
            raise DomainInvariantViolation("create_queued requires a queued workflow")
        if run.revision != 1:
            raise DomainInvariantViolation(
                "a newly persisted workflow must have revision 1"
            )
        normalized_key = _required_text(idempotency_key, "idempotency_key")
        normalized_owner = _required_text(owner_id, "owner_id")
        normalized_scope = _canonical_scope(scope)
        normalized_intent = _required_text(
            request_intent,
            "request_intent",
            max_length=500,
        )
        normalized_hash = request_hash.strip().lower()
        if not _HASH_PATTERN.fullmatch(normalized_hash):
            raise ValueError("request_hash must be a lowercase SHA-256 hex digest")
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        correlation_id = _payload_text(audit_payload, "correlation_id")
        causation_id = _payload_text(audit_payload, "causation_id")
        stable_trigger_key = _stable_trigger_key(
            normalized_owner,
            normalized_key,
        )

        await self._lock_trigger(stable_trigger_key)
        prior = await self._row_by_idempotency(
            normalized_owner,
            normalized_key,
        )
        if prior is not None:
            return _replay(prior, normalized_hash), False
        if await self._session.get(WorkflowRunRow, run.run_id) is not None:
            raise DomainInvariantViolation(f"workflow run already exists: {run.run_id}")

        try:
            async with self._session.begin_nested():
                await self._insert_queued(
                    run,
                    stable_trigger_key=stable_trigger_key,
                    idempotency_key=normalized_key,
                    request_hash=normalized_hash,
                    request_intent=normalized_intent,
                    owner_id=normalized_owner,
                    scope=normalized_scope,
                    requested_at=requested_at,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    audit_payload=audit_payload,
                    outbox_payload=outbox_payload,
                )
        except IntegrityError:
            # A concurrent transaction may have won the unique idempotency key.
            prior = await self._row_by_idempotency(
                normalized_owner,
                normalized_key,
            )
            if prior is None:
                raise
            return _replay(prior, normalized_hash), False
        return run, True

    async def compare_and_append(
        self,
        *,
        run: WorkflowRun,
        expected_revision: int,
        event_type: str,
        event_payload: dict[str, object],
        outbox_topic: str,
    ) -> WorkflowRun:
        """CAS-write one revision and append its event/audit/outbox facts."""

        async with self._write_lock:
            return await self._compare_and_append_unlocked(
                run=run,
                expected_revision=expected_revision,
                event_type=event_type,
                event_payload=event_payload,
                outbox_topic=outbox_topic,
            )

    async def _compare_and_append_unlocked(
        self,
        *,
        run: WorkflowRun,
        expected_revision: int,
        event_type: str,
        event_payload: dict[str, object],
        outbox_topic: str,
    ) -> WorkflowRun:
        normalized_event_type = _required_text(
            event_type,
            "event_type",
            max_length=80,
        )
        audit_payload = {
            "correlation_id": f"workflow-run:{run.run_id}",
            "causation_id": run.audit_reference.audit_id,
            "event_type": normalized_event_type,
            **event_payload,
        }
        outbox_payload = {
            "topic": _required_text(outbox_topic, "outbox_topic"),
            **event_payload,
        }
        if expected_revision < 1 or run.revision != expected_revision + 1:
            raise DomainInvariantViolation(
                "workflow append requires exactly one new aggregate revision"
            )
        current = await self._session.get(WorkflowRunRow, run.run_id)
        if current is None:
            raise DomainInvariantViolation(f"workflow run not found: {run.run_id}")
        prior_status = current.status
        previous_event = await self._session.scalar(
            select(WorkflowEventRow)
            .where(WorkflowEventRow.run_id == run.run_id)
            .order_by(WorkflowEventRow.sequence.desc())
            .limit(1)
        )
        if previous_event is None:
            raise DomainInvariantViolation("workflow event chain is missing")

        state = _state(run)
        result = await self._session.execute(
            update(WorkflowRunRow)
            .where(
                WorkflowRunRow.run_id == run.run_id,
                WorkflowRunRow.revision == expected_revision,
            )
            .values(
                workflow_key=run.workflow_key,
                workflow_version=run.workflow_version,
                status=run.status.value,
                trade_eligible=run.trade_eligible,
                revision=run.revision,
                state_json=state,
                updated_at=run.audit_reference.recorded_at,
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise ConcurrentCommandConflict("workflow run revision changed")
        await self._append_revision_facts(
            run,
            event_type=normalized_event_type,
            prior_status=prior_status,
            correlation_id=_payload_text(audit_payload, "correlation_id"),
            causation_id=_payload_text(audit_payload, "causation_id"),
            previous_event_hash=previous_event.event_hash,
            state=state,
            audit_payload=audit_payload,
            outbox_payload=outbox_payload,
        )
        await self._session.flush()
        return run

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
    ) -> None:
        """Append execution audit without advancing WorkflowRun revision."""

        async with self._write_lock:
            await self._append_audit_unlocked(
                audit_id=audit_id,
                run_id=run_id,
                event_type=event_type,
                payload_json=payload_json,
                occurred_at=occurred_at,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )

    async def _append_audit_unlocked(
        self,
        *,
        audit_id: str,
        run_id: str,
        event_type: str,
        payload_json: Mapping[str, object],
        occurred_at: datetime,
        actor_id: str | None,
        correlation_id: str | None,
    ) -> None:
        normalized_audit_id = _required_text(audit_id, "audit_id")
        normalized_run_id = _required_text(run_id, "run_id")
        normalized_event_type = _required_text(
            event_type,
            "event_type",
            max_length=80,
        )
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if await self._session.get(WorkflowRunRow, normalized_run_id) is None:
            raise DomainInvariantViolation(
                f"workflow run not found: {normalized_run_id}"
            )
        self._session.add(
            WorkflowExecutionAuditRow(
                audit_id=normalized_audit_id,
                run_id=normalized_run_id,
                event_type=normalized_event_type,
                payload_json=_json_mapping(payload_json, "payload_json"),
                actor_id=(
                    None
                    if actor_id is None
                    else _required_text(actor_id, "actor_id")
                ),
                correlation_id=(
                    None
                    if correlation_id is None
                    else _required_text(correlation_id, "correlation_id")
                ),
                occurred_at=occurred_at,
            )
        )
        await self._session.flush()

    async def append(
        self,
        run: WorkflowRun,
        *,
        expected_revision: int,
        audit_payload: Mapping[str, object],
        outbox_payload: Mapping[str, object],
    ) -> WorkflowRun:
        """Compatibility alias for compare_and_append."""

        event_type_value = _payload_optional_text(
            audit_payload,
            "event_type",
        ) or _event_type(None, run.status.value)
        return await self.compare_and_append(
            run=run,
            expected_revision=expected_revision,
            event_type=event_type_value,
            event_payload=dict(audit_payload),
            outbox_topic=str(
                outbox_payload.get("topic", f"workflow.{event_type_value}")
            ),
        )

    async def list_events(self, run_id: str) -> tuple[WorkflowEventRow, ...]:
        return tuple(
            (
                await self._session.scalars(
                    select(WorkflowEventRow)
                    .where(WorkflowEventRow.run_id == run_id)
                    .order_by(WorkflowEventRow.sequence)
                )
            ).all()
        )

    async def list_audits(self, run_id: str) -> tuple[WorkflowAuditRow, ...]:
        return tuple(
            (
                await self._session.scalars(
                    select(WorkflowAuditRow)
                    .where(WorkflowAuditRow.run_id == run_id)
                    .order_by(WorkflowAuditRow.revision)
                )
            ).all()
        )

    async def list_execution_audits(
        self,
        run_id: str,
    ) -> tuple[WorkflowExecutionAuditRow, ...]:
        return tuple(
            (
                await self._session.scalars(
                    select(WorkflowExecutionAuditRow)
                    .where(WorkflowExecutionAuditRow.run_id == run_id)
                    .order_by(WorkflowExecutionAuditRow.occurred_at)
                )
            ).all()
        )

    async def list_outbox(self, run_id: str) -> tuple[WorkflowOutboxRow, ...]:
        return tuple(
            (
                await self._session.scalars(
                    select(WorkflowOutboxRow)
                    .where(WorkflowOutboxRow.aggregate_id == run_id)
                    .order_by(WorkflowOutboxRow.occurred_at)
                )
            ).all()
        )

    async def _insert_queued(
        self,
        run: WorkflowRun,
        *,
        stable_trigger_key: str,
        idempotency_key: str,
        request_hash: str,
        request_intent: str,
        owner_id: str,
        scope: str,
        requested_at: datetime,
        correlation_id: str,
        causation_id: str,
        audit_payload: Mapping[str, object],
        outbox_payload: Mapping[str, object],
    ) -> None:
        state = _state(run)
        occurred_at = run.audit_reference.recorded_at
        self._session.add(
            WorkflowRunRow(
                run_id=run.run_id,
                stable_trigger_key=stable_trigger_key,
                idempotency_key=idempotency_key,
                request_intent=request_intent,
                owner_id=owner_id,
                scope=scope,
                request_hash=request_hash,
                workflow_key=run.workflow_key,
                workflow_version=run.workflow_version,
                status=run.status.value,
                trade_eligible=run.trade_eligible,
                revision=run.revision,
                state_json=state,
                requested_at=requested_at,
                created_at=occurred_at,
                updated_at=occurred_at,
            )
        )
        await self._session.flush()
        await self._append_revision_facts(
            run,
            event_type="workflow_queued",
            prior_status=None,
            correlation_id=correlation_id,
            causation_id=causation_id,
            previous_event_hash=None,
            state=state,
            audit_payload=audit_payload,
            outbox_payload=outbox_payload,
        )
        await self._session.flush()

    async def _append_revision_facts(
        self,
        run: WorkflowRun,
        *,
        event_type: str,
        prior_status: str | None,
        correlation_id: str,
        causation_id: str,
        previous_event_hash: str | None,
        state: dict[str, object],
        audit_payload: Mapping[str, object],
        outbox_payload: Mapping[str, object],
    ) -> None:
        audit = run.audit_reference
        state_hash = _sha256(state)
        normalized_audit_payload = _json_mapping(
            audit_payload,
            "audit_payload",
        )
        normalized_outbox_payload = _json_mapping(
            outbox_payload,
            "outbox_payload",
        )
        event_material = {
            "run_id": run.run_id,
            "revision": run.revision,
            "event_type": event_type,
            "prior_status": prior_status,
            "status": run.status.value,
            "audit_id": audit.audit_id,
            "actor_id": audit.actor_id,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "previous_event_hash": previous_event_hash,
            "state_hash": state_hash,
            "audit_payload_hash": _sha256(normalized_audit_payload),
            "outbox_payload_hash": _sha256(normalized_outbox_payload),
            "occurred_at": audit.recorded_at.isoformat(),
        }
        event_hash = _sha256(event_material)
        event_id = _stable_id("workflow_event", event_hash)
        message_id = _stable_id("workflow_outbox", event_hash)
        self._session.add(
            WorkflowEventRow(
                event_id=event_id,
                run_id=run.run_id,
                sequence=run.revision,
                revision=run.revision,
                event_type=event_type,
                prior_status=prior_status,
                status=run.status.value,
                audit_id=audit.audit_id,
                actor_id=audit.actor_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                previous_event_hash=previous_event_hash,
                event_hash=event_hash,
                occurred_at=audit.recorded_at,
                state_json=state,
            )
        )
        await self._session.flush()
        self._session.add(
            WorkflowAuditRow(
                audit_id=audit.audit_id,
                run_id=run.run_id,
                event_id=event_id,
                revision=run.revision,
                action=event_type,
                actor_id=audit.actor_id,
                correlation_id=correlation_id,
                state_hash=state_hash,
                event_hash=event_hash,
                payload_json=normalized_audit_payload,
                occurred_at=audit.recorded_at,
            )
        )
        self._session.add(
            WorkflowOutboxRow(
                message_id=message_id,
                topic=f"workflow.{event_type}",
                aggregate_id=run.run_id,
                event_id=event_id,
                event_hash=event_hash,
                payload_json={
                    **normalized_outbox_payload,
                    "run_id": run.run_id,
                    "workflow_key": run.workflow_key,
                    "workflow_version": run.workflow_version,
                    "revision": run.revision,
                    "status": run.status.value,
                    "event_hash": event_hash,
                },
                occurred_at=audit.recorded_at,
                published_at=None,
            )
        )

    async def _row_by_idempotency(
        self,
        owner_id: str,
        idempotency_key: str,
    ) -> WorkflowRunRow | None:
        row: WorkflowRunRow | None = await self._session.scalar(
            select(WorkflowRunRow).where(
                WorkflowRunRow.owner_id == owner_id,
                WorkflowRunRow.idempotency_key == idempotency_key,
            )
        )
        return row

    async def _lock_trigger(self, stable_trigger_key: str) -> None:
        bind = self._session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": stable_trigger_key},
        )


def _workflow(row: WorkflowRunRow) -> WorkflowRun:
    return WorkflowRun.model_validate(row.state_json)


def _replay(row: WorkflowRunRow, request_hash: str) -> WorkflowRun:
    if row.request_hash != request_hash:
        raise DomainInvariantViolation(
            "idempotency key was already used with a different request"
        )
    return _workflow(row)


def _state(run: WorkflowRun) -> dict[str, object]:
    return run.model_dump(mode="json")


def _event_type(prior_status: str | None, status: str) -> str:
    if prior_status is None:
        return "workflow_created"
    if prior_status != status:
        return "workflow_status_changed"
    return "workflow_output_recorded"


def _stable_id(prefix: str, digest: str) -> str:
    return f"{prefix}_{digest[:32]}"


def _stable_trigger_key(owner_id: str, idempotency_key: str) -> str:
    return _stable_id(
        "workflow_trigger",
        _sha256(
            {
                "owner_id": owner_id,
                "idempotency_key": idempotency_key,
            }
        ),
    )


def _payload_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"audit_payload.{key} must be a string")
    return _required_text(value, f"audit_payload.{key}")


def _payload_optional_text(
    payload: Mapping[str, object],
    key: str,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"audit_payload.{key} must be a string")
    return _required_text(value, f"audit_payload.{key}")


def _canonical_scope(scope: Mapping[str, str]) -> str:
    if not isinstance(scope, dict):
        raise ValueError("scope must be a string mapping")
    normalized: dict[str, str] = {}
    for key, value in scope.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("scope keys and values must be strings")
        clean_key = _required_text(key, "scope key", max_length=80)
        clean_value = _required_text(value, "scope value", max_length=500)
        if clean_key in normalized:
            raise ValueError("scope keys conflict after normalization")
        normalized[clean_key] = clean_value
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_mapping(
    payload: Mapping[str, object],
    field_name: str,
) -> dict[str, Any]:
    normalized = dict(payload)
    try:
        json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be JSON serializable") from error
    return normalized


def _sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
