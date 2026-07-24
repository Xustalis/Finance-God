from __future__ import annotations

from research_runtime import AgentRequest, AgentRun

from finance_god.orchestration.multi_agent import MultiAgentRuntime


class Orchestrator:
    """
    Unified orchestrator that delegates to the single source of truth:
    verifolio-research-runtime (0.2.0).
    """

    def __init__(self, multi_agent_runtime: MultiAgentRuntime | None = None) -> None:
        self._multi_agent_runtime = multi_agent_runtime

    def use_multi_agent_runtime(self, runtime: MultiAgentRuntime) -> Orchestrator:
        """Attach the unified runtime (the only supported mode)."""
        self._multi_agent_runtime = runtime
        return self

    async def execute_multi_agent(self, request: AgentRequest) -> AgentRun:
        """Execute a routed Multi-Agent request (the sole supported entry point)."""
        if self._multi_agent_runtime is None:
            raise RuntimeError(
                "Multi-Agent runtime not configured. "
                "Use Orchestrator(multi_agent_runtime=...) or Orchestrator.from_environment()."
            )
        return await self._multi_agent_runtime.run(request)

    @classmethod
    def from_environment(cls) -> "Orchestrator":
        """Convenience factory for production-like setups (mirrors VeriFolio pattern)."""
        from finance_god.orchestration.multi_agent import MultiAgentRuntime
        runtime = MultiAgentRuntime.from_environment()
        return cls(runtime)
