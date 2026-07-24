"""Async integration for the VeriFolio unified multi-agent runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from dotenv import load_dotenv
from research_runtime import (
    AgentDefinition,
    AgentPlan,
    AgentRequest,
    AgentRun,
    AgentRunner,
)
from research_runtime.config import FmpSettings, Settings
from research_runtime.llm import OpenAICompatibleChat

_PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class MultiAgentRuntime:
    """Expose the synchronous unified runtime through Finance-God's async API."""

    def __init__(self, runner: AgentRunner) -> None:
        self._runner = runner

    @classmethod
    def from_environment(
        cls,
        *,
        max_concurrency: int = 4,
        enable_panda_data: bool = False,
        enable_finrobot_metrics: bool = False,
    ) -> MultiAgentRuntime:
        """Build a runtime with explicitly enabled environment-backed adapters."""
        if enable_panda_data:
            raise ValueError(
                "the vendor PandaDataProvider path was removed; inject only the "
                "Finance-God normalized market-data boundary"
            )
        load_dotenv(_PROJECT_ENV_FILE, override=False)
        settings = Settings.from_environment()
        runner = AgentRunner(
            chat_client=OpenAICompatibleChat(settings),
            data_provider=None,
            fmp_settings=(
                FmpSettings.from_environment() if enable_finrobot_metrics else None
            ),
            max_concurrency=max_concurrency,
        )
        return cls(runner)

    async def run(self, request: AgentRequest) -> AgentRun:
        """Route and execute a request without blocking the application's event loop."""
        return await asyncio.to_thread(self._runner.run, request)

    def plan(self, request: AgentRequest) -> AgentPlan:
        """Return the authorized execution plan without running any agent."""
        return self._runner.router.plan(request)

    def list_agents(self) -> tuple[AgentDefinition, ...]:
        """Return all agents registered by the unified runtime."""
        return self._runner.registry.list()
