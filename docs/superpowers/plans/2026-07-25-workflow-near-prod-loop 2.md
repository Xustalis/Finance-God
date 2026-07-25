# Workflow Near-Production Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the near-production workflow loop in four independently acceptable milestones: cancel (M1), run-events cursor (M2), multi-worker SKIP LOCKED lease (M3), Outbox → delivery → SSE (M4).

**Architecture:** Contract-first. Expose existing domain/persistence through public HTTP and desk capabilities; do not invent infra or fake FE progress. Cancel is cooperative at node boundaries via durable status (`cancel_requested` → `cancelling` → `cancelled`). Events use per-run `sequence`. SSE (M4) uses a separate per-owner `delivery_sequence` backed by `user_event_deliveries` filled from transactional outbox.

**Tech Stack:** Starlette/FastAPI routes, Pydantic 2, SQLAlchemy 2 async, Alembic, PostgreSQL 16, pytest, Vue 3 + Pinia + TypeScript, existing `WorkflowCommandService` / `WorkflowRepository` / `WorkflowWorker` / desk store.

**Spec:** `docs/superpowers/specs/2026-07-25-workflow-near-prod-loop-design.md` (commit `562a792`)

## Global Constraints

- Product loop first; no drive-by refactors outside milestone-touched paths.
- Cooperative cancel only (node boundaries); no preemptive mid-node kill.
- No PandaData credentials in browser; Agent cannot order submit/cancel/settings/DOM.
- Fail as stale/error — never fabricate prices, events, or terminal success.
- Toast ≠ durable read; finance workflow APIs return **raw JSON** (same as existing `/api/workflows/*`).
- Capabilities are sticky-false until the feature is actually wired and probed.
- Keep existing error envelope shape used by `workflow_routes.py`:
  `{"error": {"code": "<CODE>", "message": "..."}}` (nested). Use design codes: `WORKFLOW_TERMINAL`, `WORKFLOW_CONFLICT`, `NOT_FOUND`, `VALIDATION_ERROR`, `UNAUTHORIZED`, `WORKFLOW_RUNTIME_UNAVAILABLE`, `SSE_DISABLED`.
- First public cancel reason: `user_paused` (`WorkflowCancellationReason.USER_PAUSED`).
- Dual cursor namespaces: run `sequence` vs owner `delivery_sequence` — never mix.
- Server clock only for leases; no client-supplied lease time.
- Each milestone ends with: tests green, capabilities honest, docs (`README.md`, `docs/项目索引.md`, `docs/page-design/02_前后端职责与数据合同.md`) updated for that milestone only.
- Dirty working tree: touch only loop-related files; do not open a hygiene project.
- Do not start coding a later milestone until the previous milestone’s acceptance checklist in the design is met.

## File Map

### Shared / already present

- `backend/finance_god/domain/models.py` — `WorkflowRunStatus`, `WORKFLOW_RUN_TRANSITIONS`, `WorkflowRun.transition`, `WorkflowCancellationReason`
- `backend/finance_god/orchestration/workflow_commands.py` — `WorkflowCommandPort`, `WorkflowCommandService`, `WorkflowRunRepository` protocol
- `backend/finance_god/infrastructure/persistence/workflow_repository.py` — CAS + events/outbox
- `backend/finance_god/infrastructure/persistence/workflow_models.py` — `WorkflowRunRow`, `WorkflowEventRow`, `WorkflowOutboxRow`
- `backend/finance_god/orchestration/workflow_executor.py` — control-port cancel path; must also honor durable `cancel_requested`
- `backend/finance_god/application/workflow_worker.py` — `OpenControls` (always unpaused), claim loop
- `backend/finance_god/api/workflow_routes.py` — create/get/progress only today
- `backend/server.py` — `_desk_capability_probe`
- `backend/finance_god/api/desk_routes.py` — `_POLICY_CAPABILITIES` merge
- `frontend/src/services/tradingDesk.ts` — create/get/progress clients
- `frontend/src/stores/tradingDesk.ts` — poll progress ~2s; capability gates
- `frontend/src/components/desk/DeskAgentPanel.vue` — cancel labels exist; no cancel control
- `backend/tests/api/test_workflow_routes.py`, `backend/tests/workflows/support.py`, `backend/tests/workflows/test_executor.py`, `backend/tests/domain/test_state_machines.py`

### M1 adds/changes

- Domain transition `queued → cancelled`
- `WorkflowCommandPort.request_cancel` + service implementation
- Routes: `POST /workflows/{run_id}/cancel`
- Executor reload + honor `cancel_requested`/`cancelling`
- FE: `cancelWorkflow`, store action, panel button gated by `workflow_cancel`
- Capabilities: `workflow_cancel=true` when command port is live (same probe as create)

### M2 adds/changes

- `list_events(run_id, after_sequence=0, limit=50)` on repository + memory double
- `GET /workflows/{run_id}/events?cursor=&limit=`
- Public event DTO + type mapping
- FE: events poll + ledger; `workflow_events=true`

### M3 adds/changes

- Alembic `20260725_0015_workflow_leases` after `20260724_0014_market_monitor`
- Columns: `lease_owner`, `lease_until`, `lease_token` on `workflow_runs`
- `claim_with_lease` / SKIP LOCKED path; reclaim expired running leases
- `workflow_lease=true`; event `lease_reclaimed`

### M4 adds/changes

- Table `user_event_deliveries`
- Outbox publisher loop
- `GET /api/events` SSE + `GET /api/events/history`
- FE SSE-first with poll fallback; `events_sse=true`

---

# Milestone 1 — Cancel

### Task 1: Domain allows `queued → cancelled`

**Files:**
- Modify: `backend/finance_god/domain/models.py` (`WORKFLOW_RUN_TRANSITIONS`)
- Test: `backend/tests/domain/test_state_machines.py`

**Interfaces:**
- Consumes: existing `WorkflowRun.transition(..., cancellation_reason=...)`
- Produces: `WORKFLOW_RUN_TRANSITIONS[QUEUED]` includes `CANCELLED`

