from __future__ import annotations

from datetime import UTC, datetime

from starlette.applications import Starlette
from starlette.testclient import TestClient
from tests.workflows.support import AsyncMemoryWorkflowRepository, SequenceRunIds

from finance_god.api.workflow_routes import create_workflow_routes
from finance_god.orchestration.workflow_commands import WorkflowCommandService
from finance_god.orchestration.workflow_registry import FormalWorkflowRegistry

OWNER = "workflow-owner"
OTHER_OWNER = "other-owner"
NOW = datetime(2026, 7, 25, tzinfo=UTC)


async def _owner(_request) -> str:
    return OWNER


def _commands() -> tuple[WorkflowCommandService, FormalWorkflowRegistry]:
    registry = FormalWorkflowRegistry.build_default()
    commands = WorkflowCommandService(
        registry=registry,
        repository=AsyncMemoryWorkflowRepository(),
        run_ids=SequenceRunIds(),
    )
    return commands, registry


def _client(
    commands: WorkflowCommandService,
    registry: FormalWorkflowRegistry,
    *,
    owner=_owner,
) -> TestClient:
    app = Starlette(
        routes=create_workflow_routes(
            commands_provider=lambda: commands,
            definition_provider=registry.get,
            owner_resolver=owner,
            now=lambda: NOW,
        )
    )
    return TestClient(app)


def _create_payload() -> dict[str, str]:
    return {
        "workflow_key": "company_research",
        "request_intent": "研究 600519.SH 的估值与风险。",
        "symbol": "600519.SH",
        "context_version": "2026-07-25T09:30:00Z",
    }


def _headers(key: str = "workflow-create-0001") -> dict[str, str]:
    return {"Idempotency-Key": key}


def test_create_query_and_read_honest_progress_snapshot() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)

    created = client.post("/workflows", json=_create_payload(), headers=_headers())
    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "queued"
    assert run["workflow_key"] == "company_research"
    assert run["input_versions"] == [
        {
            "object_type": "instrument_context",
            "object_id": "600519.SH",
            "version": "2026-07-25T09:30:00Z",
        }
    ]

    repeated = client.post("/workflows", json=_create_payload(), headers=_headers())
    assert repeated.status_code == 200
    assert repeated.json()["run_id"] == run["run_id"]

    queried = client.get(f"/workflows/{run['run_id']}")
    assert queried.status_code == 200
    assert queried.json()["run_id"] == run["run_id"]

    progress = client.get(f"/workflows/{run['run_id']}/progress")
    assert progress.status_code == 200
    snapshot = progress.json()
    assert snapshot["run_id"] == run["run_id"]
    assert snapshot["workflow_key"] == "company_research"
    assert snapshot["workflow_version"] == run["workflow_version"]
    assert snapshot["status"] == "queued"
    assert snapshot["revision"] == 1
    assert snapshot["updated_at"] == "2026-07-25T00:00:00Z"
    assert snapshot["total_node_count"] == len(registry.get("company_research").nodes)
    assert snapshot["completed_node_artifact_count"] == 0
    assert snapshot["completed_node_artifacts"] == []
    assert snapshot["errors"] == []
    assert snapshot["is_terminal"] is False


def test_workflow_query_hides_runs_owned_by_another_user() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)
    created = client.post("/workflows", json=_create_payload(), headers=_headers())
    run_id = created.json()["run_id"]

    async def _other_owner(_request) -> str:
        return OTHER_OWNER

    # The run is owned by OWNER, therefore resolving this request as OTHER_OWNER
    # must produce the same response as an unknown identifier.
    denied = _client(commands, registry, owner=_other_owner).get(f"/workflows/{run_id}")
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "NOT_FOUND"


def test_creation_requires_an_idempotency_key() -> None:
    commands, registry = _commands()
    response = _client(commands, registry).post("/workflows", json=_create_payload())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
