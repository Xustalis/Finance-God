from __future__ import annotations

import json
import subprocess
import sys

from research_runtime.catalog import agents, resolve_skill, skills, verify_catalog


def test_catalog_is_generated_from_the_43_agent_registry() -> None:
    summary = verify_catalog()
    identifiers = {item["agent_id"] for item in agents()}

    assert summary == {"agents": 43, "skills": 32, "paths_valid": 1}
    assert len(identifiers) == 43
    assert "quantskills:agent-macro-driven-rotation" not in identifiers
    assert "ai-trader:platform-agent-identity" not in identifiers
    assert {item["source"] for item in agents()} == {
        "FinRobot",
        "QuantSkills",
        "TradingAgents",
    }


def test_skill_resolution_remains_source_backed() -> None:
    assert resolve_skill("references:projects:ai-trader:skills:market-intel").is_file()
    assert len(skills()) == 32


def test_catalog_cli_verifies_generated_artifacts() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "research_runtime.catalog", "--verify"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"agents": 43, "skills": 32, "paths_valid": 1}
