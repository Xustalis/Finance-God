from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.agent_learning_routes import create_agent_learning_routes
from finance_god.api.auth import AuthenticationError
from finance_god.application.agent_learning_summary import AgentLearningSummaryReader

NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _snapshot(*, lessons: str = "") -> str:
    return f"""{{
      "version": 7,
      "updated_at": "2026-07-25T11:59:00Z",
      "total_lessons": 7,
      "topics": {{"market_learning": 4, "strategy_backtest": 3}},
      "recent": [{lessons}]
    }}"""


def _lesson(index: int, status: str = "verified") -> str:
    return f"""{{
      "lesson_id": "L-{index}",
      "created_at": "2026-07-25T11:{index:02d}:00Z",
      "cycle": {index},
      "topic": "market_learning",
      "kind": "outcome",
      "statement": "结论 {index}",
      "source_run_id": "run-{index}",
      "validation_status": "{status}",
      "validation_method": "walk_forward",
      "tags": ["verified"],
      "invalidation_conditions": ["波动率制度变化"]
    }}"""


def _cycle(cycle: int, *, status: str = "ok", finished_at: str | None = None) -> str:
    finished = (
        f'"finished_at": "{finished_at}"'
        if finished_at is not None
        else '"finished_at": null'
    )
    return f"""{{
      "cycle": {cycle},
      "topic": "market_learning",
      "run_id": "run-{cycle}",
      "status": "{status}",
      "started_at": "2026-07-25T11:58:00Z",
      {finished},
      "notes": ["周期说明"]
    }}"""


def test_summary_reads_recent_verified_lessons_and_limits_to_five(
    tmp_path: Path,
) -> None:
    lessons = ",".join(
        [_lesson(0, "candidate"), *(_lesson(index) for index in range(1, 8))]
    )
    _write(tmp_path / "snapshot.json", _snapshot(lessons=lessons))
    _write(
        tmp_path / "cycles/cycle-000007.json",
        _cycle(7, finished_at="2026-07-25T11:59:00Z"),
    )

    result = AgentLearningSummaryReader(
        tmp_path, interval_seconds=900, now=lambda: NOW
    ).read()

    assert result.status == "healthy"
    assert result.snapshot is not None
    assert result.snapshot.topics == {"market_learning": 4, "strategy_backtest": 3}
    assert [lesson.cycle for lesson in result.recent_verified_lessons] == [
        7,
        6,
        5,
        4,
        3,
    ]
    assert all(
        lesson.validation_method == "walk_forward"
        for lesson in result.recent_verified_lessons
    )


def test_summary_reports_unavailable_before_first_cycle(tmp_path: Path) -> None:
    result = AgentLearningSummaryReader(tmp_path, now=lambda: NOW).read()

    assert result.status == "unavailable"
    assert result.last_cycle is None
    assert result.snapshot is None


def test_summary_reports_stale_cycle(tmp_path: Path) -> None:
    _write(tmp_path / "snapshot.json", _snapshot())
    _write(
        tmp_path / "cycles/cycle-000001.json",
        _cycle(1, finished_at=(NOW - timedelta(hours=2)).isoformat()),
    )

    result = AgentLearningSummaryReader(
        tmp_path, interval_seconds=60, now=lambda: NOW
    ).read()

    assert result.status == "stale"
    assert result.freshness.is_stale is True
    assert result.freshness.age_seconds == 7200


def test_summary_reports_three_consecutive_failures(tmp_path: Path) -> None:
    _write(tmp_path / "snapshot.json", _snapshot())
    for cycle in range(3):
        _write(
            tmp_path / f"cycles/cycle-{cycle:06d}.json",
            _cycle(cycle, status="error", finished_at="2026-07-25T11:59:00Z"),
        )

    result = AgentLearningSummaryReader(tmp_path, now=lambda: NOW).read()

    assert result.status == "error"
    assert result.message == "持续学习最近三个周期均运行失败。"


def test_summary_reports_corrupt_artifact(tmp_path: Path) -> None:
    _write(tmp_path / "snapshot.json", "{not-json")

    result = AgentLearningSummaryReader(tmp_path, now=lambda: NOW).read()

    assert result.status == "error"
    assert result.recent_verified_lessons == []


def test_summary_route_requires_authentication(tmp_path: Path) -> None:
    async def reject(_request):
        raise AuthenticationError("valid Bearer authentication is required")

    app = Starlette(
        routes=[
            Mount(
                "/api/agent-learning",
                routes=create_agent_learning_routes(
                    owner_resolver=reject,
                    reader_provider=lambda: AgentLearningSummaryReader(tmp_path),
                ),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.get("/api/agent-learning/summary")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
