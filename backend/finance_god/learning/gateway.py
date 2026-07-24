"""Agent gateway: the connection between the learning loop and the runtime.

This is the single seam where the self-iteration loop talks to the *current*
multi-agent runtime.  It accepts already-assembled evidence (prior lessons plus
fresh observations) and routes one :class:`AgentRequest` through the exact same
:class:`Orchestrator` the rest of Finance-God uses, so learning consumes and
strengthens the same governed agents rather than a parallel stack.
"""

from __future__ import annotations

from research_runtime import AgentRequest, AgentRun, AssetKind
from research_runtime.models import EvidenceRecord

from finance_god.orchestration.orchestrator import Orchestrator


class OrchestratorAgentGateway:
    """Route learning requests through the shared multi-agent orchestrator."""

    def __init__(
        self,
        orchestrator: Orchestrator,
        *,
        asset_kind: AssetKind = AssetKind.MARKET,
    ) -> None:
        self._orchestrator = orchestrator
        self._asset_kind = asset_kind

    async def reason(
        self,
        *,
        run_id: str,
        subject: str,
        task_type: str,
        evidence: list[EvidenceRecord],
        max_agents: int,
    ) -> AgentRun:
        request = AgentRequest(
            run_id=run_id,
            subject=subject[:500],
            task_type=task_type,
            asset_kind=self._asset_kind,
            evidence=evidence,
            max_agents=max_agents,
        )
        return await self._orchestrator.execute_multi_agent(request)


__all__ = ["OrchestratorAgentGateway"]