- [ ] **Step 1: Write the failing domain test**

Add to the workflow state machine tests (near existing cancel path tests ~line 541):

```python
def test_queued_workflow_can_cancel_with_reason(self) -> None:
    queued = WorkflowRun(
        run_id="run-queued-cancel",
        revision=1,
        status=WorkflowRunStatus.QUEUED,
        workflow_key="company_research",
        workflow_version="1",
        trade_eligible=False,
        final_artifact=None,
        evidence_references=(),
        node_contribution_references=(),
        completed_node_artifacts=(),
        errors=(),
        permissions=(),
        block_reason=None,
        cancellation_reason=None,
        input_versions=(INSTRUMENT,),
        audit_reference=audit(1),
    )
    cancelled = queued.transition(
        WorkflowRunStatus.CANCELLED,
        audit_reference=audit(2),
        cancellation_reason=WorkflowCancellationReason.USER_PAUSED,
    )
    self.assertEqual(cancelled.status, WorkflowRunStatus.CANCELLED)
    self.assertEqual(
        cancelled.cancellation_reason,
        WorkflowCancellationReason.USER_PAUSED,
    )
```

(Reuse the file’s existing fixtures: `audit`, `INSTRUMENT` — mirror names already in the test module.)

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/pytest tests/domain/test_state_machines.py::WorkflowRunStateMachineTest::test_queued_workflow_can_cancel_with_reason -v
```

Expected: FAIL with `InvalidStateTransition` (queued cannot go to cancelled).

- [ ] **Step 3: Minimal domain change**

In `WORKFLOW_RUN_TRANSITIONS`, extend queued targets:

```python
WorkflowRunStatus.QUEUED: frozenset(
    {
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.TIMED_OUT,
        WorkflowRunStatus.BLOCKED,
        WorkflowRunStatus.CANCELLED,
    }
),
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/pytest tests/domain/test_state_machines.py -q
```

Expected: PASS (no regressions on existing cancel path tests).

- [ ] **Step 5: Commit**

```bash
git add backend/finance_god/domain/models.py backend/tests/domain/test_state_machines.py
git commit -m "$(cat <<'EOF'
feat(domain): allow queued workflow cancel

Enable queued → cancelled so public cancel can terminate unclaimed runs.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `request_cancel` on command port + service

**Files:**
- Modify: `backend/finance_god/orchestration/workflow_commands.py`
- Test: `backend/tests/workflows/test_request_cancel.py` (create)
- Modify: `backend/tests/workflows/support.py` only if needed (no new methods required for cancel — uses `compare_and_append`)

**Interfaces:**
- Consumes: `WorkflowRunRepository.get`, `compare_and_append`; domain `transition`
- Produces:

```python
class WorkflowCommandPort(Protocol):
    # existing methods...
    async def request_cancel(
        self,
        run_id: str,
        *,
        actor_id: str,
        reason: WorkflowCancellationReason,
        requested_at: datetime,
        note: str | None = None,
    ) -> WorkflowRun: ...
```

Semantics (must match design §7.2):

| Current status | Result |
| --- | --- |
| `queued` | → `cancelled` + event `workflow_cancelled` + outbox `workflow.cancelled` |
| `running` | → `cancel_requested` + event `workflow_cancel_requested` + outbox `workflow.cancel_requested` |
| `cancel_requested` / `cancelling` / `cancelled` | return current run, no revision bump |
| other terminal (`completed`, `failed`, `timed_out`, `blocked`, `expired`, `attention_required`) | raise `WorkflowTerminalError` (new lightweight exception in this module or domain) |
| missing run | raise `LookupError` |
| CAS race | re-read once; if still conflict raise `ConcurrentCommandConflict` / existing revision error |

- [ ] **Step 1: Write failing unit tests**

