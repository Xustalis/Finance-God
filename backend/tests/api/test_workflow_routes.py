from __future__ import annotations

from datetime import UTC, datetime, timedelta

from starlette.applications import Starlette
from starlette.testclient import TestClient
from tests.workflows.support import AsyncMemoryWorkflowRepository, SequenceRunIds

from finance_god.agents.contracts import WorkflowKey
from finance_god.api.desk_intent import select_desk_workflow
from finance_god.api.workflow_routes import create_workflow_routes
from finance_god.orchestration.workflow_commands import WorkflowCommandService
from finance_god.orchestration.workflow_registry import FormalWorkflowRegistry

OWNER = "workflow-owner"
OTHER_OWNER = "other-owner"
_BASE_NOW = datetime(2026, 7, 25, tzinfo=UTC)


class _AdvancingClock:
    """Domain audits require strictly later recorded_at on each version."""

    def __init__(self) -> None:
        self.value = _BASE_NOW

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


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
    instrument_validator=None,
    work_available=None,
) -> TestClient:
    app = Starlette(
        routes=create_workflow_routes(
            commands_provider=lambda: commands,
            definition_provider=registry.get,
            owner_resolver=owner,
            instrument_validator=instrument_validator,
            work_available=work_available,
            now=_AdvancingClock(),
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


def test_new_workflow_notifies_worker_but_idempotent_replay_does_not() -> None:
    commands, registry = _commands()
    notifications: list[str] = []
    client = _client(
        commands,
        registry,
        work_available=lambda: notifications.append("available"),
    )

    created = client.post("/workflows", json=_create_payload(), headers=_headers())
    repeated = client.post("/workflows", json=_create_payload(), headers=_headers())

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert notifications == ["available"]


def test_progress_long_poll_returns_immediately_after_newer_revision() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)
    created = client.post("/workflows", json=_create_payload(), headers=_headers())
    run_id = created.json()["run_id"]

    response = client.get(
        f"/workflows/{run_id}/progress",
        params={"after_revision": 0, "wait_seconds": 20},
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 1


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


def test_unknown_instrument_is_rejected_before_a_run_is_created() -> None:
    commands, registry = _commands()

    def validate(symbol: str) -> None:
        if symbol == "999999.SH":
            raise ValueError("instrument is not present in the authoritative master")

    response = _client(
        commands,
        registry,
        instrument_validator=validate,
    ).post(
        "/workflows/desk",
        json={
            "request_intent": "分析当前行情",
            "section": "information",
            "symbol": "999999.SH",
            "context_version": "desk:user:information:999999:1",
        },
        headers=_headers("desk-invalid-instrument"),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_desk_creation_selects_workflow_on_server() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)
    created = client.post(
        "/workflows/desk",
        json={
            "request_intent": "研究 600519.SH 的基本面与估值",
            "section": "watchlist",
            "symbol": "600519.sh",
            "context_version": "desk:user:watchlist:600519:1",
        },
        headers=_headers("desk-workflow-0001"),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["workflow_key"] == "company_research"
    assert body["status"] == "queued"
    assert body["input_versions"] == [
        {
            "object_type": "instrument_context",
            "object_id": "600519.SH",
            "version": "desk:user:watchlist:600519:1",
        }
    ]

    repeated = client.post(
        "/workflows/desk",
        json={
            "request_intent": "研究 600519.SH 的基本面与估值",
            "section": "watchlist",
            "symbol": "600519.sh",
            "context_version": "desk:user:watchlist:600519:1",
        },
        headers=_headers("desk-workflow-0001"),
    )
    assert repeated.status_code == 200
    assert repeated.json()["run_id"] == body["run_id"]


def test_desk_creation_rejects_a_second_active_run_for_the_owner() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)
    payload = {
        "request_intent": "生成可研究候选",
        "section": "watchlist",
        "symbol": "600519.SH",
        "context_version": "desk:user:watchlist:600519:1",
    }

    first = client.post(
        "/workflows/desk",
        json=payload,
        headers=_headers("desk-workflow-active-0001"),
    )
    second = client.post(
        "/workflows/desk",
        json=payload,
        headers=_headers("desk-workflow-active-0002"),
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"] == {
        "code": "WORKFLOW_ALREADY_ACTIVE",
        "message": "workflow owner already has an active run",
        "active_run_id": first.json()["run_id"],
    }


def test_connected_trade_plan_workflow_is_accepted_for_queueing() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)
    response = client.post(
        "/workflows/desk",
        json={
            "request_intent": "帮我制定交易方案",
            "section": "trading",
            "symbol": "600519.SH",
            "context_version": "desk:user:trading:600519:1",
        },
        headers=_headers("desk-workflow-unconnected"),
    )
    assert response.status_code == 201
    assert response.json()["workflow_key"] == "trade_plan_generation"


def test_connected_strategy_monitoring_workflow_is_accepted_for_queueing() -> None:
    commands, registry = _commands()
    response = _client(commands, registry).post(
        "/workflows",
        json={
            "workflow_key": "strategy_monitoring",
            "request_intent": "检查策略漂移",
            "input_versions": [
                {
                    "object_type": "strategy_baseline",
                    "object_id": "mean-reversion-v1",
                    "version": "2026-07-24T15:00:00Z",
                },
                {
                    "object_type": "strategy_snapshot",
                    "object_id": "mean-reversion-v1",
                    "version": "2026-07-25T15:00:00Z",
                },
            ],
        },
        headers=_headers("strategy-monitor-connected"),
    )

    assert response.status_code == 201
    assert response.json()["workflow_key"] == "strategy_monitoring"


def test_desk_workflow_selection_covers_operating_intents() -> None:
    scenarios = (
        ("推荐几只股票", "information", WorkflowKey.RESEARCH_CANDIDATES),
        ("研究公司基本面", "watchlist", WorkflowKey.COMPANY_RESEARCH),
        ("解释当前行情", "information", WorkflowKey.MARKET_CONTEXT),
        ("检查持仓集中度", "portfolio", WorkflowKey.PORTFOLIO_STRESS),
        ("回测这个策略", "information", WorkflowKey.STRATEGY_VALIDATION),
        ("只读复核这份报告", "information", WorkflowKey.REVIEW_ONLY),
        ("诊断数据质量问题", "information", WorkflowKey.DATA_QUALITY_REVIEW),
        ("研究ETF费用与持仓", "watchlist", WorkflowKey.FUND_RESEARCH),
        ("按目标权重构建组合", "portfolio", WorkflowKey.PORTFOLIO_CONSTRUCTION),
        ("制定交易计划", "trading", WorkflowKey.TRADE_PLAN_GENERATION),
        ("复核订单草稿", "trading", WorkflowKey.ORDER_REVIEW),
        ("执行已确认订单", "trading", WorkflowKey.SIMULATION_EXECUTION),
        ("复盘这次成交滑点", "trading", WorkflowKey.POST_TRADE_REVIEW),
        ("解释突发事件影响", "information", WorkflowKey.EVENT_IMPACT),
        ("分析股债汇联动", "information", WorkflowKey.CROSS_MARKET_ANALYSIS),
        ("检查策略漂移", "information", WorkflowKey.STRATEGY_MONITORING),
    )
    for intent, section, expected in scenarios:
        assert select_desk_workflow(intent, section=section) is expected


def test_specific_intent_wins_over_broad_terms_and_workspace_defaults() -> None:
    assert (
        select_desk_workflow("研究ETF的组合持仓", section="portfolio")
        is WorkflowKey.FUND_RESEARCH
    )
    assert (
        select_desk_workflow("复盘策略执行表现", section="trading")
        is WorkflowKey.POST_TRADE_REVIEW
    )
    assert (
        select_desk_workflow("监控策略表现", section="information")
        is WorkflowKey.STRATEGY_MONITORING
    )


def test_order_review_requires_and_versions_the_current_draft() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)
    payload = {
        "request_intent": "复核订单草稿",
        "section": "trading",
        "symbol": "600519.SH",
        "context_version": "desk:user:trading:600519:1",
    }

    missing = client.post(
        "/workflows/desk",
        json=payload,
        headers=_headers("desk-order-review-missing"),
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "INVALID_REQUEST"

    created = client.post(
        "/workflows/desk",
        json={
            **payload,
            "order_draft_id": "draft-1",
            "order_draft_version": "3",
        },
        headers=_headers("desk-order-review-0001"),
    )
    assert created.status_code == 201
    assert created.json()["workflow_key"] == "order_review"
    assert {
        "object_type": "order_draft",
        "object_id": "draft-1",
        "version": "3",
    } in created.json()["input_versions"]


def test_worker_claim_is_not_exposed_to_authenticated_desk_users() -> None:
    commands, registry = _commands()
    response = _client(commands, registry).post(
        "/workflows/claim",
        json={"run_id": "workflow-missing"},
    )
    assert response.status_code == 405


def test_history_cancel_and_full_retry_preserve_server_input() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)
    created = client.post("/workflows", json=_create_payload(), headers=_headers())
    run_id = created.json()["run_id"]

    history = client.get("/workflows?limit=20")
    assert history.status_code == 200
    assert history.json()["items"][0]["request_intent"] == _create_payload()["request_intent"]
    assert history.json()["items"][0]["scope"]["symbol"] == "600519.SH"

    cancelled = client.post(
        f"/workflows/{run_id}/cancel",
        json={},
        headers=_headers("workflow-cancel-0001"),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    retried = client.post(
        f"/workflows/{run_id}/retry",
        json={"mode": "full"},
        headers=_headers("workflow-retry-0001"),
    )
    assert retried.status_code == 201
    assert retried.json()["run_id"] != run_id
    assert retried.json()["parent_run_id"] == run_id
    assert retried.json()["retry_mode"] == "full"
    assert retried.json()["request_intent"] == _create_payload()["request_intent"]


def test_history_is_owner_scoped_and_repeated_cancel_is_idempotent() -> None:
    commands, registry = _commands()
    client = _client(commands, registry)
    created = client.post("/workflows", json=_create_payload(), headers=_headers())
    run_id = created.json()["run_id"]
    client.post(
        f"/workflows/{run_id}/cancel",
        json={},
        headers=_headers("workflow-cancel-0002"),
    )
    repeated = client.post(
        f"/workflows/{run_id}/cancel",
        json={},
        headers=_headers("workflow-cancel-0003"),
    )
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "cancelled"

    async def other_owner(_request) -> str:
        return OTHER_OWNER

    other = _client(commands, registry, owner=other_owner)
    assert other.get("/workflows").json()["items"] == []
    assert other.get(f"/workflows/{run_id}").status_code == 404
