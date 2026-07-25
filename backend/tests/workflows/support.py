from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from finance_god.domain.models import WorkflowRun
from finance_god.domain import ActiveWorkflowConflict


class SequenceRunIds:
    def __init__(self) -> None:
        self.value = 0

    def new(self) -> str:
        self.value += 1
        return f"workflow-run-{self.value}"


class AdvancingClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 24, tzinfo=timezone.utc)

    def now(self) -> datetime:
        self.value += timedelta(microseconds=1)
        return self.value


class AsyncMemoryWorkflowRepository:
    """Protocol test double; persistence behavior has separate SQL tests."""

    def __init__(self) -> None:
        self.runs: dict[str, WorkflowRun] = {}
        self.owners: dict[str, str] = {}
        self.intents: dict[str, str] = {}
        self.requested_at: dict[str, datetime] = {}
        self.scopes: dict[str, dict[str, str]] = {}
        self.lineage: dict[str, tuple[str | None, str | None, str | None]] = {}
        self.keys: dict[str, tuple[str, str]] = {}
        self.events: list[tuple[str, int, str, dict[str, object]]] = []
        self.audits: list[tuple[str, str, dict[str, object], datetime]] = []
        self.outbox: list[tuple[str, str]] = []

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
    ) -> tuple[WorkflowRun, bool]:
        stable_key = self._stable_key(owner_id, idempotency_key)
        existing = self.keys.get(stable_key)
        if existing is not None:
            existing_hash, run_id = existing
            if existing_hash != request_hash:
                raise ValueError(
                    "idempotency key was already used with a different request"
                )
            return self.runs[run_id], False
        active = next(
            (
                active_run
                for active_run in self.runs.values()
                if self.owners[active_run.run_id] == owner_id
                and active_run.status.value
                in {"queued", "running", "cancel_requested", "cancelling"}
            ),
            None,
        )
        if active is not None:
            raise ActiveWorkflowConflict(active.run_id)
        self.keys[stable_key] = (request_hash, run.run_id)
        self.runs[run.run_id] = run
        self.owners[run.run_id] = owner_id
        self.intents[run.run_id] = request_intent
        self.requested_at[run.run_id] = requested_at
        self.scopes[run.run_id] = dict(scope)
        self.lineage[run.run_id] = (
            parent_run_id, retry_mode, resumed_from_node_id
        )
        self.events.append(
            (run.run_id, run.revision, "workflow_queued", audit_payload)
        )
        self.outbox.append((run.run_id, str(outbox_payload["status"])))
        return run, True

    async def get(self, run_id: str) -> WorkflowRun | None:
        return self.runs.get(run_id)

    async def get_owner_id(self, run_id: str) -> str | None:
        return self.owners.get(run_id)

    async def get_record(self, run_id: str) -> dict[str, object] | None:
        run = self.runs.get(run_id)
        if run is None:
            return None
        requested_at = self.requested_at[run_id]
        parent, retry_mode, resumed = self.lineage.get(run_id, (None, None, None))
        return {
            "run": run,
            "owner_id": self.owners[run_id],
            "request_intent": self.intents[run_id],
            "scope": self.scopes.get(run_id, {}),
            "requested_at": requested_at,
            "created_at": requested_at,
            "updated_at": run.audit_reference.recorded_at,
            "parent_run_id": parent,
            "retry_mode": retry_mode,
            "resumed_from_node_id": resumed,
        }

    async def list_records(
        self, *, owner_id: str, limit: int, cursor: str | None, status: str | None
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        del cursor
        records = [
            await self.get_record(run_id)
            for run_id, run in self.runs.items()
            if self.owners[run_id] == owner_id and (status is None or run.status.value == status)
        ]
        ordered = sorted(
            (item for item in records if item is not None),
            key=lambda item: (item["requested_at"], item["run"].run_id),
            reverse=True,
        )
        return tuple(ordered[:limit]), None

    async def compare_and_append(
        self,
        *,
        run: WorkflowRun,
        expected_revision: int,
        event_type: str,
        event_payload: dict[str, object],
        outbox_topic: str,
    ) -> WorkflowRun:
        current = self.runs[run.run_id]
        if current.revision != expected_revision:
            raise RuntimeError("workflow run revision changed")
        if run.revision != expected_revision + 1:
            raise ValueError("CAS append requires exactly one revision")
        self.runs[run.run_id] = run
        self.events.append(
            (run.run_id, run.revision, event_type, event_payload)
        )
        self.outbox.append((run.run_id, outbox_topic))
        return run

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
    ) -> None:
        del audit_id, actor_id, correlation_id
        if run_id not in self.runs:
            raise LookupError(run_id)
        self.audits.append((run_id, event_type, payload_json, occurred_at))

    async def list_execution_audits(self, run_id: str) -> tuple:
        return tuple(
            SimpleNamespace(
                event_type=event_type,
                payload_json=payload,
                occurred_at=occurred_at,
            )
            for audit_run_id, event_type, payload, occurred_at in self.audits
            if audit_run_id == run_id
        )

    async def list_queued(
        self,
        *,
        limit: int = 1,
    ) -> tuple[tuple[str, str, str, str], ...]:
        from finance_god.domain.models import WorkflowRunStatus

        bound = max(1, min(int(limit), 100))
        queued = [
            (
                run_id,
                self.owners[run_id],
                self.intents[run_id],
                run.workflow_key,
                self.requested_at.get(run_id),
            )
            for run_id, run in self.runs.items()
            if run.status is WorkflowRunStatus.QUEUED
        ]
        queued.sort(key=lambda item: (item[4] is None, item[4], item[0]))
        return tuple(
            (run_id, owner_id, intent, workflow_key)
            for run_id, owner_id, intent, workflow_key, _ in queued[:bound]
        )

    @staticmethod
    def _stable_key(
        owner_id: str,
        idempotency_key: str,
    ) -> str:
        return f"{owner_id}|{idempotency_key}"