Create `backend/tests/workflows/test_request_cancel.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tests.workflows.support import AsyncMemoryWorkflowRepository, SequenceRunIds

from finance_god.agents.contracts import WorkflowKey
from finance_god.domain.models import WorkflowCancellationReason, WorkflowRunStatus
from finance_god.orchestration.workflow_commands import (
    WorkflowCommandService,
    WorkflowCreateCommand,
    WorkflowTerminalError,  # introduce in implementation
)
from finance_god.orchestration.workflow_registry import FormalWorkflowRegistry


def _clock() -> datetime:
    return datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


async def _service() -> tuple[WorkflowCommandService, AsyncMemoryWorkflowRepository]:
    repo = AsyncMemoryWorkflowRepository()
    service = WorkflowCommandService(
        registry=FormalWorkflowRegistry.build_default(),
        repository=repo,
        run_ids=SequenceRunIds(),
    )
    return service, repo


async def _queued_run(service: WorkflowCommandService) -> str:
    receipt = await service.create(
        WorkflowCreateCommand(
            idempotency_key="cancel-test-0001",
            workflow_key=WorkflowKey.COMPANY_RESEARCH,
            request_intent="研究 600519.SH",
            owner_id="owner-1",
            scope={"symbol": "600519.SH"},
            input_versions=(
                # use VersionReference matching create validator ordering
                __import__(
                    "finance_god.domain.models", fromlist=["VersionReference"]
                ).VersionReference(
                    object_type="instrument_context",
                    object_id="600519.SH",
                    version="2026-07-25T09:30:00Z",
                ),
            ),
            requested_at=_clock(),
        )
    )
    return receipt.run.run_id


@pytest.mark.asyncio
async def test_cancel_queued_becomes_cancelled() -> None:
    service, repo = await _service()
    run_id = await _queued_run(service)
    cancelled = await service.request_cancel(
        run_id,
        actor_id="owner-1",
        reason=WorkflowCancellationReason.USER_PAUSED,
        requested_at=_clock() + timedelta(seconds=1),
        note="user stopped",
    )
    assert cancelled.status is WorkflowRunStatus.CANCELLED
    assert cancelled.cancellation_reason is WorkflowCancellationReason.USER_PAUSED
    assert any(e[2] == "workflow_cancelled" for e in repo.events if e[0] == run_id)


@pytest.mark.asyncio
async def test_cancel_running_becomes_cancel_requested() -> None:
    service, repo = await _service()
    run_id = await _queued_run(service)
    await service.claim(run_id, actor_id="worker-1", claimed_at=_clock() + timedelta(seconds=1))
    requested = await service.request_cancel(
        run_id,
        actor_id="owner-1",
        reason=WorkflowCancellationReason.USER_PAUSED,
        requested_at=_clock() + timedelta(seconds=2),
    )
    assert requested.status is WorkflowRunStatus.CANCEL_REQUESTED
    assert any(e[2] == "workflow_cancel_requested" for e in repo.events if e[0] == run_id)


@pytest.mark.asyncio
async def test_cancel_idempotent_on_cancel_path() -> None:
    service, _repo = await _service()
    run_id = await _queued_run(service)
    first = await service.request_cancel(
        run_id,
        actor_id="owner-1",
        reason=WorkflowCancellationReason.USER_PAUSED,
        requested_at=_clock() + timedelta(seconds=1),
    )
    second = await service.request_cancel(
        run_id,
        actor_id="owner-1",
        reason=WorkflowCancellationReason.USER_PAUSED,
        requested_at=_clock() + timedelta(seconds=2),
    )
    assert first.revision == second.revision
    assert second.status is WorkflowRunStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_terminal_completed_raises() -> None:
    service, repo = await _service()
    run_id = await _queued_run(service)
    run = await service.get(run_id)
    assert run is not None
    # Force a terminal non-cancel status via direct CAS for the test double:
    from finance_god.domain.models import AuditReference, VersionReference

    completed = run.transition(
        WorkflowRunStatus.RUNNING,
        audit_reference=AuditReference(
            audit_id=f"workflow:{run_id}:started:2",
            actor_id="worker",
            recorded_at=_clock() + timedelta(seconds=1),
        ),
    )
    completed = await repo.compare_and_append(
        run=completed,
        expected_revision=run.revision,
        event_type="workflow_started",
        event_payload={"run_id": run_id},
        outbox_topic="workflow.started",
    )
    # complete with artifact
    artifact = VersionReference(
        object_type="EvidenceBundle", object_id=run_id, version="1"
    )
    done = completed.transition(
        WorkflowRunStatus.COMPLETED,
        audit_reference=AuditReference(
            audit_id=f"workflow:{run_id}:completed:3",
            actor_id="worker",
            recorded_at=_clock() + timedelta(seconds=2),
        ),
        trade_eligible=False,
        final_artifact=artifact,
    )
    await repo.compare_and_append(
        run=done,
        expected_revision=completed.revision,
        event_type="workflow_completed",
        event_payload={"run_id": run_id},
        outbox_topic="workflow.completed",
    )
    with pytest.raises(WorkflowTerminalError):
        await service.request_cancel(
            run_id,
            actor_id="owner-1",
            reason=WorkflowCancellationReason.USER_PAUSED,
            requested_at=_clock() + timedelta(seconds=3),
        )
```

Adjust fixture construction if `WorkflowRun` construction helpers already exist in the suite — prefer the create/claim path above over hand-built aggregates when possible. If completing a run in the terminal test is too heavy, claim then force `FAILED` via the same transition pattern used in domain tests (FAILED needs no final artifact).

Simpler terminal variant:

```python
# after claim → running, transition to FAILED with errors=...
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/workflows/test_request_cancel.py -v
```

Expected: FAIL — `request_cancel` / `WorkflowTerminalError` missing.

- [ ] **Step 3: Implement exception + port + service**

In `workflow_commands.py`:

```python
class WorkflowTerminalError(ValueError):
    """Run is in a terminal status that cannot accept cancel."""


class WorkflowCommandPort(Protocol):
    # ...existing...
    async def request_cancel(
        self,
        run_id: str,
        *,
        actor_id: str,
        reason: WorkflowCancellationReason,
        requested_at: datetime,
        note: str | None = None,
    ) -> WorkflowRun: ...
```

Implement on `WorkflowCommandService`:

```python
_CANCEL_PATH = frozenset(
    {
        WorkflowRunStatus.CANCEL_REQUESTED,
        WorkflowRunStatus.CANCELLING,
        WorkflowRunStatus.CANCELLED,
    }
)
_NON_CANCEL_TERMINAL = frozenset(
    {
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.ATTENTION_REQUIRED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.TIMED_OUT,
        WorkflowRunStatus.BLOCKED,
        WorkflowRunStatus.EXPIRED,
    }
)

async def request_cancel(
    self,
    run_id: str,
    *,
    actor_id: str,
    reason: WorkflowCancellationReason,
    requested_at: datetime,
    note: str | None = None,
) -> WorkflowRun:
    actor = actor_id.strip()
    if not actor:
        raise ValueError("actor_id is required")
    run = await self._repository.get(run_id)
    if run is None:
        raise LookupError("workflow run was not found")
    if run.status in _CANCEL_PATH:
        return run
    if run.status in _NON_CANCEL_TERMINAL:
        raise WorkflowTerminalError(
            f"workflow run is already {run.status.value}"
        )
    if run.status is WorkflowRunStatus.QUEUED:
        target = WorkflowRunStatus.CANCELLED
        event_type = "workflow_cancelled"
        outbox_topic = "workflow.cancelled"
    elif run.status is WorkflowRunStatus.RUNNING:
        target = WorkflowRunStatus.CANCEL_REQUESTED
        event_type = "workflow_cancel_requested"
        outbox_topic = "workflow.cancel_requested"
    else:
        raise WorkflowTerminalError(
            f"workflow run cannot be cancelled from status {run.status.value}"
        )
    transitioned = run.transition(
        target,
        audit_reference=AuditReference(
            audit_id=f"workflow:{run.run_id}:{target.value}:{run.revision + 1}",
            actor_id=actor,
            recorded_at=requested_at,
        ),
        cancellation_reason=reason,
    )
    payload: dict[str, object] = {
        "run_id": run.run_id,
        "from_status": run.status.value,
        "to_status": target.value,
        "cancellation_reason": reason.value,
    }
    if note:
        payload["note"] = note[:500]
    try:
        return await self._repository.compare_and_append(
            run=transitioned,
            expected_revision=run.revision,
            event_type=event_type,
            event_payload=payload,
            outbox_topic=outbox_topic,
        )
    except RuntimeError:
        # CAS conflict: re-read and re-evaluate once
        latest = await self._repository.get(run_id)
        if latest is None:
            raise LookupError("workflow run was not found") from None
        if latest.status in _CANCEL_PATH:
            return latest
        if latest.status in _NON_CANCEL_TERMINAL:
            raise WorkflowTerminalError(
                f"workflow run is already {latest.status.value}"
            ) from None
        raise ConcurrentCommandConflict(
            "workflow run revision changed during cancel"
        ) from None
```

