"""Public HTTP surface for durable WorkflowRun creation and observation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.agents.contracts import WorkflowKey
from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.domain import ConcurrentCommandConflict, DomainInvariantViolation
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
    errors: tuple[str, ...]
    is_terminal: bool


WorkflowCommandProvider = Callable[[], WorkflowCommandPort]
WorkflowDefinitionProvider = Callable[[str], WorkflowDefinition]


def create_workflow_routes(
    *,
    commands_provider: WorkflowCommandProvider,
    definition_provider: WorkflowDefinitionProvider,
    owner_resolver: OwnerResolver,
    now: Callable[[], datetime] | None = None,
) -> list[Route]:
    clock = now or (lambda: datetime.now(UTC))

    async def create(request: Request) -> JSONResponse:
        try:
            owner_id = await _owner(owner_resolver, request)
            payload = WorkflowCreateRequest.model_validate(await request.json())
            command = WorkflowCreateCommand(
                idempotency_key=_idempotency_key(request),
                workflow_key=payload.workflow_key,
                request_intent=payload.request_intent,
                owner_id=owner_id,
                scope=payload.command_scope(),
                input_versions=payload.input_versions,
                requested_at=clock(),
                task_plan_reference=payload.task_plan_reference,
            )
            receipt = await commands_provider().create(command)
            return _json(receipt.run, status_code=201 if receipt.created else 200)
        except Exception as error:  # noqa: BLE001 - translated HTTP boundary
            return _error_response(error)

    async def get(request: Request) -> JSONResponse:
        try:
            run = await _owned_run(
                commands_provider(),
                await _owner(owner_resolver, request),
                request.path_params["run_id"],
            )
            return _json(run)
        except Exception as error:  # noqa: BLE001 - translated HTTP boundary
            return _error_response(error)

    async def progress(request: Request) -> JSONResponse:
        try:
            run = await _owned_run(
                commands_provider(),
                await _owner(owner_resolver, request),
                request.path_params["run_id"],
            )
            definition = definition_provider(run.workflow_key)
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
                    errors=run.errors,
                    is_terminal=run.status in TERMINAL_STATUSES,
                )
            )
        except Exception as error:  # noqa: BLE001 - translated HTTP boundary
            return _error_response(error)

    return [
        Route("/workflows", create, methods=["POST"]),
        Route("/workflows/{run_id:str}", get, methods=["GET"]),
        Route("/workflows/{run_id:str}/progress", progress, methods=["GET"]),
    ]


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


def _error_response(error: Exception) -> JSONResponse:
    if isinstance(error, ValidationError):
        return _error("VALIDATION_ERROR", str(error), 422)
    if isinstance(error, AuthenticationError):
        return _error("UNAUTHORIZED", str(error), 401)
    if isinstance(error, LookupError):
        return _error("NOT_FOUND", str(error), 404)
    if isinstance(error, ConcurrentCommandConflict):
        return _error("IDEMPOTENCY_CONFLICT", str(error), 409)
    if isinstance(error, DomainInvariantViolation):
        return _error("WORKFLOW_BLOCKED", str(error), 409)
    if isinstance(error, WorkflowRuntimeUnavailable):
        return _error("WORKFLOW_RUNTIME_UNAVAILABLE", str(error), 503)
    if isinstance(error, ValueError):
        return _error("INVALID_REQUEST", str(error), 400)
    raise error


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status_code
    )
