# Workflow Near-Production Loop Design

**Date:** 2026-07-25  
**Status:** Approved for implementation planning  
**Approach:** Contract-first, milestone delivery (A)  
**Priority:** Product loop first; engineering quality only as minimum support for the loop

## 1. Context

Finance-God already has:

- Durable `WorkflowRun` create / get / progress APIs
- Domain cancel states: `cancel_requested` → `cancelling` → `cancelled`
- Append-only `workflow_events` and transactional `workflow_outbox_messages`
- In-process and standalone `WorkflowWorker` that advances `queued` runs
- Desk Agent panel that creates runs and polls progress

Explicitly not online today (per README, project index, and data contract):

- `POST /api/workflows/{run_id}/cancel`
- `GET /api/workflows/{run_id}/events?cursor=`
- Multi-worker `FOR UPDATE SKIP LOCKED` lease
- Outbox publisher and user-facing SSE

This design closes that gap as a **near-production workflow loop**, without microservice split or unrelated refactors.

## 2. Goals

1. Users can **request cancel** of an active workflow and observe honest status transitions.
2. Clients can **read node/status events by cursor**, without timer-fabricated progress.
3. Multiple workers **do not double-claim**; expired leases can be reclaimed.
4. Domain facts flow **Outbox → delivery log → SSE**, with cursor reconnect and history backfill.
5. Every milestone ships with **contract tests**, **honest capabilities flags**, and **doc sync**.

### Success criteria (end-to-end)

| Scenario | Expected |
| --- | --- |
| Create | `201` + `queued`; worker moves to `running` |
| Cancel queued | Reaches `cancelled` with `cancellation_reason`; never claimed afterward |
| Cancel running | `cancel_requested` → worker boundary `cancelling` → `cancelled`; persisted node artifacts kept |
| Events | `GET .../events?cursor=` resumes correctly; includes status/cancel facts |
| Dual worker | One run held by one valid lease |
| SSE | Subscriber receives published deliveries; disconnect recovers via cursor + history |
| Capabilities | Unwired features are `false`; UI disables them |

## 3. Non-goals

- No microservice split; remain monorepo: API + optional workflow worker process + outbox/SSE publish path.
- Agent still cannot submit/cancel orders, change settings, or scan DOM.
- No Kafka/Redis; PostgreSQL lease + outbox only for this phase.
- No rewrite of matching engine, profile pipeline, or market poller architecture.
- No broad frontend visual redesign or placeholder-page cleanup.
- Cancel is **cooperative at node boundaries**, not preemptive mid-node kill.

## 4. Baseline strategy

- Functional baseline: current working tree + accepted P0–P6 desk/worker loop.
- Each milestone changes only loop-related paths.
- Dirty tree: resolve conflicts only on files touched by the milestone; do not open a separate “repo hygiene” project.
- Engineering quality gates are milestone-local: tests green, capabilities honest, docs aligned.

## 5. Architecture

### 5.1 Runtime topology

```text
Vue Desk (Agent panel)
  │  HTTP: create / get / progress / cancel / events?cursor
  │  SSE:  GET /api/events?cursor=  (M4)
  ▼
FastAPI finance_app (server.py)
  ├─ workflow_routes            public commands & queries
  ├─ workflow_commands          domain command port
  ├─ WorkflowRepository + UoW   CAS projection + event/audit/outbox in one TX
  ├─ optional in-process WorkflowWorker
  └─ (M4) OutboxPublisher ──► connected SSE subscribers
Standalone: run_workflow_worker.py ──► same DB / same command port
PostgreSQL: workflow_runs | workflow_events | workflow_outbox_messages | user_event_deliveries (M4)
```

### 5.2 Component boundaries

| Unit | Does | Does not |
| --- | --- | --- |
| `workflow_routes` | Auth, DTO, HTTP codes, capability gates | Own transition rules |
| `WorkflowCommandPort` | create / claim / claim_next / **request_cancel** / transitions | Push SSE directly |
| `WorkflowRepository` | CAS `revision`, append events, outbox; M3 `claim_with_lease` | Run agent nodes |
| `WorkflowWorker` | Claim → execute → record artifacts; honor cancel at node boundaries; M3 renew lease | Fabricate percent progress |
| `WorkflowExecutor` / node runner | Node execution & evidence | Decide cancel policy |
| OutboxPublisher (M4) | Drain unpublished outbox into deliveries + SSE | Mutate business status |
| `tradingDesk` store + `DeskAgentPanel` | Cancel control, events cursor poll (M2), SSE-first with poll fallback (M4) | Timer-fake node completion |

