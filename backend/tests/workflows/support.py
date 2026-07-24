from __future__ import annotations

from datetime import datetime, timedelta, timezone

from finance_god.domain.models import WorkflowRun


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
    ) -> tuple[WorkflowRun, bool]:
        del request_intent, requested_at
        stable_key = self._stable_key(owner_id, idempotency_key)
        existing = self.keys.get(stable_key)
        if existing is not None:
            existing_hash, run_id = existing
            if existing_hash != request_hash:
                raise ValueError(
                    "idempotency key was already used with a different request"
                )
            return self.runs[run_id], False
        self.keys[stable_key] = (request_hash, run.run_id)
        self.runs[run.run_id] = run
        self.owners[run.run_id] = owner_id
        self.events.append(
            (run.run_id, run.revision, "workflow_queued", audit_payload)
        )
        self.outbox.append((run.run_id, str(outbox_payload["status"])))
        return run, True

    async def get(self, run_id: str) -> WorkflowRun | None:
        return self.runs.get(run_id)

    async def get_owner_id(self, run_id: str) -> str | None:
        return self.owners.get(run_id)

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

    @staticmethod
    def _stable_key(
        owner_id: str,
        idempotency_key: str,
    ) -> str:
        return f"{owner_id}|{idempotency_key}"
