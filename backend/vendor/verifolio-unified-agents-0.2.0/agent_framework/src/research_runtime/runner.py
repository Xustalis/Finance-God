"""LangGraph orchestration for the unified agent runtime."""

from __future__ import annotations

from operator import add
from typing import Annotated

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .adapters import AdapterResolver
from .config import FmpSettings
from .contracts import AgentContext, AgentRequest, AgentResult, AgentRun
from .data_provider import DataProvider
from .llm import ChatClient
from .registry import AgentRegistry
from .router import AgentRouter


class _RunState(TypedDict):
    results: Annotated[list[AgentResult], add]


class AgentRunner:
    """Execute routed agents sequentially by default or independently with bounded concurrency."""

    def __init__(
        self,
        *,
        registry: AgentRegistry | None = None,
        chat_client: ChatClient | None = None,
        data_provider: DataProvider | None = None,
        fmp_settings: FmpSettings | None = None,
        max_concurrency: int = 1,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self.registry = registry or AgentRegistry()
        self.router = AgentRouter(self.registry)
        self._max_concurrency = max_concurrency
        self._adapters = AdapterResolver(
            chat_client=chat_client,
            data_provider=data_provider,
            fmp_settings=fmp_settings,
        )

    def run(self, request: AgentRequest) -> AgentRun:
        plan = self.router.plan(request)
        graph = StateGraph(_RunState)
        previous_node = START
        for index, assignment in enumerate(plan.assignments, start=1):
            node_name = f"agent_{index}"
            graph.add_node(
                node_name,
                self._node(assignment.agent_id, request),
            )
            if self._max_concurrency == 1:
                graph.add_edge(previous_node, node_name)
                previous_node = node_name
            else:
                graph.add_edge(START, node_name)
                graph.add_edge(node_name, END)
        if self._max_concurrency == 1:
            graph.add_edge(previous_node, END)
        final_state = graph.compile().invoke(
            {"results": []},
            config={"max_concurrency": self._max_concurrency},
        )
        results_by_agent = {result.agent_id: result for result in final_state["results"]}
        ordered_results = [
            results_by_agent[assignment.agent_id] for assignment in plan.assignments
        ]
        return AgentRun(run_id=request.run_id, plan=plan, results=ordered_results)

    def _node(self, agent_id: str, request: AgentRequest):
        definition = self.registry.get(agent_id)
        adapter = self._adapters.resolve(definition)

        def execute(state: _RunState) -> dict[str, list[AgentResult]]:
            previous_results = state["results"]
            evidence = [
                *request.evidence,
                *[
                    item
                    for result in previous_results
                    for item in result.evidence
                ],
            ]
            result = adapter.run(
                definition,
                AgentContext(
                    request=request,
                    evidence=evidence,
                    previous_results=previous_results,
                ),
            )
            return {"results": [result]}

        return execute
