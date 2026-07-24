#!/usr/bin/env python3
"""
Finance-God Main Entry Point
Unified entry point for Finance-God (V1.0).
Uses the single orchestration source from verifolio-research-runtime.
"""

import asyncio

from finance_god.orchestration import MultiAgentRuntime, Orchestrator
from research_runtime import AgentRequest, AssetKind
from research_runtime.models import EvidenceRecord


async def main() -> None:
    # Build runtime (uses .env + OpenAI-compatible endpoint)
    runtime = MultiAgentRuntime.from_environment(max_concurrency=4)

    # Create orchestrator
    orch = Orchestrator(runtime)

    # Run a simple demo
    request = AgentRequest(
        run_id="finance-god-demo",
        subject="AAPL",
        task_type="research",
        asset_kind=AssetKind.EQUITY,
        evidence=[
            EvidenceRecord(
                identifier="E1",
                source="Company filing",
                excerpt="Strong earnings growth expected.",
            )
        ],
    )

    print("=== Finance-God Multi-Agent Demo ===")
    result = await orch.execute_multi_agent(request)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
