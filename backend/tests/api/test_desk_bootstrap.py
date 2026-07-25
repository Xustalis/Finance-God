from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime

from starlette.applications import Starlette
from starlette.testclient import TestClient

from finance_god.api.auth import AuthenticationError
from finance_god.api.desk_routes import create_desk_routes

OWNER = "desk-owner"
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


async def _owner(_request) -> str:
    return OWNER


async def _failing_owner(_request) -> str:
    raise AuthenticationError("missing bearer token")


async def _rich_profile(_owner_id: str) -> dict:
    return {
        "version": 3,
        "archetype_code": "balanced",
        "archetype_title": "均衡型",
        "risk_level": "medium",
        "loss_tolerance_percent": 15.0,
        "confidence": 0.82,
        "completeness": 0.9,
        "education_only": False,
        "selected_direction": "long_term",
        "recommended_directions": ["long_term", "index"],
        "settings": {"should_not": "leak"},
        "token": "secret-token",
        "password": "nope",
    }


async def _failing_profile(_owner_id: str) -> dict:
    raise RuntimeError("profile store down")


async def _quick_commands(
    _owner_id,
    _stage,
    section,
    symbol,
    _instrument_name,
    projection,
    _answer_text,
    _workflow_evidence,
):
    profile_hint = projection.risk_level or "未完成画像"
    return (
        f"{symbol} 在{section}区最值得核查什么？",
        f"从{profile_hint}角度找一项反方证据",
        f"下一步应补哪类{symbol}证据？",
    )


def _client(
    *,
    owner=_owner,
    profile_provider=None,
    capability_provider=None,
    quick_command_provider=_quick_commands,
    quick_command_context_provider=None,
) -> TestClient:
    app = Starlette(
        routes=create_desk_routes(
            owner_resolver=owner,
            profile_provider=profile_provider,
            now=lambda: NOW,
            default_symbol="000001.SZ",
            capability_provider=capability_provider,
            quick_command_provider=quick_command_provider,
            quick_command_context_provider=quick_command_context_provider,
            instrument_name_provider=lambda symbol: {
                "000001.SZ": "平安银行",
                "600519.SH": "贵州茅台",
            }.get(symbol, symbol),
        )
    )
    return TestClient(app)