### 5.3 Critical flows

1. **Create** — `POST /workflows` inserts `queued` + event + outbox (existing).
2. **Claim** — worker `claim_next` → `running` + event/outbox; from M3 with `lease_owner` / `lease_until`.
3. **Cancel** — `POST .../cancel`:
   - `queued` → `cancelled` (reason required)
   - `running` → `cancel_requested`; worker at node boundary → `cancelling` → `cancelled`
   - already in cancel path or `cancelled` → idempotent `200`
   - other terminal → `409 WORKFLOW_TERMINAL`
4. **Events read** — `GET .../events?cursor=` where cursor is last consumed per-run `sequence`.
5. **SSE (M4)** — publisher emits per-owner delivery sequence; client reconnects with cursor; history API fills gaps.

## 6. Domain state machine

Reuse `WorkflowRunStatus` and `WORKFLOW_RUN_TRANSITIONS`.

Required extension if missing today:

- `queued` → `cancelled` for user cancel before claim.

Existing paths used as-is:

- `running` → `cancel_requested`
- `cancel_requested` → `cancelling` | `cancelled`
- `cancelling` → `cancelled`

Invariants:

- Any cancel-path status requires `cancellation_reason`.
- First public reason enum value: `user_paused` (matches `WorkflowCancellationReason`).
- No new status names.

Worker cancel collaboration (M1 required):

- Before each node start and after each successful node write, reload run.
- If `cancel_requested`, move to `cancelling` if needed, stop further nodes, move to `cancelled`.
- Keep already persisted node artifacts; do not invent rollback.

## 7. API contract

### 7.1 Common rules

- Bearer auth on all endpoints below.
- Missing or non-owned resource → **404** (no existence leak).
- Success bodies are **raw JSON** (same as existing `/api/workflows/*`).
- Error shape:

```json
{
  "error": "conflict",
  "message": "workflow run is already completed",
  "code": "WORKFLOW_TERMINAL"
}
```

### 7.2 `POST /api/workflows/{run_id}/cancel` (M1)

Request:

```json
{
  "reason": "user_paused",
  "note": "optional free text, max 500"
}
```

Optional header: `Idempotency-Key` (same key + body replay returns same outcome).

| Current status | Result |
| --- | --- |
| `queued` | → `cancelled`; event + outbox; `200` + `WorkflowRun` |
| `running` | → `cancel_requested`; event + outbox; `200` + `WorkflowRun` |
| `cancel_requested` / `cancelling` / `cancelled` | Idempotent `200` + current run (no revision bump if no semantic change) |
| Other terminal | `409 WORKFLOW_TERMINAL` |
| CAS conflict | Re-read and re-evaluate; still conflicting → `409 WORKFLOW_CONFLICT` |

Response: same shape as `GET /workflows/{run_id}`.

### 7.3 `GET /api/workflows/{run_id}/events?cursor=&limit=` (M2)

| Param | Rule |
| --- | --- |
| `cursor` | Integer last consumed `sequence`; default/`0` = from start |
| `limit` | Default 50, max 200 |

Response:

```json
{
  "run_id": "…",
  "events": [
    {
      "event_id": "…",
      "sequence": 3,
      "revision": 3,
      "event_type": "status_changed",
      "occurred_at": "2026-07-25T12:00:00Z",
      "payload": {
        "from_status": "running",
        "to_status": "cancel_requested",
        "cancellation_reason": "user_paused"
      }
    }
  ],
  "next_cursor": 3,
  "has_more": false
}
```

Cursor rules:

- Return events with `sequence > cursor`, ascending.
- `next_cursor` = last event sequence in page; empty page keeps `next_cursor = cursor`.
- Clients must not use timestamps as cursors.
- `progress` remains; it is not an event stream and must not be replaced by client-side percent animation.

