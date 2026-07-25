from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from research_runtime import AgentRequest, AgentRunner
from research_runtime.models import (
    DataArtifact,
    DataQuery,
    EvidenceRecord,
    PandaDataDataset,
)

from finance_god.orchestration import MultiAgentRuntime, Orchestrator


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


class QuickCommandChatClient:
    def __init__(self, response: str | list[str]) -> None:
        self.responses = [response] if isinstance(response, str) else response
        self.system_prompt = ""
        self.user_prompt = ""
        self.calls = 0

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class DeskTurnChatClient:
    def __init__(self) -> None:
        self.system_prompt = ""
        self.user_prompt = ""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return json.dumps(
            {
                "routing_reason": "可直接依据脱敏画像回答。",
                "answer_text": "你的风险等级为进取型。",
                "ui_actions": [],
            },
            ensure_ascii=False,
        )


class MultiAgentIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_desk_turn_prompt_includes_safe_profile_projection(self) -> None:
        chat = DeskTurnChatClient()
        runtime = MultiAgentRuntime(AgentRunner(), chat_client=chat)

        turn = await runtime.compose_desk_turn(
            message="平安银行适配我的风险吗？",
            section="information",
            symbol="000001.SZ",
            mode="answer",
            workflow_title=None,
            action_catalog=(),
            profile_projection={
                "available": True,
                "risk_level": "aggressive",
                "loss_tolerance_percent": 25,
            },
            portfolio_projection={
                "available": True,
                "simulation": True,
                "positions": [{"instrument_id": "000001.SZ", "quantity": "100"}],
            },
        )

        self.assertEqual(turn["answer_text"], "你的风险等级为进取型。")
        self.assertIn('"risk_level": "aggressive"', chat.user_prompt)
        self.assertIn('"instrument_id": "000001.SZ"', chat.user_prompt)
        self.assertIn("available=true 时必须使用", chat.system_prompt)

    async def test_model_generates_contextual_desk_quick_commands(self) -> None:
        chat = QuickCommandChatClient(
            '["贵州茅台量价背离得到确认吗？","贵州茅台哪项现金流证据可能推翻判断？","贵州茅台稳健画像下先核查什么风险？"]'
        )
        runtime = MultiAgentRuntime(AgentRunner(), chat_client=chat)

        commands = await runtime.generate_desk_quick_commands(
            section="portfolio",
            symbol="600519.SH",
            instrument_name="贵州茅台",
            profile_projection={"risk_level": "medium"},
        )

        self.assertEqual(len(commands), 3)
        self.assertIn("600519.SH", chat.user_prompt)
        self.assertIn("贵州茅台", chat.user_prompt)
        self.assertIn("medium", chat.user_prompt)
        self.assertIn("不为显得完整而机械凑成三点", chat.system_prompt)
        self.assertIn("不得为了行文流畅补造事实", chat.system_prompt)

    async def test_model_quick_commands_reject_duplicate_output(self) -> None:
        chat = QuickCommandChatClient(
            '["平安银行同一条","平安银行同一条","平安银行另一条"]'
        )
        runtime = MultiAgentRuntime(AgentRunner(), chat_client=chat)

        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            await runtime.generate_desk_quick_commands(
                section="information",
                symbol="000001.SZ",
                instrument_name="平安银行",
                profile_projection={},
            )

    async def test_model_repairs_invalid_quick_commands_once(self) -> None:
        chat = QuickCommandChatClient(
            [
                '["分析当前标的","分析当前标的","分析当前标的"]',
                '["平安银行当前结论依据是什么？","平安银行有哪些反方风险？","平安银行下一步应补什么证据？"]',
            ]
        )
        runtime = MultiAgentRuntime(AgentRunner(), chat_client=chat)

        commands = await runtime.generate_desk_quick_commands(
            stage="after_answer",
            section="information",
            symbol="000001.SZ",
            instrument_name="平安银行",
            profile_projection={},
            answer_text="回答内容",
        )

        self.assertEqual(len(commands), 3)
        self.assertEqual(chat.calls, 2)
        self.assertIn("回答内容", chat.user_prompt)

    async def test_model_rejects_forbidden_quick_commands_after_repair(self) -> None:
        chat = QuickCommandChatClient(
            '["替我下单买入平安银行","平安银行提交订单","平安银行直接下单"]'
        )
        runtime = MultiAgentRuntime(AgentRunner(), chat_client=chat)

        with self.assertRaisesRegex(RuntimeError, "forbidden"):
            await runtime.generate_desk_quick_commands(
                stage="after_workflow",
                section="trading",
                symbol="000001.SZ",
                instrument_name="平安银行",
                profile_projection={},
                workflow_evidence={"conclusion": "结论"},
            )
        self.assertEqual(chat.calls, 2)

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
            runtime = MultiAgentRuntime.from_environment(
                enable_panda_data=True,
                enable_finrobot_metrics=False,
            )

        self.assertEqual(len(runtime.list_agents()), 43)
        self.assertIn("workspace", runtime.available_resources)
        self.assertNotIn("fmp", runtime.available_resources)
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
