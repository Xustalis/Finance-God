from __future__ import annotations

from datetime import datetime, timezone

import pytest

from research_runtime import AgentRequest, AgentRunner, AssetKind
from research_runtime.models import DataArtifact, DataQuery, PandaDataDataset


class FakeProvider:
    def fetch(self, query: DataQuery) -> DataArtifact:
        records = self._records(query)
        return DataArtifact(
            provider="fake",
            query=query,
            retrieved_at=datetime.now(timezone.utc),
            row_count=len(records),
            columns=list(records[0]),
            records=records,
        )

    @staticmethod
    def _records(query: DataQuery) -> list[dict[str, object]]:
        if query.dataset == PandaDataDataset.MARGIN:
            return [
                {"date": "20250102", "total_balance": 100.0, "short_balance": 10.0},
                {"date": "20250103", "total_balance": 110.0, "short_balance": 11.0},
            ]
        if query.dataset == PandaDataDataset.LHB_LIST:
            return [{"date": "20250103", "amount": 10.0, "change_rate": 2.0}]
        if query.dataset == PandaDataDataset.FUTURE_DOMINANT_CORR:
            return [{"date": "20250103", "pair": "RB:JM", "correlation": 0.4}]
        if query.dataset == PandaDataDataset.OPTION_IMPLIED_VOLATILITY:
            return [{"date": "20250103", "implied_volatility": 25.0}]
        if query.dataset == PandaDataDataset.OPTION_UNDERLYING_VOLATILITY:
            return [{"date": "20250103", "historical_volatility": 0.2}]
        if query.dataset == PandaDataDataset.MARKET_BARS:
            return [
                {"date": "20250102", "close": 100.0},
                {"date": "20250103", "close": 105.0},
            ]
        raise AssertionError(f"unexpected dataset: {query.dataset}")


def request(kind: str = "crowding_risk") -> AgentRequest:
    return AgentRequest(
        run_id="monitor-1",
        subject="Crowding review",
        task_type="research",
        asset_kind=AssetKind.EQUITY,
        available_resources={"margin", "lhb_list"},
        requested_agent_ids=["quantskills:agent-crowding-risk-monitor"],
        payload={
            "kind": kind,
            "subject": "Crowding review",
            "symbol": "000001.SZ",
            "start_date": "20250102",
            "end_date": "20250103",
        },
    )


def test_monitor_runs_through_unified_envelope_without_raw_records() -> None:
    result = AgentRunner(data_provider=FakeProvider()).run(request()).results[0]

    assert result.agent_id == "quantskills:agent-crowding-risk-monitor"
    assert result.metadata["snapshot"]["state"] == "crowding-watch"
    assert result.claims[0].evidence_ids
    assert all("records" not in artifact.metadata for artifact in result.artifacts)


@pytest.mark.parametrize(
    ("agent_id", "resources", "payload", "expected_state"),
    [
        (
            "quantskills:agent-correlation-break-research",
            {"future_dominant_corr"},
            {
                "kind": "correlation_break",
                "subject": "Correlation",
                "future_symbols": ["RB", "JM"],
                "start_date": "20250102",
                "end_date": "20250103",
            },
            "correlation-structure-observed",
        ),
        (
            "quantskills:agent-crowding-risk-monitor",
            {"margin", "lhb_list"},
            {
                "kind": "crowding_risk",
                "subject": "Crowding",
                "symbol": "000001.SZ",
                "start_date": "20250102",
                "end_date": "20250103",
            },
            "crowding-watch",
        ),
        (
            "quantskills:agent-derivatives-skew-sentiment-monitor",
            {"option_implied_volatility", "option_underlying_volatility"},
            {
                "kind": "derivatives_iv_premium",
                "subject": "Volatility",
                "option_underlying": "510300.SH",
                "start_date": "20250102",
                "end_date": "20250103",
            },
            "iv-premium-watch",
        ),
        (
            "quantskills:agent-market-regime-monitor",
            {
                "market_bars",
                "margin",
                "lhb_list",
                "option_underlying_volatility",
            },
            {
                "kind": "market_regime",
                "subject": "Regime",
                "symbol": "000001.SZ",
                "option_underlying": "510300.SH",
                "start_date": "20250102",
                "end_date": "20250103",
            },
            "heat-expansion-watch",
        ),
    ],
)
def test_every_monitor_agent_runs_through_the_same_runner(
    agent_id: str,
    resources: set[str],
    payload: dict[str, object],
    expected_state: str,
) -> None:
    monitor_request = AgentRequest(
        run_id="all-monitors",
        subject=str(payload["subject"]),
        task_type="research",
        available_resources=resources,
        requested_agent_ids=[agent_id],
        payload=payload,
    )

    result = AgentRunner(data_provider=FakeProvider()).run(monitor_request).results[0]

    assert result.agent_id == agent_id
    assert result.metadata["snapshot"]["state"] == expected_state


def test_monitor_rejects_payload_for_a_different_agent_kind() -> None:
    with pytest.raises(ValueError, match="requires monitor kind crowding_risk"):
        AgentRunner(data_provider=FakeProvider()).run(request("market_regime"))


def test_monitor_validation_fails_before_fetch() -> None:
    invalid = request().model_copy(
        update={
            "payload": {
                "kind": "crowding_risk",
                "subject": "Crowding review",
                "start_date": "20250103",
                "end_date": "20250102",
                "symbol": "000001.SZ",
            }
        }
    )
    with pytest.raises(ValueError, match="start_date must not be later"):
        AgentRunner(data_provider=FakeProvider()).run(invalid)