Import `WorkflowCancellationReason`, `AuditReference`, `ConcurrentCommandConflict` as needed. If `ConcurrentCommandConflict` is only raised from domain CAS helpers, map the memory double’s `RuntimeError("workflow run revision changed")` consistently with existing claim/create error handling.

Also update `claim` so that a run already in cancel path cannot be claimed:

```python
if run.status is not WorkflowRunStatus.QUEUED:
    if run.status is WorkflowRunStatus.RUNNING:
        return run
    raise ValueError(
        f"workflow run cannot be claimed from status {run.status.value}"
    )
```

(Already correct — cancelled is not queued.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/workflows/test_request_cancel.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/finance_god/orchestration/workflow_commands.py \
  backend/tests/workflows/test_request_cancel.py
git commit -m "$(cat <<'EOF'
feat(workflow): add request_cancel command

Queued runs cancel immediately; running runs enter cancel_requested.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Executor honors durable `cancel_requested` at node boundaries

**Files:**
- Modify: `backend/finance_god/orchestration/workflow_executor.py` (`_apply_runtime_control` / `_execute_dag`)
- Test: `backend/tests/workflows/test_executor.py`

**Interfaces:**
- Consumes: `repository.get` / `_require_run`
- Produces: if persisted status is `cancel_requested`, drive `cancelling` → `cancelled` (keep artifacts); if already `cancelling`, finish to `cancelled`; if already terminal cancel, return

Why: production `OpenControls` always returns unpaused. Public cancel writes status in DB; executor must reload and honor it, not only the in-memory control port.

- [ ] **Step 1: Write failing executor test**

```python
async def test_durable_cancel_requested_stops_further_nodes(self) -> None:
    run_id = await self.make_run(
        WorkflowKey.COMPANY_RESEARCH,
        suffix="durable-cancel",
    )
    plan = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="durable-cancel")
    # Flip to cancel_requested after claim-equivalent running start by mutating repo mid-flight.
    # Use a runner that, on first node, writes cancel_requested into the repository.
    class CancelAfterFirst(GovernedRunner):
        def __init__(self, repository, outer):
            super().__init__()
            self._repository = repository
            self._outer = outer
            self._flipped = False

        async def run(self, node, context):
            outcome = await super().run(node, context)
            if not self._flipped:
                self._flipped = True
                current = await self._repository.get(context.run_id)
                requested = current.transition(
                    WorkflowRunStatus.CANCEL_REQUESTED,
                    audit_reference=self._outer._audit(current, "cancel_requested"),
                    cancellation_reason=WorkflowCancellationReason.USER_PAUSED,
                )
                await self._repository.compare_and_append(
                    run=requested,
                    expected_revision=current.revision,
                    event_type="workflow_cancel_requested",
                    event_payload={"run_id": context.run_id},
                    outbox_topic="workflow.cancel_requested",
                )
            return outcome

    # Prefer a cleaner approach if make_run/executor helpers expose repository:
    # After starting execute is hard mid-flight; instead pre-start running then
    # set cancel_requested before execute's DAG loop by claiming first.
```

Prefer this clearer variant that matches existing patterns:

```python
async def test_reloaded_cancel_requested_completes_cancel_protocol(self) -> None:
    run_id = await self.make_run(WorkflowKey.COMPANY_RESEARCH, suffix="reload-cancel")
    plan = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="reload-cancel")
    # Move to running via repository the same way claim does
    run = await self.repository.get(run_id)
    running = run.transition(
        WorkflowRunStatus.RUNNING,
        audit_reference=self.executor(GovernedRunner())._audit(run, "started"),
    )
    # If _audit is private, use AuditReference directly like other tests.
```

Use the same `AuditReference` pattern as `test_request_cancel`. Concrete recommended test:

1. Create queued run via `make_run`.
2. CAS to `RUNNING`.
3. CAS to `CANCEL_REQUESTED` with `USER_PAUSED`.
4. Call `executor(GovernedRunner()).execute(run_id=..., plan=...)`.
5. Assert final status `CANCELLED`, events include `workflow_cancelling` and `workflow_cancelled`, and `runner.calls` is empty or partial only if execute still walks DAG — with reload at loop start, zero further nodes after cancel_requested.

If `execute` requires status `QUEUED` or `RUNNING` at entry: after cancel_requested it should either short-circuit or finish cancel protocol without executing nodes.

Also keep existing `test_runtime_pause_uses_cancellation_protocol` green (control-port path).

- [ ] **Step 2: Run test — expect FAIL** (executor ignores durable cancel and may raise `workflow run is not executable` or continue running).

```bash
cd backend && .venv/bin/pytest tests/workflows/test_executor.py -k reload_cancel -v
```

- [ ] **Step 3: Implement reload + honor in executor**

In `_execute_dag`, at the top of the `while pending:` loop **before** control-port checks:

```python
# Reload durable status so public cancel is visible mid-run.
run = await self._require_run(run.run_id)
if run.status is WorkflowRunStatus.CANCEL_REQUESTED:
    run = await self._transition(
        run,
        WorkflowRunStatus.CANCELLING,
        event_type="workflow_cancelling",
        cancellation_reason=run.cancellation_reason
        or WorkflowCancellationReason.USER_PAUSED,
    )
    return await self._transition(
        run,
        WorkflowRunStatus.CANCELLED,
        event_type="workflow_cancelled",
        cancellation_reason=run.cancellation_reason
        or WorkflowCancellationReason.USER_PAUSED,
    )
if run.status is WorkflowRunStatus.CANCELLING:
    return await self._transition(
        run,
        WorkflowRunStatus.CANCELLED,
        event_type="workflow_cancelled",
        cancellation_reason=run.cancellation_reason
        or WorkflowCancellationReason.USER_PAUSED,
    )
if run.status is not WorkflowRunStatus.RUNNING:
    return run
```

Also at the start of `execute`, after plan validation, if status is already `CANCEL_REQUESTED`/`CANCELLING`/`CANCELLED`, finish or return without raising “not executable”.

Keep the existing control-port path for pause tests.

- [ ] **Step 4: Run executor tests**

```bash
cd backend && .venv/bin/pytest tests/workflows/test_executor.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/finance_god/orchestration/workflow_executor.py \
  backend/tests/workflows/test_executor.py
git commit -m "$(cat <<'EOF'
feat(workflow): honor durable cancel_requested at node boundaries

Reload run status each DAG iteration so public cancel stops further nodes.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: HTTP `POST /workflows/{run_id}/cancel`

**Files:**
- Modify: `backend/finance_god/api/workflow_routes.py`
- Test: `backend/tests/api/test_workflow_routes.py`

**Interfaces:**
- Consumes: `commands.request_cancel`, `_owned_run` ownership rules
- Produces: route registered; request body model; error mapping for `WorkflowTerminalError` → 409 `WORKFLOW_TERMINAL`

Request model:

```python
class WorkflowCancelRequest(APIModel):
    reason: Literal["user_paused"] = "user_paused"
    note: str | None = Field(default=None, max_length=500)
```

Handler sketch:

```python
async def cancel(request: Request) -> JSONResponse:
    try:
        owner_id = await _owner(owner_resolver, request)
        run_id = request.path_params["run_id"]
        # ownership 404 before body semantics
        await _owned_run(commands_provider(), owner_id, run_id)
        raw = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        payload = WorkflowCancelRequest.model_validate(raw or {})
        run = await commands_provider().request_cancel(
            run_id,
            actor_id=owner_id,
            reason=WorkflowCancellationReason(payload.reason),
            requested_at=clock(),
            note=payload.note,
        )
        return _json(run)
    except Exception as error:
        return _error_response(error)
```

In `_error_response`:

```python
if isinstance(error, WorkflowTerminalError):
    return _error("WORKFLOW_TERMINAL", str(error), 409)
```

Optional: map CAS to `WORKFLOW_CONFLICT` (design name) while keeping legacy `CONFLICT` only if tests require — prefer adding `WORKFLOW_CONFLICT` for cancel-path concurrency and leave existing create codes alone.

Register:

```python
Route("/workflows/{run_id:str}/cancel", cancel, methods=["POST"]),
```

- [ ] **Step 1: Write failing API tests** in `test_workflow_routes.py`:

```python
def test_cancel_queued_run() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)
    created = client.post("/workflows", json=_create_payload(), headers=_headers("c1"))
    run_id = created.json()["run_id"]
    cancelled = client.post(
        f"/workflows/{run_id}/cancel",
        json={"reason": "user_paused", "note": "stop"},
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert body["cancellation_reason"] == "user_paused"


def test_cancel_running_run_is_cancel_requested() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)
    created = client.post("/workflows", json=_create_payload(), headers=_headers("c2"))
    run_id = created.json()["run_id"]
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        commands.claim(run_id, actor_id="worker-1", claimed_at=datetime(2026, 7, 25, 0, 0, 1, tzinfo=UTC))
    )
    # Prefer a small helper if the suite already has async runners; otherwise use
    # anyio/pytest-asyncio style consistent with the file (this file is sync TestClient).
    # If claim from sync tests is awkward, expose a test-only force via repository CAS
    # through commands.repository if accessible, or add a sync helper in the test module.

