"""Explicit, isolated FinRobot Equity adapter for FMP's current stable API."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .config import FmpSettings

_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_FINROBOT_ROOT = _WORKSPACE_ROOT / "references" / "projects" / "finrobot"
_INSTALLED_FINROBOT_ROOT = (
    Path(sys.prefix) / "agent_framework" / "references" / "projects" / "finrobot"
)
_DEFAULT_FINROBOT_ROOT = (
    _SOURCE_FINROBOT_ROOT
    if _SOURCE_FINROBOT_ROOT.is_dir()
    else _INSTALLED_FINROBOT_ROOT
)
_DEFAULT_OUTPUT_ROOT = (
    _WORKSPACE_ROOT / "agent_framework" / "live-runs" / "finrobot"
    if _SOURCE_FINROBOT_ROOT.is_dir()
    else Path(sys.prefix) / "agent_framework" / "live-runs" / "finrobot"
)
_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")


class FinRobotRunError(RuntimeError):
    """Raised when the isolated FinRobot process cannot produce its core artifact."""


@dataclass(frozen=True)
class _FinRobotMetricsRequest:
    """Bounded request passed to the FMP-only FinRobot Equity analysis script."""

    ticker: str
    company_name: str
    years_limit: int = 1
    period: Literal["annual", "quarterly"] = "annual"

    def __post_init__(self) -> None:
        if not _TICKER_PATTERN.fullmatch(self.ticker):
            raise ValueError("ticker must be an uppercase FMP-compatible symbol")
        if not self.company_name.strip():
            raise ValueError("company_name must not be empty")
        if not 1 <= self.years_limit <= 5:
            raise ValueError("years_limit must be between 1 and 5")


@dataclass(frozen=True)
class _FinRobotMetricsResult:
    """Safe metadata for one generated local FinRobot analysis artifact set."""

    run_id: str
    ticker: str
    company_name: str
    output_dir: str
    files: list[str]

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


CommandExecutor = Callable[..., subprocess.CompletedProcess[str]]


class _FinRobotMetricsProcess:
    """Run FinRobot's financial-data processor in an isolated subprocess."""

    def __init__(
        self,
        settings: FmpSettings,
        *,
        finrobot_root: Path = _DEFAULT_FINROBOT_ROOT,
        output_root: Path = _DEFAULT_OUTPUT_ROOT,
        executor: CommandExecutor = subprocess.run,
    ) -> None:
        self._settings = settings
        self._finrobot_root = finrobot_root
        self._output_root = output_root
        self._executor = executor

    def run(self, request: _FinRobotMetricsRequest) -> _FinRobotMetricsResult:
        source_dir = self._finrobot_root / "finrobot_equity" / "core" / "src"
        processor = source_dir / "modules" / "financial_data_processor.py"
        if not processor.is_file():
            raise FinRobotRunError(f"FinRobot financial-data processor is unavailable: {processor}")

        run_id = self._run_id(request.ticker)
        output_dir = self._output_root / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        command = self._command(source_dir, request, output_dir)
        environment = os.environ.copy()
        environment["FMP_API_KEY"] = self._settings.api_key
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = self._executor(
                command,
                cwd=self._finrobot_root,
                env=environment,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise FinRobotRunError(
                "FinRobot Equity analysis exceeded the 120-second limit"
            ) from error

        if completed.returncode:
            raise FinRobotRunError(
                f"FinRobot Equity analysis exited with code {completed.returncode}; "
                "stdout and stderr were not retained because FMP URLs include credentials."
            )
        expected = output_dir / "financial_metrics_and_forecasts.csv"
        if not expected.is_file():
            raise FinRobotRunError(
                "FinRobot Equity analysis completed without its core metrics artifact"
            )
        files = sorted(
            path.relative_to(output_dir).as_posix()
            for path in output_dir.rglob("*")
            if path.is_file()
        )
        return _FinRobotMetricsResult(
            run_id=run_id,
            ticker=request.ticker,
            company_name=request.company_name,
            output_dir=str(output_dir),
            files=files,
        )

    @staticmethod
    def _command(
        source_dir: Path,
        request: _FinRobotMetricsRequest,
        output_dir: Path,
    ) -> list[str]:
        return [
            sys.executable,
            "-m",
            "research_runtime.finrobot_compat",
            "--ticker",
            request.ticker,
            "--years-limit",
            str(request.years_limit),
            "--period",
            request.period,
            "--finrobot-source",
            str(source_dir),
            "--output-dir",
            str(output_dir),
        ]

    @staticmethod
    def _run_id(ticker: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{ticker.lower()}-{timestamp}"
