from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from research_runtime import AgentRequest, AgentRunner, AssetKind, ExecutionProfile
from research_runtime.config import FmpSettings
from research_runtime.finrobot_adapter import (
    FinRobotRunError,
    _FinRobotMetricsProcess,
    _FinRobotMetricsRequest,
    _FinRobotMetricsResult,
)


def _finrobot_root(tmp_path: Path) -> Path:
    script = tmp_path / "finrobot" / "finrobot_equity" / "core" / "src"
    (script / "modules").mkdir(parents=True)
    (script / "modules" / "financial_data_processor.py").write_text(
        "# fixture\n",
        encoding="utf-8",
    )
    return tmp_path / "finrobot"


def test_metrics_process_is_internal_and_returns_artifact_metadata(tmp_path: Path) -> None:
    def executor(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        output_dir = Path(command[command.index("--output-dir") + 1])
        assert "test-fmp-key" not in command
        assert kwargs["env"]["FMP_API_KEY"] == "test-fmp-key"
        assert kwargs["capture_output"] is True
        (output_dir / "financial_metrics_and_forecasts.csv").write_text(
            "metric,2024A\nrevenue,1\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    result = _FinRobotMetricsProcess(
        FmpSettings(api_key="test-fmp-key"),
        finrobot_root=_finrobot_root(tmp_path),
        output_root=tmp_path / "runs",
        executor=executor,
    ).run(_FinRobotMetricsRequest(ticker="AAPL", company_name="Apple Inc."))

    assert result.files == ["financial_metrics_and_forecasts.csv"]
    assert result.ticker == "AAPL"


def test_metrics_process_hides_subprocess_output(tmp_path: Path) -> None:
    def executor(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            returncode=1,
            stdout="https://financialmodelingprep.com/?apikey=test-fmp-key",
            stderr="request failed",
        )

    runner = _FinRobotMetricsProcess(
        FmpSettings(api_key="test-fmp-key"),
        finrobot_root=_finrobot_root(tmp_path),
        output_root=tmp_path / "runs",
        executor=executor,
    )
    with pytest.raises(FinRobotRunError) as error:
        runner.run(_FinRobotMetricsRequest(ticker="AAPL", company_name="Apple Inc."))

    assert "test-fmp-key" not in str(error.value)


def test_finrobot_metrics_agent_runs_through_the_unified_runner(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_run(
        self: _FinRobotMetricsProcess,
        request: _FinRobotMetricsRequest,
    ) -> _FinRobotMetricsResult:
        return _FinRobotMetricsResult(
            run_id="aapl-test",
            ticker=request.ticker,
            company_name=request.company_name,
            output_dir=str(tmp_path),
            files=["financial_metrics_and_forecasts.csv"],
        )

    monkeypatch.setattr(_FinRobotMetricsProcess, "run", fake_run)
    request = AgentRequest(
        run_id="finrobot-1",
        subject="Apple metrics",
        task_type="data_analysis",
        profile=ExecutionProfile.WORKSPACE,
        asset_kind=AssetKind.EQUITY,
        available_resources={"fmp", "workspace"},
        requested_agent_ids=["finrobot:equity:fmp-stable-metrics"],
        payload={"ticker": "AAPL", "company_name": "Apple Inc."},
    )

    result = AgentRunner(fmp_settings=FmpSettings(api_key="test-key")).run(request)

    assert result.results[0].agent_id == "finrobot:equity:fmp-stable-metrics"
    assert result.results[0].artifacts[0].kind == "finrobot_metric"
