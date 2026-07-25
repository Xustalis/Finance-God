from decimal import Decimal
from types import SimpleNamespace

from finance_god.application.evidence_service import (
    _agent_run_conclusion,
    evidence_content_from_agent_run,
)
from finance_god.application.workflow_worker import _quote_change_text


def test_agent_evidence_deduplicates_equivalent_claims_from_the_same_source() -> None:
    first = SimpleNamespace(
        kind="fact",
        statement="PandaData freshness is unknown.",
        author_agent_id="agent-1",
        evidence_ids=["E1"],
        unknowns=[],
        invalidation_conditions=[],
    )
    repeated = SimpleNamespace(
        kind="fact",
        statement="  pandadata   FRESHNESS is unknown. ",
        author_agent_id="agent-2",
        evidence_ids=["E1"],
        unknowns=[],
        invalidation_conditions=[],
    )
    run = SimpleNamespace(
        results=(
            SimpleNamespace(claims=(first,), evidence=()),
            SimpleNamespace(claims=(repeated,), evidence=()),
        ),
        plan=None,
    )

    content = evidence_content_from_agent_run(run)

    assert [item["statement"] for item in content["facts"]] == [
        "PandaData freshness is unknown."
    ]


def test_market_snapshot_change_ratio_is_rendered_as_percentage_points() -> None:
    assert _quote_change_text(Decimal("0.02")) == "涨跌幅 2.00%"
    assert _quote_change_text(None) == "涨跌幅不可用"


def test_final_evidence_uses_terminal_synthesis_without_agent_repetition() -> None:
    analyst = SimpleNamespace(
        agent_id="tradingagents:market_analyst",
        summary="分析员摘要",
        claims=(
            SimpleNamespace(
                kind="fact",
                statement="000001.SZ 最新价为 11.10。",
                author_agent_id="tradingagents:market_analyst",
                evidence_ids=["market-context"],
                unknowns=[],
                invalidation_conditions=[],
            ),
        ),
        evidence=(
            SimpleNamespace(
                identifier="market-context",
                source="PandaData",
                excerpt="last=11.10",
            ),
        ),
    )
    manager = SimpleNamespace(
        agent_id="tradingagents:portfolio_manager",
        summary="证据不足，暂不形成交易判断。",
        claims=(
            SimpleNamespace(
                kind="fact",
                statement="000001.SZ 最新价为 11.10。",
                author_agent_id="tradingagents:portfolio_manager",
                evidence_ids=["market-context", "prior-agent"],
                unknowns=["涨跌幅计算基准未知。"],
                invalidation_conditions=[],
            ),
        ),
        evidence=(),
    )
    run = SimpleNamespace(results=(analyst, manager), plan=None)

    content = evidence_content_from_agent_run(run)

    assert len(content["facts"]) == 1
    assert content["facts"][0]["author_agent_id"] == manager.agent_id
    assert content["unknowns"] == ["涨跌幅计算基准未知。"]
    assert content["sources"][0]["identifier"] == "market-context"
    assert _agent_run_conclusion(run) == manager.summary
