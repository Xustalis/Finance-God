from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from finance_god.orchestration import MultiAgentRuntime, Orchestrator
from research_runtime import AgentRequest, AgentRunner
from research_runtime.models import DataArtifact, DataQuery, EvidenceRecord, PandaDataDataset


class MonitorDataProvider:
    def fetch(self, query: DataQuery) -> DataArtifact:
        records_by_dataset = {
            PandaDataDataset.MARKET_BARS: [
                {"date": "20260722", "close": 100.0},
                {"date": "20260723", "close": 102.0},
            ],
            PandaDataDataset.MARGIN: [
                {"date": "20260722", "total_balance": 100.0, "short_balance": 10.0},
                {"date": "20260723", "total_balance": 110.0, "short_balance": 12.0},
            ],
            PandaDataDataset.LHB_LIST: [
                {"date": "20260723", "amount": 10.0, "change_rate": 2.0},
            ],
            PandaDataDataset.FUTURE_DOMINANT_CORR: [
                {"pair": "RB:JM", "correlation": 0.4},
            ],
            PandaDataDataset.OPTION_IMPLIED_VOLATILITY: [
                {"date": "20260723", "implied_volatility": 25.0},
            ],
            PandaDataDataset.OPTION_UNDERLYING_VOLATILITY: [
                {"date": "20260723", "historical_volatility": 0.2},
            ],
        }
        records = records_by_dataset[query.dataset]
        return DataArtifact(
            provider="test",
            query=query,
            retrieved_at=datetime.now(timezone.utc),
            row_count=len(records),
            columns=sorted({key for record in records for key in record}),
            records=records,
        )


class JsonChatClient:
    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(
            {
                "summary": "Evidence-backed analysis.",
                "claims": [
                    {
                        "kind": "fact",
                        "statement": "Revenue increased.",
                        "evidence_ids": ["E1"],
                        "unknowns": [],
                        "invalidation_conditions": [],
                    }
                ],
                "proposed_actions": [],
            }
        )


