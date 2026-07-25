from __future__ import annotations

import json
from threading import Event, Lock

import pytest

from research_runtime import (
    AgentAdapterKind,
    AgentRegistry,
    AgentRequest,
    AgentRunner,
    ExecutionProfile,
)
from research_runtime.models import EvidenceRecord


class JsonChatClient:
    def __init__(self, *, evidence_id: str = "E1") -> None:
        self.evidence_id = evidence_id
        self.prompts: list[str] = []

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append(system_prompt + user_prompt)
        return json.dumps(
            {
                "summary": "structured result",
                "claims": [
                    {
                        "kind": "fact",
                        "statement": "Evidence-backed statement.",
                        "evidence_ids": [self.evidence_id],
                        "unknowns": [],
                        "invalidation_conditions": [],
                    }
                ],
                "proposed_actions": [],
            }
        )


class ConcurrentJsonChatClient(JsonChatClient):
    def __init__(self) -> None:
        super().__init__()
        self._lock = Lock()
        self._release = Event()
        self._active = 0
        self.peak_concurrency = 0

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        with self._lock:
            self._active += 1
            self.peak_concurrency = max(self.peak_concurrency, self._active)
            if self.peak_concurrency >= 2:
                self._release.set()
        if not self._release.wait(timeout=1):
            raise RuntimeError("prompt agents did not execute concurrently")
        try:
            return super().complete(system_prompt=system_prompt, user_prompt=user_prompt)
        finally:
            with self._lock:
                self._active -= 1


def prompt_request(agent_ids: list[str]) -> AgentRequest:
    return AgentRequest(
        run_id="prompt-run",
        subject="Example task",
        task_type="research",
        profile=ExecutionProfile.EXTERNAL,
        available_resources={"workspace"},
        requested_agent_ids=agent_ids,
        evidence=[
            EvidenceRecord(identifier="E1", source="Filing", excerpt="Revenue increased.")
        ],
    )


def test_langgraph_runner_preserves_explicit_order_and_prior_results() -> None:
    client = JsonChatClient()
    agent_ids = [
        "tradingagents:fundamentals_analyst",
        "tradingagents:bear_researcher",
    ]

    result = AgentRunner(chat_client=client).run(prompt_request(agent_ids))

    assert [item.agent_id for item in result.results] == agent_ids
    assert result.results[0].claims[0].author_agent_id == agent_ids[0]
    assert agent_ids[0] in client.prompts[1]


def test_parallel_mode_runs_independently_and_preserves_plan_order() -> None:
    client = ConcurrentJsonChatClient()
    agent_ids = [
        "tradingagents:fundamentals_analyst",
        "tradingagents:bear_researcher",
    ]

    result = AgentRunner(chat_client=client, max_concurrency=2).run(
        prompt_request(agent_ids)
    )

    assert [item.agent_id for item in result.results] == agent_ids
    assert result.results[0].claims[0].author_agent_id == agent_ids[0]
    assert client.peak_concurrency == 2
    bear_prompt = next(prompt for prompt in client.prompts if f"Agent: {agent_ids[1]}" in prompt)
    assert agent_ids[0] not in bear_prompt


def test_runner_rejects_invalid_concurrency_limit() -> None:
    with pytest.raises(ValueError, match="max_concurrency"):
        AgentRunner(max_concurrency=0)


def test_every_prompt_agent_executes_through_the_same_runner_contract() -> None:
    prompt_agents = [
        item.agent_id
        for item in AgentRegistry().list()
        if item.adapter == AgentAdapterKind.PROMPT
    ]
    client = JsonChatClient()
    runner = AgentRunner(chat_client=client)

    for agent_id in prompt_agents:
        result = runner.run(prompt_request([agent_id]))
        assert result.results[0].agent_id == agent_id
        assert result.results[0].claims[0].evidence_ids == ["E1"]

    assert len(prompt_agents) == 38


def test_prompt_agent_rejects_unknown_evidence_reference() -> None:
    with pytest.raises(ValueError, match="unavailable evidence"):
        AgentRunner(chat_client=JsonChatClient(evidence_id="UNKNOWN")).run(
            prompt_request(["tradingagents:fundamentals_analyst"])
        )


def test_research_prompt_uses_a_real_evidence_id_and_consistent_claim_rules() -> None:
    client = JsonChatClient(evidence_id="source-42")
    request = prompt_request(["tradingagents:fundamentals_analyst"]).model_copy(
        update={
            "evidence": [
                EvidenceRecord(
                    identifier="source-42",
                    source="Filing",
                    excerpt="Revenue increased.",
                )
            ]
        }
    )

    AgentRunner(chat_client=client).run(request)

    prompt = client.prompts[0]
    assert '"evidence_ids":["source-42"]' in prompt
    assert "For the first research role, claims must be non-empty" in prompt
    assert "return an empty claims list instead of paraphrasing" in prompt
    assert "materially distinct fact or inference" in prompt


def test_prompt_honors_requested_response_language() -> None:
    client = JsonChatClient()
    request = prompt_request(["tradingagents:fundamentals_analyst"]).model_copy(
        update={
            "payload": {
                "response_language": "zh-CN",
                "response_requirements": "所有面向用户的文本使用简体中文。",
            }
        }
    )

    AgentRunner(chat_client=client).run(request)

    prompt = client.prompts[0]
    assert "Payload.response_language" in prompt
    assert "Payload.response_requirements" in prompt


def test_prompt_agent_requires_evidence() -> None:
    request = prompt_request(["tradingagents:fundamentals_analyst"]).model_copy(
        update={"evidence": []}
    )
    with pytest.raises(ValueError, match="requires at least one evidence"):
        AgentRunner(chat_client=JsonChatClient()).run(request)


class InvalidJsonClient:
    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        return "not-json"


def test_prompt_agent_surfaces_structured_output_failure() -> None:
    with pytest.raises(ValueError, match="invalid structured response"):
        AgentRunner(chat_client=InvalidJsonClient()).run(
            prompt_request(["tradingagents:fundamentals_analyst"])
        )
