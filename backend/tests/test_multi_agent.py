from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from finance_god.orchestration import MultiAgentRuntime, Orchestrator
from research_runtime import AgentRequest, AgentRunner
from research_runtime.models import EvidenceRecord


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
    def test_vendor_pandadata_second_source_is_explicitly_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "vendor PandaDataProvider path was removed",
        ):
            MultiAgentRuntime.from_environment(enable_panda_data=True)

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
                },
                clear=True,
            ),
            patch(
                "finance_god.orchestration.multi_agent.load_dotenv"
            ) as load_project_env,
        ):
            runtime = MultiAgentRuntime.from_environment()

        self.assertEqual(len(runtime.list_agents()), 43)
        self.assertEqual(load_project_env.call_args.args[0].name, ".env")

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
