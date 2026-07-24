from __future__ import annotations

from pathlib import Path

from research_runtime import AgentAdapterKind, AgentRegistry

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def test_registry_contains_every_source_backed_local_agent_once() -> None:
    registry = AgentRegistry()
    definitions = registry.list()

    assert len(registry) == 43
    assert len({item.agent_id for item in definitions}) == 43
    assert sum(item.adapter == AgentAdapterKind.PROMPT for item in definitions) == 38
    assert sum(item.adapter == AgentAdapterKind.DETERMINISTIC_MONITOR for item in definitions) == 4
    assert sum(item.adapter == AgentAdapterKind.FINROBOT_METRICS for item in definitions) == 1
    assert "quantskills:liangshuyuan:publish-agent" not in {
        item.agent_id for item in definitions
    }
    assert not {
        action
        for item in definitions
        for action in item.external_actions
        if action.startswith("github")
    }


def test_every_definition_has_local_code_and_an_upstream_basis() -> None:
    for definition in AgentRegistry().list():
        assert (WORKSPACE_ROOT / definition.source_path).is_file()
        assert (WORKSPACE_ROOT / definition.upstream_path).exists()
        assert definition.description
        assert definition.task_types