def test_cancel_other_owners_run_is_404() -> None:
    ...


def test_cancel_completed_is_409_terminal() -> None:
    ...


def test_cancel_idempotent() -> None:
    ...
```

For sync claim in this file, use:

```python
import anyio
anyio.run(commands.claim, run_id, actor_id="worker-1", claimed_at=...)
# or
from starlette.concurrency import run_in_threadpool  # not for coroutines
```

Simplest: `asyncio.run(commands.claim(...))` in the test (Python 3.11+ fine in pytest).

- [ ] **Step 2: Run — expect FAIL (404 route missing)**

```bash
cd backend && .venv/bin/pytest tests/api/test_workflow_routes.py -k cancel -v
```

- [ ] **Step 3: Implement route + error mapping**

- [ ] **Step 4: Run full workflow route tests**

```bash
cd backend && .venv/bin/pytest tests/api/test_workflow_routes.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/finance_god/api/workflow_routes.py backend/tests/api/test_workflow_routes.py
git commit -m "$(cat <<'EOF'
feat(api): expose POST /workflows/{id}/cancel

Owner-scoped cancel with terminal 409 and cross-user 404.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Capabilities `workflow_cancel` + FE cancel control

**Files:**
- Modify: `backend/server.py` (`_desk_capability_probe`)
- Modify: `backend/finance_god/api/desk_routes.py` if policy defaults need the key present as false
- Modify: `frontend/src/services/tradingDesk.ts`
- Modify: `frontend/src/stores/tradingDesk.ts`
- Modify: `frontend/src/components/desk/DeskAgentPanel.vue`
- Test: `backend/tests/api/test_workspace_routes.py` or desk bootstrap tests if they assert capability keys; FE: add/adjust unit test only if the project already has desk store tests — otherwise manual checklist in Step 4