def test_bootstrap_returns_shell_state_with_safe_action_catalog() -> None:
    response = _client(profile_provider=_rich_profile).get(
        "/desk/bootstrap",
        params={"section": "trading", "symbol": "600519.SH"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["owner_id"] == OWNER
    assert body["section"] == "trading"
    assert body["symbol"] == "600519.SH"
    assert body["context_version"].startswith(f"desk:{OWNER}:trading:600519.SH:")
    assert body["generated_at"] == "2026-07-25T12:00:00Z"
    assert "quick_commands" not in body
    assert "quick_commands_error" not in body
    assert body["capabilities"]["order_submit"] is False
    assert body["capabilities"]["settings_excluded"] is True
    assert body["capabilities"]["workflow_claim"] is False
    # Without a live capability probe, create/worker stay False (never declared).
    assert body["capabilities"]["workflow_create"] is False
    assert body["capabilities"]["workflow_worker"] is False
    assert body["capabilities"]["market_data"] is False
    ids = {item["id"] for item in body["ui_action_catalog"]}
    assert "navigate_trading" in ids
    assert "select_symbol" in ids
    assert "fill_trade_draft" in ids
    assert "locate_candidate" in ids
    assert "open_trade_plan" in ids
    assert all(item["descriptor_version"] == "1" for item in body["ui_action_catalog"])
    projection = body["profile_projection"]
    assert projection["available"] is True
    assert projection["degraded"] is False
    assert projection["archetype_code"] == "balanced"
    assert projection["recommended_directions"] == ["long_term", "index"]
    assert "settings" not in projection
    assert "token" not in projection
    assert "password" not in projection


def test_bootstrap_does_not_call_quick_command_provider() -> None:
    called = False

    async def provider(*_args):
        nonlocal called
        called = True
        return ("一", "二", "三")

    response = _client(quick_command_provider=provider).get("/desk/bootstrap")
    assert response.status_code == 200
    assert called is False


def test_bootstrap_loads_profile_and_capabilities_concurrently() -> None:
    profile_started = threading.Event()
    capability_started = threading.Event()
    observed_peer_start = {"profile": False, "capability": False}

    async def profile_provider(_owner_id: str) -> dict:
        profile_started.set()
        observed_peer_start["profile"] = await asyncio.to_thread(
            capability_started.wait, 1
        )
        return await _rich_profile(_owner_id)

    async def capability_provider() -> dict[str, bool]:
        capability_started.set()
        observed_peer_start["capability"] = await asyncio.to_thread(
            profile_started.wait, 1
        )
        return {"workflow_create": True}

    response = _client(
        profile_provider=profile_provider,
        capability_provider=capability_provider,
    ).get("/desk/bootstrap")

    assert response.status_code == 200
    assert observed_peer_start == {"profile": True, "capability": True}


def test_quick_command_api_uses_server_owned_answer_context() -> None:
    captured: dict[str, object] = {}

    async def context_provider(owner_id, stage, reference):
        captured["context"] = (owner_id, stage, reference)
        return "服务端保存的直接回答"

    async def provider(
        owner_id,
        stage,
        section,
        symbol,
        instrument_name,
        projection,
        answer_text,
        workflow_evidence,
    ):
        captured["generation"] = (
            owner_id,
            stage,
            section,
            symbol,
            instrument_name,
            projection.risk_level,
            answer_text,
            workflow_evidence,
        )
        return ("平安银行结论依据是什么？", "平安银行有哪些反方风险？", "平安银行下一步补什么证据？")

    client = _client(
        profile_provider=_rich_profile,
        quick_command_provider=provider,
        quick_command_context_provider=context_provider,
    )
    bootstrap = client.get("/desk/bootstrap").json()
    response = client.post(
        "/desk/quick-commands",
        json={
            "stage": "after_answer",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": bootstrap["context_version"],
            "decision_id": "decision-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["quick_commands"][0].startswith("平安银行")
    assert captured["context"] == (OWNER, "after_answer", "decision-1")
    assert captured["generation"][-2] == "服务端保存的直接回答"


def test_quick_command_api_rejects_stale_context_without_generation() -> None:
    response = _client().post(
        "/desk/quick-commands",
        json={
            "stage": "initial",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:other-owner:information:000001.SZ:1",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_CONTEXT"


def test_quick_command_api_requires_authentication_and_stage_reference() -> None:
    unauthorized = _client(owner=_failing_owner).post(
        "/desk/quick-commands",
        json={
            "stage": "initial",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": "desk:any:information:000001.SZ:1",
        },
    )
    invalid = _client().post(
        "/desk/quick-commands",
        json={
            "stage": "after_answer",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": f"desk:{OWNER}:information:000001.SZ:1",
        },
    )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_REQUEST"


def test_quick_command_api_exposes_invalid_or_unavailable_context() -> None:
    async def unavailable_context(*_args):
        raise LookupError("not owned")

    client = _client(quick_command_context_provider=unavailable_context)
    bootstrap = client.get("/desk/bootstrap").json()
    response = client.post(
        "/desk/quick-commands",
        json={
            "stage": "after_workflow",
            "section": "information",
            "symbol": "000001.SZ",
            "context_version": bootstrap["context_version"],
            "run_id": "another-owner-run",
        },
    )

    assert response.status_code == 200
    assert response.json()["quick_commands"] == []
    assert response.json()["quick_commands_error"]
def test_bootstrap_defaults_section_and_symbol() -> None:
    response = _client().get("/desk/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert body["section"] == "information"
    assert body["symbol"] == "000001.SZ"
    assert body["profile_projection"]["available"] is False
    assert body["profile_projection"]["degraded"] is True


def test_bootstrap_rejects_unknown_section() -> None:
    response = _client().get("/desk/bootstrap", params={"section": "settings"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_bootstrap_requires_authenticated_owner() -> None:
    response = _client(owner=_failing_owner).get("/desk/bootstrap")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_bootstrap_degrades_when_profile_provider_fails() -> None:
    response = _client(profile_provider=_failing_profile).get("/desk/bootstrap")
    assert response.status_code == 200
    projection = response.json()["profile_projection"]
    assert projection["available"] is False
    assert projection["degraded"] is True


def test_bootstrap_strips_objective_and_dimension_fields() -> None:
    async def profile_with_raw(_owner_id: str) -> dict:
        return {
            "version": 1,
            "archetype_code": "balanced",
            "risk_level": "medium",
            "objective_profile": {"asset_level": "A6"},
            "dimension_scores": {"risk_capacity": 0.7},
            "answers": {"q1": "yes"},
        }

    response = _client(profile_provider=profile_with_raw).get("/desk/bootstrap")
    assert response.status_code == 200
    projection = response.json()["profile_projection"]
    assert projection["available"] is True
    assert "objective_profile" not in projection
    assert "dimension_scores" not in projection
    assert "answers" not in projection
    assert response.json()["capabilities"]["workflow_worker"] is False


def test_bootstrap_capabilities_reflect_live_probe_only() -> None:
    async def live_probe() -> dict[str, bool]:
        return {
            "workflow_create": True,
            "workflow_worker": True,
            "market_data": True,
            # Provider must not be able to enable forbidden actions.
            "order_submit": True,
            "order_cancel": True,
            "fund_transfer": True,
            "workflow_claim": True,
        }

    response = _client(capability_provider=live_probe).get("/desk/bootstrap")
    assert response.status_code == 200
    caps = response.json()["capabilities"]
    assert caps["workflow_create"] is True
    assert caps["workflow_worker"] is True
    assert caps["market_data"] is True
    assert caps["order_submit"] is False
    assert caps["order_cancel"] is False
    assert caps["fund_transfer"] is False
    assert caps["workflow_claim"] is False
    assert caps["settings_excluded"] is True


def test_bootstrap_capabilities_stay_false_when_probe_fails() -> None:
    async def failing_probe() -> dict[str, bool]:
        raise RuntimeError("dependency down")

    response = _client(capability_provider=failing_probe).get("/desk/bootstrap")
    assert response.status_code == 200
    caps = response.json()["capabilities"]
    assert caps["workflow_create"] is False
    assert caps["workflow_worker"] is False
    assert caps["market_data"] is False
    assert caps["order_submit"] is False


def test_ui_action_applied_for_catalog_action() -> None:
    client = _client()
    bootstrap = client.get(
        "/desk/bootstrap",
        params={"section": "trading", "symbol": "600519.SH"},
    ).json()
    response = client.post(
        "/desk/ui-actions",
        json={
            "action_id": "select_symbol",
            "context_version": bootstrap["context_version"],
            "parameters": {"symbol": "600519.SH"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["receipt"] == "applied"
    assert body["action_id"] == "select_symbol"
    assert body["parameters"]["symbol"] == "600519.SH"
    assert body["owner_id"] == OWNER


def test_ui_action_rejects_unknown_and_forbidden() -> None:
    client = _client()
    bootstrap = client.get("/desk/bootstrap").json()
    unknown = client.post(
        "/desk/ui-actions",
        json={
            "action_id": "submit_order",
            "context_version": bootstrap["context_version"],
        },
    )
    assert unknown.status_code == 200
    assert unknown.json()["receipt"] == "rejected"
    assert unknown.json()["reason"] == "action_not_in_catalog"

    stale = client.post(
        "/desk/ui-actions",
        json={
            "action_id": "select_symbol",
            "context_version": "desk:other-owner:information:000001.SZ:1",
        },
    )
    assert stale.status_code == 200
    assert stale.json()["receipt"] == "stale_context"


def test_ui_action_validates_semantic_parameters_and_rejects_selectors() -> None:
    client = _client()
    context = client.get("/desk/bootstrap").json()["context_version"]

    draft = client.post(
        "/desk/ui-actions",
        json={
            "action_id": "fill_trade_draft",
            "context_version": context,
            "parameters": {
                "side": "buy",
                "quantity": "100",
                "price_type": "limit",
                "limit_price": "12.30",
            },
        },
    ).json()
    assert draft["receipt"] == "applied"

    invalid = client.post(
        "/desk/ui-actions",
        json={
            "action_id": "fill_trade_draft",
            "context_version": context,
            "parameters": {
                "side": "buy",
                "quantity": "0",
                "price_type": "market",
            },
        },
    ).json()
    assert invalid["receipt"] == "rejected"
    assert invalid["reason"] == "invalid_trade_draft"

    selector = client.post(
        "/desk/ui-actions",
        json={
            "action_id": "select_symbol",
            "context_version": context,
            "parameters": {"symbol": "600519.SH", "css_selector": "#buy"},
        },
    ).json()
    assert selector["receipt"] == "rejected"
    assert selector["reason"] == "selector_parameters_forbidden"


def test_ui_action_supports_workspace_records_candidates_and_artifacts() -> None:
    client = _client()
    context = client.get("/desk/bootstrap").json()["context_version"]
    commands = (
        ("set_workspace_filter", {"section": "portfolio", "field": "symbol", "value": "600519.SH"}),
        ("set_workspace_sort", {"section": "watchlist", "field": "change_percent", "value": "desc"}),
        ("open_record", {"record_type": "order", "record_id": "order-1"}),
        ("locate_candidate", {"symbol": "600519.SH", "target": "research"}),
        ("open_workflow_artifact", {"artifact_id": "evidence-1"}),
        ("open_reminder", {"reminder_id": "notice-1"}),
        ("open_trade_plan", {"plan_id": "plan-1"}),
    )
    for action_id, parameters in commands:
        response = client.post(
            "/desk/ui-actions",
            json={
                "action_id": action_id,
                "context_version": context,
                "parameters": parameters,
            },
        )
        assert response.status_code == 200
        assert response.json()["receipt"] == "applied"
