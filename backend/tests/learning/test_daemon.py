from __future__ import annotations

import argparse
from pathlib import Path

from scripts.run_self_iteration_loop import _healthcheck

from finance_god.learning.contracts import CycleReport
from finance_god.learning.knowledge_store import JsonKnowledgeStore


def test_healthcheck_accepts_recent_cycle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FINANCE_GOD_KNOWLEDGE_DIR", str(tmp_path))
    store = JsonKnowledgeStore(tmp_path)
    store.record_cycle(
        CycleReport(
            cycle=0,
            topic="market_learning",
            run_id="learn-mkt-000000",
        )
    )

    result = _healthcheck(argparse.Namespace(max_age=60.0))

    assert result == 0


def test_healthcheck_rejects_three_consecutive_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FINANCE_GOD_KNOWLEDGE_DIR", str(tmp_path))
    store = JsonKnowledgeStore(tmp_path)
    for cycle in range(3):
        store.record_cycle(
            CycleReport(
                cycle=cycle,
                topic="market_learning",
                run_id=f"learn-mkt-{cycle:06d}",
                status="error",
            )
        )

    result = _healthcheck(argparse.Namespace(max_age=60.0))

    assert result == 1