Stable `event_type` whitelist (public):

| Type | When |
| --- | --- |
| `run_created` | Enqueued |
| `run_claimed` / `status_changed` | Claim and status moves (cancel path required) |
| `node_started` / `node_completed` / `node_failed` | If executor already records them; do not fabricate |
| `run_cancelled` | Entered `cancelled` |
| `lease_reclaimed` | M3 reclaim |

M2 minimum bar: **status/cancel events complete**. Node-level events are best-effort exposure of existing writes.

### 7.4 Lease (M3) — no end-user public API

- Claim uses `SELECT … FOR UPDATE SKIP LOCKED` plus lease columns on `workflow_runs`.
- Only non-expired lease owner may advance revisions (CAS includes lease token/owner as needed).
- Expired lease: another worker may reclaim; emit `lease_reclaimed`.
- Terminal (including cancelled) clears lease fields.
- Observability: log/metrics for `lease_owner`, claim conflicts. No user “steal lock” API.

### 7.5 `GET /api/events?cursor=` SSE (M4)

Purpose: per-user delivery stream. First payload source is workflow outbox-derived facts; notifications may attach later without rewriting alert rules.

Connection:

- `Accept: text/event-stream`
- Query `cursor` = last consumed **delivery_sequence** (per-owner monotonic).
- Auth: prefer SPA `fetch` + `ReadableStream` with `Authorization` header. Do **not** put long-lived tokens in query strings.

SSE frame example:

```text
id: 42
event: workflow
data: {"delivery_sequence":42,"topic":"workflow.status_changed","run_id":"…","sequence":3,"revision":3,"occurred_at":"…","payload":{…}}
```

Also provide:

- `GET /api/events/history?cursor=&limit=` — JSON backfill, same event payload shape.

Client policy:

- If `events_sse=true`, subscribe SSE first.
- On failure or flag false, fall back to run-level events poll + progress.
- SSE gap is never interpreted as business completion.

### 7.6 Capabilities

| Flag | M1 | M2 | M3 | M4 |
| --- | --- | --- | --- | --- |
| `workflow_cancel` | true | true | true | true |
| `workflow_events` | false | true | true | true |
| `workflow_worker` | true (existing) | true | true | true |
| `workflow_lease` | false | false | true | true |
| `events_sse` | false | false | false | true |

Frontend gates:

- `workflow_cancel` → cancel button
- `workflow_events` → event ledger
- `events_sse` → push subscription

### 7.7 Frontend minimum wiring

- **M1:** Agent panel cancel → `cancelWorkflow`; show existing `cancel_*` labels.
- **M2:** Poll events for `activeWorkflow.run_id` (about 1–2s); stop when document hidden.
- **M4:** SSE when enabled; exponential backoff reconnect; keep poll fallback until SSE proven.

## 8. Data model changes

### Existing (keep)

- `workflow_runs` — CAS projection
- `workflow_events` — per-run sequence + hash chain
- `workflow_outbox_messages` — transactional outbox with nullable `published_at`

### M1 / M2

- Prefer **no schema change**.
- Extend domain transitions if `queued → cancelled` is blocked.
- Repository `list_events` gains `after_sequence` + `limit`.

### M3 — Alembic migration on `workflow_runs`

| Column | Type | Meaning |
| --- | --- | --- |
| `lease_owner` | `String(160) NULL` | Worker instance id |
| `lease_until` | `UTCDateTime NULL` | Lease expiry |
| `lease_token` | `String(64) NULL` | Optional renew/CAS token |

Claim predicate (single chosen semantics in implementation plan):

- Eligible rows: `status = 'queued'` OR (`status = 'running'` AND `lease_until < now()`), ordered FIFO, `FOR UPDATE SKIP LOCKED`.

### M4 — recommended delivery table

New table `user_event_deliveries`:

- `owner_id`
- `delivery_sequence` (per-owner monotonic)
- `source_outbox_id`
- `topic`
- `payload` (JSON)
- `created_at`

Publisher steps:

1. Read outbox rows with `published_at IS NULL`
2. Resolve `owner_id`
3. Insert delivery row(s)
4. Mark outbox `published_at`
5. Push to live SSE subscribers if any

