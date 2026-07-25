from __future__ import annotations

from types import SimpleNamespace

from research_runtime.contracts import AgentRequest
from research_runtime.models import EvidenceRecord
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.agent_routes import create_agent_routes
from finance_god.orchestration.workflow_registry import FormalWorkflowRegistry

OWNER = "profile-owner"
AUTH = {"Authorization": "Bearer token"}

PROFILE = {
    "version": 3,
    "archetype_code": "growth_seeker",
    "archetype_title": "成长进取型",
    "risk_level": "aggressive",
    "loss_tolerance_percent": 25,
    "confidence": 0.82,
    "completeness": 0.9,
    "education_only": False,
    "objective_profile": {"asset_level": "A6"},
    "dimension_scores": {"risk_capacity": 0.7},
    "recommended_directions": ["equities", "public_funds"],
    "selected_direction": "equities",
}


class _CapturingRuntime:
    """Duck-typed runtime that records the request it was asked to run."""

    def __init__(self) -> None:
        self.last_request: AgentRequest | None = None
        self.proposed_ui_actions: list[dict[str, object]] = []
        self.proposed_ui_action_batches: list[list[dict[str, object]]] = []
        self.desk_turn_calls = 0
        self.last_profile_projection: dict[str, object] | None = None
        self.last_portfolio_projection: dict[str, object] | None = None

    async def run(self, request: AgentRequest):
        self.last_request = request
        return SimpleNamespace(
            model_dump=lambda mode="json": {"run_id": request.run_id, "results": []}
        )

    async def compose_desk_turn(
        self,
        *,
        message: str,
        section: str,
        symbol: str,
        mode: str,
        workflow_title: str | None,
        action_catalog: tuple[dict[str, str], ...],
        profile_projection: dict[str, object],
        portfolio_projection: dict[str, object],
        include_answer: bool = True,
    ) -> dict[str, object]:
        self.desk_turn_calls += 1
        self.last_profile_projection = profile_projection
        self.last_portfolio_projection = portfolio_projection
        answer = None
        if mode == "answer" and include_answer:
            answer = (
                "你好！我在这里，可以帮你研究市场或解释交易台功能。"
                if message == "你好"
                else f"这是对“{message}”的直接回答。"
            )
        return {
            "routing_reason": (
                f"Agent 判断“{message}”适合 {mode}；"
                f"当前标的是 {symbol}，工作流是 {workflow_title or '单 Agent'}。"
            ),
            "answer_text": answer,
            "ui_actions": (
                self.proposed_ui_action_batches.pop(0)
                if self.proposed_ui_action_batches
                else self.proposed_ui_actions
            ),
        }

    async def stream_desk_answer(self, *, message: str, section: str, symbol: str):
        assert section
        assert symbol
        yield f"这是对“{message}”的"
        yield "原生流式回答。"

    def list_agents(self) -> tuple:
        return ()


async def _resolve_owner(_request) -> str:
    return OWNER


def _client(
    runtime: _CapturingRuntime,
    profile: dict | None,
    learning: list[EvidenceRecord] | None = None,
    *,
    learning_error: bool = False,
    profile_error: bool = False,
    portfolio: object | None = None,
    evidence_recorder=None,
):
    registry = FormalWorkflowRegistry.build_default()
    async def _runtime_provider() -> _CapturingRuntime:
        return runtime

    async def _profile_provider(owner_id: str) -> dict | None:
        assert owner_id == OWNER
        if profile_error:
            raise RuntimeError("profile store unavailable")
        return profile

    async def _portfolio_provider(owner_id: str) -> object:
        assert owner_id == OWNER
        if portfolio is None:
            raise LookupError("simulation account not found")
        return portfolio

    async def _learning_provider(
        subject: str,
        task_type: str,
        asset_kind: str,
    ) -> list[EvidenceRecord]:
        assert subject
        assert task_type
        assert asset_kind
        if learning_error:
            raise RuntimeError("learning sidecar unavailable")
        return learning or []

    app = Starlette(
        routes=[
            Mount(
                "/agent",
                routes=create_agent_routes(
                    runtime_provider=_runtime_provider,
                    owner_resolver=_resolve_owner,
                    evidence_recorder=evidence_recorder,
                    profile_provider=_profile_provider,
                    portfolio_provider=_portfolio_provider,
                    learning_context_provider=_learning_provider,
                    workflow_definition_provider=lambda key: registry.get(key),
                ),
            )
        ]
    )
    return TestClient(app)