**Interfaces:**
- Produces: `capabilities.workflow_cancel === true` when `workflow_create` probe succeeds (same durable runtime gate)
- Produces FE:

```typescript
export async function cancelWorkflow(
  runId: string,
  input: { reason?: 'user_paused'; note?: string } = {},
): Promise<DeskWorkflowRun> {
  return request(() =>
    client.post(`/workflows/${encodeURIComponent(runId)}/cancel`, {
      reason: input.reason ?? 'user_paused',
      note: input.note,
    }),
  )
}
```

Store:

```typescript
async function cancelActiveWorkflow() {
  if (!activeWorkflow.value) return
  if (!isDeskCapabilityEnabled(deskCapabilities.value, 'workflow_cancel')) {
    workflowError.value = '服务端未确认可取消工作流。'
    return
  }
  const runId = activeWorkflow.value.run_id
  try {
    activeWorkflow.value = await cancelWorkflow(runId)
    await refreshWorkflow()
    if (activeWorkflow.value && ACTIVE_WORKFLOW_STATUSES.has(activeWorkflow.value.status)) {
      startWorkflowPolling()
    }
  } catch (error) {
    workflowError.value = failureText(error, '取消工作流失败')
  }
}
```

Export `cancelActiveWorkflow` from the store.

Panel: show cancel button when `workflowCancelReady && ACTIVE` statuses (`queued|running|cancel_requested|cancelling` — disable only when already `cancelled` or other terminal). Label: `取消任务`. Gate with `isDeskCapabilityEnabled(..., 'workflow_cancel')`.

Capability probe return add:

```python
"workflow_cancel": workflow_create,  # same live port
"workflow_events": False,
"workflow_lease": False,
"events_sse": False,
```

- [ ] **Step 1: Backend test that bootstrap/capabilities include `workflow_cancel: true` when runtime is up** (extend existing desk bootstrap test if present; else assert via unit of probe by importing server helper carefully — prefer route-level test already used for capabilities).

- [ ] **Step 2: Implement probe + FE service/store/panel**

- [ ] **Step 3: Run backend capability-related tests**

```bash
cd backend && .venv/bin/pytest tests/api/test_workspace_routes.py tests/api/test_workflow_routes.py -q
```

- [ ] **Step 4: Manual FE checklist (document in commit body if no vitest)**
  - Cancel button hidden when capability false
  - Cancel on queued shows `已取消`
  - Cancel on running shows `请求取消` then progresses when worker honors

- [ ] **Step 5: Docs for M1**

Update only the “not online” → online lines for cancel:

- `README.md` — cancel API is online; events/lease/SSE still not
- `docs/项目索引.md` — list `POST .../cancel`
- `docs/page-design/02_前后端职责与数据合同.md` — cancel contract + cooperative semantics

- [ ] **Step 6: Commit**

```bash
git add backend/server.py backend/finance_god/api/desk_routes.py \
  frontend/src/services/tradingDesk.ts frontend/src/stores/tradingDesk.ts \
  frontend/src/components/desk/DeskAgentPanel.vue \
  README.md docs/项目索引.md docs/page-design/02_前后端职责与数据合同.md
git commit -m "$(cat <<'EOF'
feat(desk): wire workflow cancel capability and Agent control

Gate cancel on live workflow_cancel flag; sync docs for M1.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: M1 acceptance gate

- [ ] **Step 1: Run focused regression**

```bash
cd backend && .venv/bin/pytest \
  tests/domain/test_state_machines.py \
  tests/workflows/test_request_cancel.py \
  tests/workflows/test_executor.py \
  tests/api/test_workflow_routes.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Tick design M1 checklist** (in PR description, not necessarily in the design file):

- `POST /workflows/{id}/cancel` live; `workflow_cancel=true`
- queued → cancelled; running → cancel_requested → (worker/executor) → cancelled
- terminal 409; cross-user 404; idempotent 200
- persisted node artifacts retained
- Desk cancel control + status copy
- pytest: API + worker collaboration

- [ ] **Step 3: Stop** — do not start M2 until user accepts M1 or plan continues by agreement.

---

# Milestone 2 — Events cursor

### Task 7: Repository `list_events` with cursor + limit

**Files:**
- Modify: `backend/finance_god/infrastructure/persistence/workflow_repository.py`
- Modify: `backend/tests/workflows/support.py` (`AsyncMemoryWorkflowRepository`)
- Modify: `backend/tests/workflow_persistence/test_repository.py` (and memory unit tests)
- Optional protocol note: events listing is query-side; may live on repository without being on `WorkflowCommandPort` if routes use UoW/repository provider — **prefer** adding `list_events` to a small query method on the command service or a dedicated provider already used by routes.

**Decision (lock in):** Add to `WorkflowCommandPort`:

```python
async def list_events(
    self,
    run_id: str,
    *,
    after_sequence: int = 0,
    limit: int = 50,
) -> tuple[WorkflowEventView, ...]: ...
```

Define a frozen view DTO in `workflow_commands.py` or `workflow_routes.py`:

```python
class WorkflowEventView(FrozenModel):
    event_id: str
    sequence: int
    revision: int
    event_type: str  # public mapped type
    occurred_at: datetime
    payload: dict[str, object]
```

Repository method (SQL):

```python
async def list_events(
    self,
    run_id: str,
    *,
    after_sequence: int = 0,
    limit: int = 50,
) -> tuple[WorkflowEventRow, ...]:
    bound = max(1, min(int(limit), 200))
    after = max(0, int(after_sequence))
    rows = (
        await self._session.scalars(
            select(WorkflowEventRow)
            .where(
                WorkflowEventRow.run_id == run_id,
                WorkflowEventRow.sequence > after,
            )
            .order_by(WorkflowEventRow.sequence.asc())
            .limit(bound)
        )
    ).all()
    return tuple(rows)
```

Memory double: store sequence integers (today memory stores revision as second tuple field — extend to track real sequence counter per run when appending events).