class MultiAgentIntegrationTest(unittest.IsolatedAsyncioTestCase):
    def test_environment_factory_injects_finance_god_market_data_provider(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "ARK_API_KEY": "test-key",
                    "ARK_BASE_URL": "https://api.openai.com/v1",
                    "ARK_MODEL": "test-model",
                    "FMP_API_KEY": "test-key",
                },
                clear=True,
            ),
            patch(
                "finance_god.orchestration.multi_agent.FinanceGodMarketDataProvider.from_environment",
                return_value=MonitorDataProvider(),
            ) as provider_factory,
        ):
            runtime = MultiAgentRuntime.from_environment(enable_panda_data=True)

        self.assertEqual(len(runtime.list_agents()), 43)
        provider_factory.assert_called_once_with()

    def test_runtime_exposes_the_complete_agent_catalog(self) -> None:
        runtime = MultiAgentRuntime(AgentRunner())

        self.assertEqual(len(runtime.list_agents()), 43)

    def test_environment_factory_uses_explicit_model_settings(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "ARK_API_KEY": "test-key",
                    "ARK_BASE_URL": "https://api.openai.com/v1",
                    "ARK_MODEL": "test-model",
                    "FMP_API_KEY": "test-key",
                },
                clear=True,
            ),
            patch(
                "finance_god.orchestration.multi_agent.load_dotenv"
            ) as load_project_env,
            patch(
                "finance_god.orchestration.multi_agent.FinanceGodMarketDataProvider.from_environment",
                return_value=MonitorDataProvider(),
            ),
        ):
            runtime = MultiAgentRuntime.from_environment()

        self.assertEqual(len(runtime.list_agents()), 43)
        self.assertEqual(load_project_env.call_args.args[0].name, ".env")

    async def test_all_monitor_agents_execute_when_product_data_boundary_is_injected(
        self,
    ) -> None:
        cases = (
            (
                "quantskills:agent-correlation-break-research",
                {"future_dominant_corr"},
                {
                    "kind": "correlation_break",
                    "subject": "Correlation",
                    "future_symbols": ["RB", "JM"],
                    "start_date": "20260722",
                    "end_date": "20260723",
                },
            ),
            (
                "quantskills:agent-crowding-risk-monitor",
                {"margin", "lhb_list"},
                {
                    "kind": "crowding_risk",
                    "subject": "Crowding",
                    "symbol": "000001.SZ",
                    "start_date": "20260722",
                    "end_date": "20260723",
                },
            ),
            (
                "quantskills:agent-derivatives-skew-sentiment-monitor",
                {"option_implied_volatility", "option_underlying_volatility"},
                {
                    "kind": "derivatives_iv_premium",
                    "subject": "Volatility",
                    "option_underlying": "510300.SH",
                    "start_date": "20260722",
                    "end_date": "20260723",
                },
            ),
            (
                "quantskills:agent-market-regime-monitor",
                {"market_bars", "margin", "lhb_list", "option_underlying_volatility"},
                {
                    "kind": "market_regime",
                    "subject": "Regime",
                    "symbol": "000001.SZ",
                    "option_underlying": "510300.SH",
                    "start_date": "20260722",
                    "end_date": "20260723",
                },
            ),
        )
        runtime = MultiAgentRuntime(AgentRunner(data_provider=MonitorDataProvider()))

        for agent_id, resources, payload in cases:
            result = await runtime.run(
                AgentRequest(
                    run_id=f"monitor-{payload['kind']}",
                    subject=str(payload["subject"]),
                    task_type="research",
                    available_resources=resources,
                    requested_agent_ids=[agent_id],
                    payload=payload,
                )
            )
            self.assertEqual(result.results[0].agent_id, agent_id)

    async def test_orchestrator_executes_unified_agents_in_requested_order(
        self,
    ) -> None:
        request = AgentRequest(
            run_id="finance-god-test",
            subject="Example company",
            task_type="research",
            requested_agent_ids=[
                "tradingagents:fundamentals_analyst",
                "tradingagents:bear_researcher",
            ],
            evidence=[
                EvidenceRecord(
                    identifier="E1",
                    source="Company filing",
                    excerpt="Revenue increased.",
                )
            ],
        )
        runtime = MultiAgentRuntime(
            AgentRunner(chat_client=JsonChatClient(), max_concurrency=2)
        )
        orchestrator = Orchestrator(multi_agent_runtime=runtime)

        result = await orchestrator.execute_multi_agent(request)

        self.assertEqual(
            [item.agent_id for item in result.results],
            request.requested_agent_ids,
        )
        self.assertEqual(len(result.results), 2)

    async def test_multi_agent_execution_requires_explicit_configuration(self) -> None:
        request = AgentRequest(
            run_id="missing-runtime",
            subject="Example company",
            task_type="research",
            requested_agent_ids=["tradingagents:fundamentals_analyst"],
            evidence=[
                EvidenceRecord(
                    identifier="E1",
                    source="Company filing",
                    excerpt="Revenue increased.",
                )
            ],
        )

        with self.assertRaisesRegex(RuntimeError, "not configured"):
            await Orchestrator().execute_multi_agent(request)

    async def test_removed_github_publish_agent_cannot_be_routed(self) -> None:
        request = AgentRequest(
            run_id="removed-publisher",
            subject="Publish a skill",
            task_type="publishing",
            requested_agent_ids=["quantskills:liangshuyuan:publish-agent"],
            evidence=[
                EvidenceRecord(
                    identifier="E1",
                    source="Test evidence",
                    excerpt="A publication request.",
                )
            ],
        )
        runtime = MultiAgentRuntime(AgentRunner(chat_client=JsonChatClient()))

        with self.assertRaisesRegex(ValueError, "unknown agent"):
            await runtime.run(request)


if __name__ == "__main__":
    unittest.main()
