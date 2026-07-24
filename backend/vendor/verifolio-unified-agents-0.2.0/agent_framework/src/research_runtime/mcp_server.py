"""Stdio MCP server for the unified agent registry, router, and runner."""

from __future__ import annotations

import json
from typing import Any

from .catalog import skills
from .config import FmpSettings, PandaDataSettings, Settings
from .contracts import AgentAdapterKind, AgentRequest, ExecutionProfile
from .data_provider import DataProvider, PandaDataProvider
from .definitions import serialize_agent_definition
from .llm import ChatClient, OpenAICompatibleChat
from .registry import AgentRegistry
from .router import AgentRouter
from .runner import AgentRunner


def create_server(
    *,
    chat_client: ChatClient | None = None,
    provider: DataProvider | None = None,
    fmp_settings: FmpSettings | None = None,
):
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "MCP support is not installed. Install with `pip install -e '.[mcp]'`."
        ) from error

    server = FastMCP(
        "VeriFolio Unified Agents",
        instructions=(
            "Plan and run locally registered agents through explicit execution profiles. "
            "External publication and trading actions are never performed by this server."
        ),
    )
    registry = AgentRegistry()
    router = AgentRouter(registry)

    def runner_for(request: AgentRequest) -> AgentRunner:
        plan = router.plan(request)
        adapters = {registry.get(item.agent_id).adapter for item in plan.assignments}
        active_chat = chat_client
        active_provider = provider
        active_fmp = fmp_settings
        if AgentAdapterKind.PROMPT in adapters and active_chat is None:
            active_chat = OpenAICompatibleChat(Settings.from_environment())
        if AgentAdapterKind.DETERMINISTIC_MONITOR in adapters and active_provider is None:
            active_provider = PandaDataProvider(PandaDataSettings.from_environment())
        if AgentAdapterKind.FINROBOT_METRICS in adapters and active_fmp is None:
            active_fmp = FmpSettings.from_environment()
        return AgentRunner(
            registry=registry,
            chat_client=active_chat,
            data_provider=active_provider,
            fmp_settings=active_fmp,
        )

    @server.tool()
    def list_agents(profile: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """List all 44 local agents, optionally filtered by authorized profile."""

        selected_profile = ExecutionProfile(profile) if profile else None
        return {
            "agents": [
                serialize_agent_definition(definition)
                for definition in registry.list()
                if selected_profile is None
                or selected_profile.allows(definition.minimum_profile)
            ]
        }

    @server.tool()
    def get_agent(agent_id: str) -> dict[str, Any]:
        """Return one unified local agent definition."""

        return serialize_agent_definition(registry.get(agent_id))

    @server.tool()
    def plan_agents(request: dict[str, Any]) -> dict[str, Any]:
        """Route a request without executing any agent."""

        validated = AgentRequest.model_validate(request)
        return router.plan(validated).model_dump(mode="json")

    @server.tool()
    def run_agents(request: dict[str, Any]) -> dict[str, Any]:
        """Execute a routed request through the unified LangGraph runner."""

        validated = AgentRequest.model_validate(request)
        return runner_for(validated).run(validated).model_dump(mode="json")

    @server.resource("catalog://agents")
    def agent_catalog() -> str:
        return json.dumps(
            [serialize_agent_definition(item) for item in registry.list()],
            ensure_ascii=False,
            indent=2,
        )

    @server.resource("catalog://skills")
    def skill_catalog() -> str:
        return json.dumps(skills(), ensure_ascii=False, indent=2)

    return server


def main() -> int:
    create_server().run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