**Important:** `AsyncMemoryWorkflowRepository.events` currently stores `(run_id, revision, event_type, payload)`. Extend to `(run_id, sequence, revision, event_type, payload)` **or** add parallel `event_rows` list used by `list_events`. Update all test readers of `.events` accordingly (grep and fix).

Public type mapping function:

```python
_PUBLIC_EVENT_TYPES = {
    "workflow_queued": "run_created",
    "workflow_started": "run_claimed",
    "workflow_cancel_requested": "status_changed",
    "workflow_cancelling": "status_changed",
    "workflow_cancelled": "run_cancelled",
    "workflow_completed": "status_changed",
    "node_started": "node_started",
    "node_completed": "node_completed",
    "node_attempt_failed": "node_failed",
    "lease_reclaimed": "lease_reclaimed",
}
```

Unknown internal types: either skip or pass through only if already recorded — M2 minimum is status/cancel complete; do not fabricate node events.

- [ ] **Step 1: Failing repository / memory tests for `after_sequence` and `limit`**
- [ ] **Step 2: Implement SQL + memory**
- [ ] **Step 3: Pass tests**
- [ ] **Step 4: Commit** `feat(workflow): list events by sequence cursor`

---

### Task 8: `GET /workflows/{run_id}/events`

**Files:**
- Modify: `backend/finance_god/api/workflow_routes.py`
- Test: `backend/tests/api/test_workflow_routes.py`

Response model:

```python
class WorkflowEventsResponse(APIModel):
    run_id: str
    events: tuple[WorkflowEventResponse, ...]
    next_cursor: int
    has_more: bool

class WorkflowEventResponse(APIModel):
    event_id: str
    sequence: int
    revision: int
    event_type: str
    occurred_at: datetime
    payload: dict[str, object]
```

Query params: `cursor` default 0, `limit` default 50 max 200.

Rules from design:

- `sequence > cursor`, ascending
- empty page: `next_cursor = cursor`
- non-empty: `next_cursor = last.sequence`
- `has_more` true if page length == limit (or probe limit+1)

- [ ] **Step 1: Failing API tests** — create run, cancel, list events from 0 and resume from `next_cursor`; cross-user 404
- [ ] **Step 2: Implement route**
- [ ] **Step 3: Pass**
- [ ] **Step 4: Commit** `feat(api): GET /workflows/{id}/events cursor read`

---

### Task 9: FE event ledger + `workflow_events` capability

**Files:**
- `backend/server.py` — set `workflow_events` true when runtime live (same as cancel/create)
- `frontend/src/services/tradingDesk.ts` — `fetchWorkflowEvents(runId, cursor, limit)`
- `frontend/src/stores/tradingDesk.ts` — poll events ~1–2s while active; stop when `document.hidden`; keep progress poll
- `frontend/src/components/desk/DeskAgentPanel.vue` — simple event list (sequence + type + time)
- Docs: README / 项目索引 / data contract for events

Store fields:

```typescript
const workflowEvents = ref<DeskWorkflowEvent[]>([])
const workflowEventsCursor = ref(0)
```

On refresh / poll:

```typescript
if (isDeskCapabilityEnabled(deskCapabilities.value, 'workflow_events') && activeWorkflow.value) {
  const page = await fetchWorkflowEvents(activeWorkflow.value.run_id, workflowEventsCursor.value)
  if (page.events.length) {
    workflowEvents.value = [...workflowEvents.value, ...page.events]
    workflowEventsCursor.value = page.next_cursor
  }
}
```

Reset cursor when starting a new workflow.

- [ ] **Steps:** failing capability assertion → implement → docs → commit `feat(desk): poll workflow events ledger`

---

### Task 10: M2 acceptance gate

```bash
cd backend && .venv/bin/pytest tests/api/test_workflow_routes.py tests/workflow_persistence/test_repository.py tests/workflows/ -q
```

Design checklist: cursor resume, status/cancel events, panel ledger, progress still available, `workflow_events=true`.

---

# Milestone 3 — Lease / SKIP LOCKED

### Task 11: Alembic lease columns

**Files:**
- Create: `backend/alembic/versions/20260725_0015_workflow_leases.py`
- Modify: `backend/finance_god/infrastructure/persistence/workflow_models.py` (`WorkflowRunRow`)
- Test: `backend/tests/workflow_persistence/test_migration.py` (follow existing migration test patterns)

Columns:

```python
lease_owner = mapped_column(String(160), nullable=True)
lease_until = mapped_column(UTCDateTime(), nullable=True)
lease_token = mapped_column(String(64), nullable=True)
```

Index: `(status, lease_until)` for claim scans.

Migration:

```python
revision = "20260725_0015_workflow_leases"
down_revision = "20260724_0014_market_monitor"
```

- [ ] Failing migration test if the suite asserts heads → add columns → upgrade/downgrade → commit `feat(db): workflow run lease columns`

---

### Task 12: `claim_with_lease` repository + command service

**Files:**
- `workflow_repository.py` — replace/extend `list_queued` claim path
- `workflow_commands.py` — `claim` / `claim_next` accept `lease_owner`, `lease_ttl`, `now`
- `workflow_worker.py` — pass worker instance id; renew lease heartbeat while executing
- Tests: dual-claim unit with mocked rows; postgres contract test if available

Claim eligibility SQL (design §8):

```sql
WHERE status = 'queued'
   OR (status = 'running' AND lease_until < :now)
ORDER BY requested_at ASC, run_id ASC
FOR UPDATE SKIP LOCKED
LIMIT 1
```

On claim:

- set `status=running` if queued (domain transition)
- set `lease_owner`, `lease_until=now+ttl`, new `lease_token`
- if reclaiming expired running: emit event `lease_reclaimed` then continue

On terminal (including cancelled): clear lease fields in same CAS write when status leaves running/cancel path execution.

CAS advance: optional check that `lease_owner` matches for worker writes (M3 minimum: claim uses SKIP LOCKED; enforce owner on compare_and_append only if tests require — design says only non-expired lease owner may advance).