def test_profile_is_injected_into_payload_and_evidence() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, PROFILE)

    response = client.post(
        "/agent/research",
        json={"subject": "600519", "task_type": "research", "asset_kind": "equity"},
        headers=AUTH,
    )

    assert response.status_code == 200
    request = runtime.last_request
    assert request is not None
    # Planner/agents receive only SuitabilityProfileProjection fields.
    injected = request.payload["investor_profile"]
    assert injected["risk_level"] == "aggressive"
    assert injected["selected_direction"] == "equities"
    assert injected["available"] is True
    assert "objective_profile" not in injected
    assert "dimension_scores" not in injected
    # A citable profile evidence record is prepended for research claims.
    profile_evidence = [e for e in request.evidence if e.identifier == "investor-profile"]
    assert len(profile_evidence) == 1
    assert "aggressive" in profile_evidence[0].excerpt


def test_run_proceeds_without_profile() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None)

    response = client.post(
        "/agent/research",
        json={"subject": "600519", "task_type": "research"},
        headers=AUTH,
    )

    assert response.status_code == 200
    request = runtime.last_request
    assert request is not None
    assert "investor_profile" not in request.payload
    assert all(e.identifier != "investor-profile" for e in request.evidence)
    # Empty caller evidence still gets an E1 seed so prompt agents run.
    assert [e.identifier for e in request.evidence] == ["E1"]
    assert "600519" in request.evidence[0].excerpt


def test_verified_learning_context_is_injected_as_citable_evidence() -> None:
    runtime = _CapturingRuntime()
    learned = EvidenceRecord(
        identifier="L-VERIFIED",
        source="learning:strategy_backtest",
        excerpt="[verified:outcome] held-out result",
    )
    client = _client(runtime, None, [learned])

    response = client.post(
        "/agent/research",
        json={"subject": "510300.SH", "task_type": "research"},
        headers=AUTH,
    )

    assert response.status_code == 200
    request = runtime.last_request
    assert request is not None
    assert [item.identifier for item in request.evidence] == ["L-VERIFIED"]


def test_learning_failure_does_not_block_product_agent() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None, learning_error=True)

    response = client.post(
        "/agent/research",
        json={"subject": "600519.SH", "task_type": "research"},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert [e.identifier for e in runtime.last_request.evidence] == ["E1"]


def test_subject_seed_includes_scope_and_is_skipped_when_caller_supplies_evidence() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None)

    seeded = client.post(
        "/agent/research",
        json={
            "subject": "600519.SH 茅台",
            "task_type": "research",
            "scope": "600519.SH",
            "asset_kind": "equity",
        },
        headers=AUTH,
    )
    assert seeded.status_code == 200
    seeded_request = runtime.last_request
    assert seeded_request is not None
    assert len(seeded_request.evidence) == 1
    assert seeded_request.evidence[0].identifier == "E1"
    assert "scope=600519.SH" in seeded_request.evidence[0].excerpt
    assert "asset_kind=equity" in seeded_request.evidence[0].excerpt

    with_caller = client.post(
        "/agent/research",
        json={
            "subject": "600519.SH",
            "evidence": [
                {
                    "identifier": "caller-1",
                    "source": "manual",
                    "excerpt": "caller fact",
                }
            ],
        },
        headers=AUTH,
    )
    assert with_caller.status_code == 200
    caller_request = runtime.last_request
    assert caller_request is not None
    assert [item.identifier for item in caller_request.evidence] == ["caller-1"]


def test_caller_evidence_keeps_priority_at_agent_contract_limit() -> None:
    runtime = _CapturingRuntime()
    learned = EvidenceRecord(
        identifier="L-VERIFIED",
        source="learning:test",
        excerpt="verified",
    )
    client = _client(runtime, PROFILE, [learned])
    evidence = [
        {
            "identifier": f"caller-{index}",
            "source": "caller",
            "excerpt": "fact",
        }
        for index in range(50)
    ]

    response = client.post(
        "/agent/research",
        json={"subject": "510300.SH", "evidence": evidence},
        headers=AUTH,
    )

    assert response.status_code == 200
    request = runtime.last_request
    assert request is not None
    assert len(request.evidence) == 50
    assert all(item.identifier.startswith("caller-") for item in request.evidence)


