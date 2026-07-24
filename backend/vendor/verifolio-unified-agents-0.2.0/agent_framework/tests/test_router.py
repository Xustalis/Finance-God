from __future__ import annotations

import pytest

from research_runtime import (
    AgentRegistry,
    AgentRequest,
    AgentRouter,
    AgentRoutingError,
    AssetKind,
    ExecutionProfile,
)


def test_automatic_route_selects_core_research_and_matching_equity_specialists() -> None:
    request = AgentRequest(
        run_id="research-1",
        subject="Example company",
        task_type="research",
        asset_kind=AssetKind.EQUITY,
        tags={"company_deep_dive"},
    )

    plan = AgentRouter(AgentRegistry()).plan(request)
    selected = {item.agent_id for item in plan.assignments}

    assert {
        "tradingagents:fundamentals_analyst",
        "tradingagents:market_analyst",
        "tradingagents:news_analyst",
        "tradingagents:bull_researcher",
        "tradingagents:bear_researcher",
        "finrobot:equity:CompanyOverviewAgent",
        "finrobot:equity:CompetitorAnalysisAgent",
    } == selected


def test_automatic_route_reports_missing_monitor_resources() -> None:
    request = AgentRequest(
        run_id="research-2",
        subject="Market regime",
        task_type="research",
        asset_kind=AssetKind.MARKET,
        tags={"market_context"},
        available_resources={"market_bars"},
    )

    plan = AgentRouter(AgentRegistry()).plan(request)
    notice = next(
        item
        for item in plan.notices
        if item.agent_id == "quantskills:agent-market-regime-monitor"
    )

    assert notice.missing_resources == [
        "lhb_list",
        "margin",
        "option_underlying_volatility",
    ]


def test_external_profile_does_not_bypass_explicit_resource_gate() -> None:
    with pytest.raises(AgentRoutingError, match="workspace"):
        AgentRouter(AgentRegistry()).plan(
            AgentRequest(
                run_id="dev-1",
                subject="Develop alpha",
                task_type="quant_development",
                profile=ExecutionProfile.EXTERNAL,
                requested_agent_ids=["quantskills:liangshuyuan:dev-alpha-agent"],
            )
        )


def test_automatic_workspace_route_selects_orchestrator_and_matching_developer() -> None:
    plan = AgentRouter(AgentRegistry()).plan(
        AgentRequest(
            run_id="alpha-1",
            subject="Implement alpha",
            task_type="quant_development",
            profile=ExecutionProfile.WORKSPACE,
            tags={"alpha"},
            available_resources={"workspace"},
        )
    )

    assert [item.agent_id for item in plan.assignments] == [
        "quantskills:liangshuyuan:main-agent",
        "quantskills:liangshuyuan:dev-alpha-agent",
    ]