Offline users still recover via history + cursor. Business truth remains workflow tables, not SSE presence.

## 9. Error handling

| Scenario | HTTP | Code |
| --- | --- | --- |
| Unauthenticated | 401 | `UNAUTHENTICATED` |
| Missing / not owned | 404 | `NOT_FOUND` |
| Terminal, not cancellable | 409 | `WORKFLOW_TERMINAL` |
| CAS / concurrency | 409 | `WORKFLOW_CONFLICT` |
| Validation | 422 | `VALIDATION_ERROR` |
| Runtime unavailable | 503 | `WORKFLOW_UNAVAILABLE` |
| SSE disabled | 404 or 503 | `SSE_DISABLED` |

Hard rules:

- Never fabricate events or success terminal states on failure.
- Cancel UI must not show cancelled unless server says so.
- Logs include `run_id`, `owner_id`, `revision`, `lease_owner`; never PandaData credentials or raw sensitive profile fields.

## 10. Milestones and acceptance

### M1 — Cancel

- [ ] `POST /workflows/{id}/cancel` live; `workflow_cancel=true`
- [ ] queued → cancelled; running → cancel_requested → (worker) → cancelled
- [ ] terminal 409; cross-user 404; idempotent 200
- [ ] persisted node artifacts retained
- [ ] Desk cancel control + status copy
- [ ] pytest: API + worker collaboration

### M2 — Events

- [ ] `GET /workflows/{id}/events?cursor=`; `workflow_events=true`
- [ ] cursor resume correct; status/cancel events complete
- [ ] panel event ledger; stop poll when tab hidden
- [ ] progress still available and not replaced by fake percent

### M3 — Lease

- [ ] lease columns migrated; claim uses `SKIP LOCKED`
- [ ] dual worker single claim; expiry reclaim; `lease_reclaimed` event
- [ ] `workflow_lease=true`
- [ ] cancelled runs are not advanced under a live lease

### M4 — Outbox / SSE

- [ ] publisher + delivery cursor
- [ ] `GET /api/events` SSE + `GET /api/events/history`
- [ ] reconnect backfill; `events_sse=true`
- [ ] FE SSE-first with poll fallback
- [ ] unpublished outbox still recoverable via history when no subscriber

### Per-milestone engineering bar

1. Contract/integration tests green
2. Capabilities + README + `docs/项目索引.md` + `docs/page-design/02_前后端职责与数据合同.md` updated
3. Frontend disables unwired controls
4. No drive-by cleanup outside touched paths

## 11. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Dirty working tree | Milestone-scoped conflict resolution; tests lock behavior |
| Hard mid-node cancel | Cooperative node-boundary cancel; document non-preemptive semantics |
| Browser SSE auth | fetch stream + Authorization; no long-lived token query |
| Two cursor spaces | Name and type `sequence` vs `delivery_sequence` separately |
| Clock skew on lease | Server `now()` only; configurable lease TTL (e.g. 30s) + renew heartbeat |

## 12. Documentation touchpoints after implementation

- `README.md` — Current desk capabilities / not-online list
- `docs/项目索引.md` — workflow API surface
- `docs/page-design/02_前后端职责与数据合同.md` — cancel/events/SSE contract
- Bootstrap capabilities consumers in frontend desk store/panel

## 13. Implementation planning handoff

Next step after user review of this spec: invoke **writing-plans** to produce:

`docs/superpowers/plans/2026-07-25-workflow-near-prod-loop.md`

Plan must break M1–M4 into file-level tasks, test commands, and ordered PRs or commits. Do not start coding until that plan exists and is accepted for execution.

## 14. Decision log

| Decision | Choice | Why |
| --- | --- | --- |
| Optimization focus | Product loop over broad quality sweep | User priority |
| Approach | Contract-first milestones (A) | Reuses existing domain/persistence |
| Delivery shape | M1 cancel → M2 events → M3 lease → M4 outbox/SSE | Each batch is demoable and reversible |
| Delivery cursor store | `user_event_deliveries` | Clear per-owner monotonic SSE/history cursor |
| Cancel semantics | Cooperative node boundary | Matches current executor model; avoids unsafe half-writes |