def test_direct_agent_answer_is_not_returned_when_evidence_persistence_fails() -> None:
    runtime = _CapturingRuntime()

    async def failing_recorder(_owner_id, _subject, _run) -> None:
        raise RuntimeError("database unavailable")

    client = _client(runtime, None, evidence_recorder=failing_recorder)

    response = client.post(
        "/agent/research",
        json={"subject": "什么是市盈率？", "task_type": "research", "max_agents": 1},
        headers=AUTH,
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_EVIDENCE_PERSISTENCE_FAILED"


def test_desk_decision_keeps_simple_explanation_out_of_workflow() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "什么是市盈率？",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:owner:information:000001.SZ:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "answer"
    assert body["can_start"] is True
    assert body["workflow_key"] is None
    assert body["decision_source"] == "agent_generated_policy_approved"
    assert body["decision_id"].startswith("decision-")
    assert body["routing_reason"].startswith("Agent 判断")
    assert body["answer_text"] == "这是对“什么是市盈率？”的直接回答。"
    assert runtime.desk_turn_calls == 1


def test_desk_direct_answer_receives_safe_profile_projection() -> None:
    runtime = _CapturingRuntime()
    portfolio = SimpleNamespace(
        as_of="2026-07-25T10:00:00+08:00",
        rule_version="simulation-v1",
        realized_pnl_rmb=0,
        positions=(
            SimpleNamespace(
                instrument_id="000001.SZ",
                quantity=100,
                available_quantity=100,
                cost_basis_rmb=1150,
                average_cost_rmb=11.5,
                realized_pnl_rmb=0,
            ),
        ),
    )
    client = _client(runtime, PROFILE, portfolio=portfolio)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "平安银行适配我的风险吗？",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:owner:information:000001.SZ:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    projection = runtime.last_profile_projection
    assert projection is not None
    assert projection["available"] is True
    assert projection["risk_level"] == "aggressive"
    assert projection["loss_tolerance_percent"] == 25
    assert "objective_profile" not in projection
    assert "dimension_scores" not in projection
    portfolio_projection = runtime.last_portfolio_projection
    assert portfolio_projection is not None
    assert portfolio_projection["available"] is True
    assert portfolio_projection["simulation"] is True
    assert portfolio_projection["positions"] == [
        {
            "instrument_id": "000001.SZ",
            "quantity": "100",
            "available_quantity": "100",
            "cost_basis_rmb": "1150",
            "average_cost_rmb": "11.5",
            "realized_pnl_rmb": "0",
        }
    ]


def test_desk_direct_answer_marks_missing_profile_unavailable() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "你好",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:owner:information:000001.SZ:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    assert runtime.last_profile_projection is not None
    assert runtime.last_profile_projection["available"] is False
    assert runtime.last_profile_projection["degraded"] is False


def test_desk_direct_answer_marks_profile_provider_failure_degraded() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None, profile_error=True)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "你好",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:owner:information:000001.SZ:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    assert runtime.last_profile_projection is not None
    assert runtime.last_profile_projection["available"] is False
    assert runtime.last_profile_projection["degraded"] is True


def test_desk_greeting_returns_a_conversational_answer() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "你好",
            "section": "portfolio",
            "symbol": "000001.SZ",
            "context_version": "desk:owner:portfolio:000001.SZ:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "answer"
    assert body["answer_text"] == "你好！我在这里，可以帮你研究市场或解释交易台功能。"


def test_desk_direct_answer_stream_emits_reliable_delta_and_done_event() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, PROFILE)

    with client.stream(
        "POST",
        "/agent/desk/decision/stream",
        json={
            "message": "什么是市盈率？",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:owner:information:000001.SZ:1",
            "active_workflow": False,
        },
        headers=AUTH,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = [__import__("json").loads(line) for line in response.iter_lines()]

    assert [event["type"] for event in events] == ["start", "delta", "done"]
    assert events[0]["decision"]["answer_text"] is None
    assert "".join(event.get("text", "") for event in events) == "这是对“什么是市盈率？”的直接回答。"
    assert events[-1]["answer_text"] == "这是对“什么是市盈率？”的直接回答。"
    assert runtime.last_profile_projection is not None
    assert runtime.last_profile_projection["risk_level"] == "aggressive"


def test_desk_preview_is_side_effect_free_and_uses_server_routing() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None)
    payload = {
        "section": "information",
        "symbol": "600519.SH",
        "context_version": "desk:owner:information:600519.SH:1",
        "active_workflow": False,
    }

    direct = client.post(
        "/agent/desk/preview",
        json={**payload, "message": "什么是市盈率？"},
        headers=AUTH,
    )
    workflow = client.post(
        "/agent/desk/preview",
        json={**payload, "message": "研究贵州茅台的基本面与估值"},
        headers=AUTH,
    )

    assert direct.status_code == 200
    assert direct.json() == {
        "mode": "answer",
        "workflow_key": None,
        "workflow_title": None,
        "expected_roles": ["对话 Agent"],
        "artifact_types": ["文字答复"],
        "can_start": True,
    }
    assert workflow.status_code == 200
    assert workflow.json()["mode"] == "workflow"
    assert workflow.json()["workflow_key"] == "company_research"
    assert workflow.json()["expected_roles"]
    assert workflow.json()["artifact_types"] == ["ResearchMemo"]
    assert runtime.desk_turn_calls == 0


