from __future__ import annotations

import asyncio
import json

import pytest

from research_runtime.mcp_server import create_server


class FakeChatClient:
    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(
            {
                "summary": "MCP result",
                "claims": [
                    {
                        "kind": "fact",
                        "statement": "Evidence-backed MCP result.",
                        "evidence_ids": ["E1"],
                        "unknowns": [],
                        "invalidation_conditions": [],
                    }
                ],
                "proposed_actions": [],
            }
        )


def test_mcp_server_exposes_only_unified_agent_tools() -> None:
    pytest.importorskip("mcp")
    server = create_server(chat_client=FakeChatClient())

    async def exercise_server() -> None:
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == {
            "list_agents",
            "get_agent",
            "plan_agents",
            "run_agents",
        }
        _content, definitions = await server.call_tool("list_agents", {})
        assert len(definitions["agents"]) == 43
        _content, plan = await server.call_tool(
            "plan_agents",
            {
                "request": {
                    "run_id": "mcp-plan",
                    "subject": "Example",
                    "task_type": "research",
                }
            },
        )
        assert len(plan["assignments"]) == 5
        _content, result = await server.call_tool(
            "run_agents",
            {
                "request": {
                    "run_id": "mcp-run",
                    "subject": "Example",
                    "task_type": "research",
                    "requested_agent_ids": ["tradingagents:fundamentals_analyst"],
                    "evidence": [
                        {
                            "identifier": "E1",
                            "source": "Filing",
                            "excerpt": "Revenue increased.",
                        }
                    ],
                }
            },
        )
        assert result["results"][0]["agent_id"] == "tradingagents:fundamentals_analyst"

    asyncio.run(exercise_server())
