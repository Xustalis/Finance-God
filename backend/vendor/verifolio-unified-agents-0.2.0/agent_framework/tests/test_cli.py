from __future__ import annotations

import json

import research_runtime.cli as cli
from research_runtime import AgentPlan, AgentRun
from research_runtime.contracts import AgentAssignment, AgentResult


class FakeRunner:
    def run(self, request):
        return AgentRun(
            run_id=request.run_id,
            plan=AgentPlan(
                run_id=request.run_id,
                assignments=[
                    AgentAssignment(
                        agent_id="tradingagents:fundamentals_analyst",
                        reason="explicitly requested by caller",
                    )
                ],
            ),
            results=[
                AgentResult(
                    agent_id="tradingagents:fundamentals_analyst",
                    summary="done",
                )
            ],
        )


def test_unified_cli_builds_one_agent_request(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli, "_runner_for", lambda request: FakeRunner())

    result = cli.main(
        [
            "--run-id",
            "cli-1",
            "--subject",
            "Example",
            "--task-type",
            "research",
            "--agent-id",
            "tradingagents:fundamentals_analyst",
            "--evidence",
            "E1|Filing|Revenue increased.",
            "--payload-json",
            '{"key":"value"}',
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["run_id"] == "cli-1"
    assert payload["results"][0]["summary"] == "done"