def test_desk_decision_returns_server_validated_ui_actions() -> None:
    runtime = _CapturingRuntime()
    runtime.proposed_ui_actions = [
        {"action_id": "select_symbol", "parameters": {"symbol": "600519.SH"}},
        {"action_id": "navigate_trading", "parameters": {}},
        {
            "action_id": "fill_trade_draft",
            "parameters": {
                "side": "buy",
                "quantity": "100",
                "price_type": "market",
            },
        },
    ]
    client = _client(runtime, None)
    context_version = "desk:owner:information:000001.SZ:1"

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "打开贵州茅台，切到交易页并帮我填买入100股",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": context_version,
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["ui_actions"] == [
        {
            "action_id": "select_symbol",
            "parameters": {"symbol": "600519.SH"},
            "context_version": context_version,
        },
        {
            "action_id": "navigate_trading",
            "parameters": {},
            "context_version": context_version,
        },
        {
            "action_id": "fill_trade_draft",
            "parameters": {
                "side": "buy",
                "quantity": "100",
                "price_type": "market",
            },
            "context_version": context_version,
        },
    ]


def test_desk_decision_allows_explicit_add_to_watchlist_action() -> None:
    runtime = _CapturingRuntime()
    runtime.proposed_ui_actions = [
        {"action_id": "add_to_watchlist", "parameters": {"symbol": "600519.SH"}},
    ]
    client = _client(runtime, None)
    context_version = "desk:owner:information:600519.SH:1"

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "把贵州茅台加入自选",
            "section": "information",
            "symbol": "600519.SH",
            "context_version": context_version,
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["ui_actions"] == [
        {
            "action_id": "add_to_watchlist",
            "parameters": {"symbol": "600519.SH"},
            "context_version": context_version,
        }
    ]


def test_desk_decision_rejects_agent_action_outside_catalog() -> None:
    runtime = _CapturingRuntime()
    runtime.proposed_ui_actions = [
        {"action_id": "submit_order", "parameters": {"quantity": "100"}},
    ]
    client = _client(runtime, None)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "打开交易页并替我提交订单",
            "section": "trading",
            "symbol": "600519.SH",
            "context_version": "desk:owner:trading:600519.SH:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_ACTION_PROPOSAL_FAILED"
    assert runtime.desk_turn_calls == 2


def test_desk_decision_discards_unsolicited_ui_actions_but_keeps_answer() -> None:
    runtime = _CapturingRuntime()
    runtime.proposed_ui_actions = [
        {"action_id": "submit_order", "parameters": {"quantity": "100"}},
    ]
    client = _client(runtime, None)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "什么是市盈率？",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:owner:information:000001.SZ:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["ui_actions"] == []
    assert runtime.desk_turn_calls == 1


def test_desk_decision_retries_invalid_ui_actions_once() -> None:
    runtime = _CapturingRuntime()
    runtime.proposed_ui_action_batches = [
        [{"action_id": "submit_order", "parameters": {"quantity": "100"}}],
        [{"action_id": "navigate_trading", "parameters": {}}],
    ]
    client = _client(runtime, None)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "切到交易页",
            "section": "information",
            "symbol": "600519.SH",
            "context_version": "desk:owner:information:600519.SH:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["ui_actions"] == [
        {
            "action_id": "navigate_trading",
            "parameters": {},
            "context_version": "desk:owner:information:600519.SH:1",
        }
    ]
    assert runtime.desk_turn_calls == 2


def test_desk_workflow_skips_model_turn_when_no_ui_action_was_requested() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "核查平安银行最大回撤超8%的概率",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:owner:information:000001.SZ:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "workflow"
    assert response.json()["routing_reason"].startswith("该任务需要启动")
    assert response.json()["ui_actions"] == []
    assert runtime.desk_turn_calls == 0


def test_trade_strategy_defers_form_prefill_until_versioned_plan_completes() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "制定平安银行交易策略并填写交易单",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:owner:information:000001.SZ:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "workflow"
    assert response.json()["workflow_key"] == "trade_plan_generation"
    assert response.json()["ui_actions"] == []
    assert "完成后" in response.json()["routing_reason"]
    assert runtime.desk_turn_calls == 0


def test_desk_concept_question_does_not_start_strategy_workflow() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None)

    response = client.post(
        "/agent/desk/decision",
        json={
            "message": "什么是量化策略？",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:owner:information:000001.SZ:1",
            "active_workflow": False,
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "answer"