Default TTL: 30s; renew every ~10s from worker while executing.

- [ ] Tests: two concurrent claim_next → one winner; expired lease reclaim; cancelled not claimed
- [ ] Implement
- [ ] Commit `feat(workflow): SKIP LOCKED lease claim and reclaim`

---

### Task 13: Capability `workflow_lease` + docs

- Probe: `workflow_lease=true` when worker enabled **and** repository supports lease (always true after migration in this deploy path) — honest rule: true only if settings say lease path is active (e.g. always after M3 ships, or feature flag `workflow_lease_enabled` default true in server settings).
- Docs update for lease (no public user API).
- Commit `docs: mark workflow lease online`

---

### Task 14: M3 acceptance gate

Dual-worker single claim, reclaim event, cancelled not advanced, tests green.

---

# Milestone 4 — Outbox publisher + SSE

### Task 15: `user_event_deliveries` table + publisher

**Files:**
- Alembic `20260725_0016_user_event_deliveries.py`
- New model module or extend workflow models
- New `backend/finance_god/application/outbox_publisher.py`

Table:

| Column | Type |
| --- | --- |
| `delivery_id` | PK string |
| `owner_id` | string indexed |
| `delivery_sequence` | int, unique per owner |
| `source_outbox_id` | FK/outbox message id |
| `topic` | string |
| `payload` | JSON |
| `created_at` | timestamptz |

Publisher algorithm:

1. Select outbox where `published_at IS NULL` order by `occurred_at` limit N FOR UPDATE SKIP LOCKED
2. Resolve `owner_id` from `workflow_runs`
3. Allocate next `delivery_sequence` per owner (max+1)
4. Insert delivery; set outbox `published_at=now`
5. Notify in-process SSE hub subscribers

- [ ] Unit tests with memory/fake session or postgres contract
- [ ] Commit `feat(events): outbox publisher into user_event_deliveries`

---

### Task 16: SSE + history HTTP

**Files:**
- New routes module `backend/finance_god/api/event_stream_routes.py` or extend workspace routes
- Wire in `server.py`
- Auth: `OwnerResolver` + `Authorization` header (no token query)

Endpoints:

- `GET /api/events?cursor=` → `text/event-stream`
- `GET /api/events/history?cursor=&limit=` → JSON

SSE frame:

```text
id: 42
event: workflow
data: {"delivery_sequence":42,"topic":"workflow.status_changed","run_id":"…","sequence":3,"revision":3,"occurred_at":"…","payload":{…}}
```

If SSE not enabled: 503/404 `SSE_DISABLED`.

- [ ] Tests with TestClient stream or publisher unit + history JSON tests
- [ ] Commit `feat(api): SSE event stream and history backfill`

---

### Task 17: FE SSE-first + capabilities `events_sse`

**Files:**
- `tradingDesk.ts` — `subscribeDeskEvents({ cursor, onEvent, signal })` using `fetch` + `ReadableStream` + `Authorization`
- Store: if `events_sse`, connect; on failure exponential backoff; keep M2 poll until SSE stable
- Never treat SSE gap as business completion
- Docs + `events_sse=true` in probe when publisher task running

- [ ] Commit `feat(desk): SSE-first workflow event subscription with poll fallback`

---

### Task 18: M4 acceptance + final doc pass

- Publisher without subscribers still fills history
- Reconnect backfill via cursor
- Full pytest suite for workflow + persistence
- README / 项目索引 / data contract: cancel, events, lease, SSE all honest

---

## Execution notes for agents

1. **One task at a time.** Prefer Subagent-Driven Development: fresh subagent per task, review between tasks.
2. **TDD discipline:** red → green → commit. Do not combine domain+API+FE in one commit unless the task explicitly says so.
3. **Memory repository drift:** every new repository method must be mirrored on `AsyncMemoryWorkflowRepository` in the same task.
4. **Error envelope:** keep nested `{"error":{"code","message"}}` for Starlette workflow routes.
5. **Do not** implement M3/M4 schema “early” during M1.
6. **Worker collaboration for M1** does not require lease; only durable status honor in executor.
7. If a test file uses sync `TestClient` and needs async claim, use `asyncio.run(...)` once per test; do not restructure the whole suite.
8. When docs conflict with code mid-milestone, code+tests win; docs update at milestone end.

## Self-review (plan vs design)

| Design requirement | Task(s) |
| --- | --- |
| `queued → cancelled` domain | Task 1 |
| `POST .../cancel` + reasons + idempotent + 409 terminal + 404 ownership | Tasks 2, 4 |
| Worker/executor cooperative cancel; artifacts kept | Task 3 |
| `workflow_cancel` capability + desk control | Task 5 |
| `GET .../events?cursor=` + status/cancel events | Tasks 7–8 |
| FE event ledger + hidden-tab stop | Task 9 |
| Lease columns + SKIP LOCKED + reclaim event | Tasks 11–12 |
| `workflow_lease` | Task 13 |
| Outbox → deliveries → SSE + history | Tasks 15–16 |
| FE SSE-first + poll fallback + `events_sse` | Task 17 |
| Docs per milestone | Tasks 5, 9, 13, 17–18 |
| No microservice / no Kafka / cooperative only | Global constraints |

**Placeholder scan:** no TBD/TODO left in task steps; code sketches are concrete.

**Type consistency:** `request_cancel` / `WorkflowTerminalError` / `WorkflowEventView` / lease column names / `delivery_sequence` used uniformly across tasks.

**Known intentional deviations from design prose:**

1. HTTP error JSON stays nested (`error.code`) to match existing `workflow_routes._error` — design’s flat example is conceptual.
2. Internal event type strings remain `workflow_*`; public mapping layer exposes design whitelist names.
3. M1 sets `workflow_events`/`workflow_lease`/`events_sse` explicitly false in the probe so the FE never assumes them.

---

## Plan complete

Plan saved to `docs/superpowers/plans/2026-07-25-workflow-near-prod-loop.md`.
