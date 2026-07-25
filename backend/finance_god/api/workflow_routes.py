"""Public HTTP surface for durable WorkflowRun creation and observation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.agents.contracts import WorkflowKey
from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.api.desk_intent import (
    requests_trade_form_prefill,
    select_desk_workflow,
)
from finance_god.application.workflow_worker import (
    CONNECTED_DETERMINISTIC_SERVICES,
    worker_supports,
)
from finance_god.application.idempotency import canonical_request_hash
from finance_god.domain import (
    ActiveWorkflowConflict,
    ConcurrentCommandConflict,
    DomainInvariantViolation,
    IdempotencyConflict,
)
from finance_god.domain.models import VersionReference, WorkflowRun, WorkflowRunStatus
from finance_god.orchestration.workflow_commands import (
    WorkflowCommandPort,
    WorkflowCreateCommand,
)
from finance_god.orchestration.workflow_registry import WorkflowDefinition

IDEMPOTENCY_HEADER = "idempotency-key"
TERMINAL_STATUSES = frozenset(
    {
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.ATTENTION_REQUIRED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.TIMED_OUT,
        WorkflowRunStatus.BLOCKED,
        WorkflowRunStatus.EXPIRED,
        WorkflowRunStatus.CANCELLED,
    }
)


class WorkflowRuntimeUnavailable(RuntimeError):
    """Raised when the durable workflow runtime is unavailable."""


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkflowCreateRequest(APIModel):
    workflow_key: WorkflowKey
    request_intent: str = Field(min_length=1, max_length=500)
    scope: dict[str, str] = Field(default_factory=dict)
    input_versions: tuple[VersionReference, ...] = ()
    task_plan_reference: VersionReference | None = None

    # Kept while the trading-desk client uses its compact instrument contract.
    # Callers should prefer input_versions for a fully explicit public command.
    symbol: str | None = Field(default=None, min_length=1, max_length=160)
    context_version: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def require_versioned_input(self):
        has_legacy_input = self.symbol is not None or self.context_version is not None
        if has_legacy_input and (self.symbol is None or self.context_version is None):
            raise ValueError("symbol and context_version must be supplied together")
        if self.input_versions:
            if has_legacy_input:
                raise ValueError(
                    "input_versions cannot be combined with symbol/context_version"
                )
            return self
        if self.symbol is None or self.context_version is None:
            raise ValueError(
                "input_versions or symbol and context_version are required"
            )
        symbol = self.symbol.strip().upper()
        return self.model_copy(
            update={
                "symbol": symbol,
                "input_versions": (
                    VersionReference(
                        object_type="instrument_context",
                        object_id=symbol,
                        version=self.context_version,
                    ),
                ),
            }
        )

    def command_scope(self) -> dict[str, str]:
        scope = dict(self.scope)
        if self.symbol is not None:
            scope.setdefault("symbol", self.symbol)
        return scope


class WorkflowProgressResponse(APIModel):
    run_id: str
    workflow_key: str
    workflow_version: str
    status: WorkflowRunStatus
    revision: int
    updated_at: datetime
    total_node_count: int = Field(ge=1)
    completed_node_artifact_count: int = Field(ge=0)
    completed_node_artifacts: tuple[VersionReference, ...]
    nodes: tuple["WorkflowNodeProgressResponse", ...]
    errors: tuple[str, ...]
    is_terminal: bool


class WorkflowNodeProgressResponse(APIModel):
    node_id: str
    title: str
    agent_ids: tuple[str, ...]
    service_id: str | None
    status: Literal["pending", "running", "completed", "failed", "timed_out", "reused"]
    attempt: int | None = None
    updated_at: datetime | None = None


class DeskWorkflowCreateRequest(APIModel):
    """Compact desk command; workflow selection remains server-owned."""

    request_intent: str = Field(min_length=1, max_length=500)
    section: Literal["information", "portfolio", "watchlist", "trading", "review"]
    symbol: str = Field(min_length=1, max_length=160)
    context_version: str = Field(min_length=1, max_length=80)
    order_draft_id: str | None = Field(default=None, min_length=1, max_length=160)
    order_draft_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )

    @model_validator(mode="after")
    def require_complete_order_reference(self):
        if (self.order_draft_id is None) != (self.order_draft_version is None):
            raise ValueError(
                "order_draft_id and order_draft_version must be supplied together"
            )
        return self


class WorkflowRetryRequest(APIModel):
    mode: Literal["full", "resume_failed"]


WorkflowCommandProvider = Callable[[], WorkflowCommandPort]
WorkflowDefinitionProvider = Callable[[str], WorkflowDefinition]
InstrumentValidator = Callable[[str], object]
WorkAvailableNotifier = Callable[[], None]


def create_workflow_routes(
    *,
    commands_provider: WorkflowCommandProvider,
    definition_provider: WorkflowDefinitionProvider,
    owner_resolver: OwnerResolver,
    instrument_validator: InstrumentValidator | None = None,
    work_available: WorkAvailableNotifier | None = None,
    now: Callable[[], datetime] | None = None,
) -> list[Route]:
    clock = now or (lambda: datetime.now(UTC))

    async def create(request: Request) -> JSONResponse:
        try:
            owner_id = await _owner(owner_resolver, request)
            payload = WorkflowCreateRequest.model_validate(await request.json())
            _validate_symbol(payload.symbol, instrument_validator)
            _require_worker_support(definition_provider(payload.workflow_key.value))
            return await _create_response(
                commands=commands_provider(),
                owner_id=owner_id,
                idempotency_key=_idempotency_key(request),
                workflow_key=payload.workflow_key,
                request_intent=payload.request_intent,
                scope=payload.command_scope(),
                input_versions=payload.input_versions,
                requested_at=clock(),
                task_plan_reference=payload.task_plan_reference,
                work_available=work_available,
            )
        except Exception as error:  # noqa: BLE001 - translated HTTP boundary
            return _error_response(error)

    async def create_for_desk(request: Request) -> JSONResponse:
        try:
            owner_id = await _owner(owner_resolver, request)
            payload = DeskWorkflowCreateRequest.model_validate(await request.json())
            symbol = payload.symbol.strip().upper()
            _validate_symbol(symbol, instrument_validator)
            workflow_key = select_desk_workflow(
                payload.request_intent,
                section=payload.section,
            )
            if (
                workflow_key is WorkflowKey.ORDER_REVIEW
                and payload.order_draft_id is None
            ):
                raise ValueError(
                    "order review requires order_draft_id and order_draft_version"
                )
            _require_worker_support(definition_provider(workflow_key.value))
            input_versions = [
                VersionReference(
                    object_type="instrument_context",
                    object_id=symbol,
                    version=payload.context_version,
                )
            ]
            scope = {"section": payload.section, "symbol": symbol}
            if (
                workflow_key is WorkflowKey.TRADE_PLAN_GENERATION
                and requests_trade_form_prefill(payload.request_intent)
            ):
                scope["requested_ui_action"] = "fill_trade_draft"
            if payload.order_draft_id is not None:
                input_versions.append(
                    VersionReference(
                        object_type="order_draft",
                        object_id=payload.order_draft_id,
                        version=payload.order_draft_version or "",
                    )
                )
                scope["order_draft_id"] = payload.order_draft_id
            return await _create_response(
                commands=commands_provider(),
                owner_id=owner_id,
                idempotency_key=_idempotency_key(request),
                workflow_key=workflow_key,
                request_intent=payload.request_intent,
                scope=scope,
                input_versions=tuple(
                    sorted(
                        input_versions,
                        key=lambda item: (
                            item.object_type,
                            item.object_id,
                            item.version,
                        ),
                    )
                ),
                requested_at=clock(),
                work_available=work_available,
            )
        except Exception as error:  # noqa: BLE001 - translated HTTP boundary
            return _error_response(error)

    async def get(request: Request) -> JSONResponse:
        try:
            run = await _owned_run(
                commands_provider(),
                await _owner(owner_resolver, request),
                request.path_params["run_id"],
            )
            record = await commands_provider().get_record(run.run_id)
            if record is None:
                raise LookupError("workflow run was not found")
            return JSONResponse(_record_json(record))
        except Exception as error:  # noqa: BLE001 - translated HTTP boundary
            return _error_response(error)

    async def progress(request: Request) -> JSONResponse:
        try:
            commands = commands_provider()
            run = await _owned_run(
                commands,
                await _owner(owner_resolver, request),
                request.path_params["run_id"],
            )
            after_revision, wait_seconds = _progress_wait(request)
            if after_revision is not None and run.revision <= after_revision:
                deadline = monotonic() + wait_seconds
                while run.revision <= after_revision and monotonic() < deadline:
                    await asyncio.sleep(min(0.2, max(0.0, deadline - monotonic())))
                    refreshed = await commands.get(run.run_id)
                    if refreshed is None:
                        raise LookupError("workflow run was not found")
                    run = refreshed
            definition = definition_provider(run.workflow_key)
            execution_audits = await commands.list_execution_audits(run.run_id)
            completed = run.completed_node_artifacts
            return _json(
                WorkflowProgressResponse(
                    run_id=run.run_id,
                    workflow_key=run.workflow_key,
                    workflow_version=run.workflow_version,
                    status=run.status,
                    revision=run.revision,
                    updated_at=run.audit_reference.recorded_at,
                    total_node_count=len(definition.nodes),
                    completed_node_artifact_count=len(completed),
                    completed_node_artifacts=completed,
                    nodes=_node_progress(definition, execution_audits),
                    errors=run.errors,
                    is_terminal=run.status in TERMINAL_STATUSES,
                )
            )
        except Exception as error:  # noqa: BLE001 - translated HTTP boundary
            return _error_response(error)

    async def list_runs(request: Request) -> JSONResponse:
        try:
            owner_id = await _owner(owner_resolver, request)
            raw_limit = request.query_params.get("limit", "20")
            try:
                limit = int(raw_limit)
            except ValueError as error:
                raise ValueError("limit must be numeric") from error
            status = request.query_params.get("status") or None
            if status and status not in {item.value for item in WorkflowRunStatus}:
                raise ValueError("invalid workflow status")
            records, next_cursor = await commands_provider().list_records(
                owner_id=owner_id,
                limit=limit,
                cursor=request.query_params.get("cursor"),
                status=status,
            )
            return JSONResponse({
                "items": [_record_json(record) for record in records],
                "next_cursor": next_cursor,
            })
        except Exception as error:  # noqa: BLE001
            return _error_response(error)

    async def cancel(request: Request) -> JSONResponse:
        try:
            commands = commands_provider()
            owner_id = await _owner(owner_resolver, request)
            run_id = request.path_params["run_id"]
            await _owned_run(commands, owner_id, run_id)
            run = await commands.cancel(
                run_id,
                actor_id=owner_id,
                idempotency_key=_idempotency_key(request),
                request_hash=canonical_request_hash({"run_id": run_id}),
                cancelled_at=clock(),
            )
            record = await commands.get_record(run.run_id)
            if record is None:
                raise LookupError("workflow run was not found")
            return JSONResponse(_record_json(record))
        except Exception as error:  # noqa: BLE001
            return _error_response(error)

    async def retry(request: Request) -> JSONResponse:
        try:
            commands = commands_provider()
            owner_id = await _owner(owner_resolver, request)
            run_id = request.path_params["run_id"]
            await _owned_run(commands, owner_id, run_id)
            payload = WorkflowRetryRequest.model_validate(await request.json())
            receipt = await commands.retry(
                run_id,
                owner_id=owner_id,
                idempotency_key=_idempotency_key(request),
                mode=payload.mode,
                requested_at=clock(),
            )
            if receipt.created and work_available is not None:
                work_available()
            record = await commands.get_record(receipt.run.run_id)
            if record is None:
                raise LookupError("workflow run was not found")
            return JSONResponse(
                _record_json(record),
                status_code=201 if receipt.created else 200,
            )
        except Exception as error:  # noqa: BLE001
            return _error_response(error)

    return [
        Route("/workflows", create, methods=["POST"]),
        Route("/workflows", list_runs, methods=["GET"]),
        Route("/workflows/desk", create_for_desk, methods=["POST"]),
        Route("/workflows/{run_id:str}", get, methods=["GET"]),
        Route("/workflows/{run_id:str}/progress", progress, methods=["GET"]),
        Route("/workflows/{run_id:str}/cancel", cancel, methods=["POST"]),
        Route("/workflows/{run_id:str}/retry", retry, methods=["POST"]),
    ]


def _progress_wait(request: Request) -> tuple[int | None, float]:
    raw_revision = request.query_params.get("after_revision")
    if raw_revision is None:
        return None, 0.0
    try:
        after_revision = int(raw_revision)
        wait_seconds = float(request.query_params.get("wait_seconds", "20"))
    except ValueError as error:
        raise ValueError("after_revision and wait_seconds must be numeric") from error
    if after_revision < 0:
        raise ValueError("after_revision must be non-negative")
    if not 0 < wait_seconds <= 25:
        raise ValueError("wait_seconds must be greater than 0 and at most 25")
    return after_revision, wait_seconds


def _validate_symbol(
    symbol: str | None,
    validator: InstrumentValidator | None,
) -> None:
    if symbol is not None and validator is not None:
        validator(symbol)


def _node_progress(
    definition: WorkflowDefinition,
    audits,
) -> tuple[WorkflowNodeProgressResponse, ...]:
    state: dict[str, dict[str, object]] = {}
    status_by_event = {
        "node_attempt_started": "running",
        "node_attempt_completed": "completed",
        "node_attempt_failed": "failed",
        "node_attempt_timed_out": "timed_out",
        "node_reused": "reused",
    }
    for audit in audits:
        node_id = str(audit.payload.get("node_id", ""))
        if not node_id or audit.event_type not in status_by_event:
            continue
        state[node_id] = {
            "status": status_by_event[audit.event_type],
            "attempt": audit.payload.get("attempt"),
            "updated_at": audit.occurred_at,
        }
    return tuple(
        WorkflowNodeProgressResponse(
            node_id=node.node_id,
            title=node.title,
            agent_ids=node.agent_ids,
            service_id=node.service_id,
            status=str(state.get(node.node_id, {}).get("status", "pending")),
            attempt=state.get(node.node_id, {}).get("attempt"),
            updated_at=state.get(node.node_id, {}).get("updated_at"),
        )
        for node in definition.nodes
    )


async def _create_response(
    *,
    commands: WorkflowCommandPort,
    owner_id: str,
    idempotency_key: str,
    workflow_key: WorkflowKey,
    request_intent: str,
    scope: dict[str, str],
    input_versions: tuple[VersionReference, ...],
    requested_at: datetime,
    task_plan_reference: VersionReference | None = None,
    work_available: WorkAvailableNotifier | None = None,
) -> JSONResponse:
    receipt = await commands.create(
        WorkflowCreateCommand(
            idempotency_key=idempotency_key,
            workflow_key=workflow_key,
            request_intent=request_intent,
            owner_id=owner_id,
            scope=scope,
            input_versions=input_versions,
            requested_at=requested_at,
            task_plan_reference=task_plan_reference,
        )
    )
    if receipt.created and work_available is not None:
        work_available()
    return _json(receipt.run, status_code=201 if receipt.created else 200)


def _require_worker_support(definition: WorkflowDefinition) -> None:
    if worker_supports(definition):
        return
    missing = sorted(
        {
            node.service_id
            for node in definition.nodes
            if node.service_id is not None
            and node.service_id not in CONNECTED_DETERMINISTIC_SERVICES
        }
    )
    raise WorkflowRuntimeUnavailable(
        "workflow deterministic services are not connected: " + ", ".join(missing)
    )


async def _owned_run(
    commands: WorkflowCommandPort,
    owner_id: str,
    run_id: str,
) -> WorkflowRun:
    persisted_owner = await commands.get_owner_id(run_id)
    if persisted_owner != owner_id:
        raise LookupError("workflow run was not found")
    run = await commands.get(run_id)
    if run is None:
        raise LookupError("workflow run was not found")
    return run


async def _owner(owner_resolver: OwnerResolver, request: Request) -> str:
    owner_id = (await owner_resolver(request)).strip()
    if not owner_id or len(owner_id) > 160:
        raise AuthenticationError("authenticated owner is required")
    return owner_id


def _idempotency_key(request: Request) -> str:
    key = request.headers.get(IDEMPOTENCY_HEADER, "").strip()
    if not key or len(key) > 160:
        raise ValueError("a valid idempotency-key header is required")
    return key


def _json(model: BaseModel | WorkflowRun, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), status_code=status_code)


def _record_json(record: dict[str, object]) -> dict[str, object]:
    run = record["run"]
    assert isinstance(run, WorkflowRun)
    return {
        **run.model_dump(mode="json"),
        "request_intent": record["request_intent"],
        "scope": record["scope"],
        "requested_at": record["requested_at"].isoformat(),
        "created_at": record["created_at"].isoformat(),
        "updated_at": record["updated_at"].isoformat(),
        "parent_run_id": record["parent_run_id"],
        "retry_mode": record["retry_mode"],
        "resumed_from_node_id": record["resumed_from_node_id"],
    }


def _error_response(error: Exception) -> JSONResponse:
    if isinstance(error, ValidationError):
        return _error("VALIDATION_ERROR", str(error), 422)
    if isinstance(error, AuthenticationError):
        return _error("UNAUTHORIZED", str(error), 401)
    if isinstance(error, LookupError):
        return _error("NOT_FOUND", str(error), 404)
    if isinstance(error, ActiveWorkflowConflict):
        return JSONResponse(
            {
                "error": {
                    "code": "WORKFLOW_ALREADY_ACTIVE",
                    "message": str(error),
                    "active_run_id": error.active_run_id,
                }
            },
            status_code=409,
        )
    if isinstance(error, IdempotencyConflict):
        return _error("IDEMPOTENCY_CONFLICT", str(error), 409)
    if isinstance(error, ConcurrentCommandConflict):
        return _error("CONFLICT", str(error), 409)
    if isinstance(error, DomainInvariantViolation):
        return _error("WORKFLOW_BLOCKED", str(error), 409)
    if isinstance(error, WorkflowRuntimeUnavailable):
        return _error("WORKFLOW_RUNTIME_UNAVAILABLE", str(error), 503)
    if isinstance(error, RuntimeError) and "revision changed" in str(error):
        return _error("CONFLICT", str(error), 409)
    if isinstance(error, ValueError):
        return _error("INVALID_REQUEST", str(error), 400)
    raise error


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status_code
    )
