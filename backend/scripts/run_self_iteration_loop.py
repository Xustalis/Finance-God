#!/usr/bin/env python3
"""Daemon entrypoint for the continuous self-iteration learning loop.

Runs forever until interrupted (SIGINT/SIGTERM), executing one learning cycle
per interval.  Intended to run as a standalone long-lived process (systemd or a
docker service) so it stays decoupled from the API server lifecycle.

Usage:
    python -m scripts.run_self_iteration_loop            # run continuously
    python -m scripts.run_self_iteration_loop --once     # single cycle (smoke)
    python -m scripts.run_self_iteration_loop --cycles 3 # bounded run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time

from finance_god.learning.contracts import CycleReport, LearningConfig
from finance_god.learning.loop import LearningRuntime

_LOGGER = logging.getLogger("finance_god.learning.daemon")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="run a single cycle and exit",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="run a bounded number of cycles and exit",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="override the seconds between cycles",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="exit 0 when the worker has completed a recent healthy cycle",
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=None,
        help="maximum cycle age in seconds for --healthcheck",
    )
    args = parser.parse_args()
    if args.cycles is not None and args.cycles < 1:
        parser.error("--cycles must be at least 1")
    if args.interval is not None and args.interval <= 0:
        parser.error("--interval must be greater than 0")
    if args.max_age is not None and args.max_age <= 0:
        parser.error("--max-age must be greater than 0")
    return args


async def _run(args: argparse.Namespace) -> None:
    runtime = LearningRuntime.from_environment()
    if args.interval is not None:
        runtime.config.interval_seconds = args.interval
    for note in runtime.startup_notes:
        _LOGGER.warning("startup: %s", note)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows fallback
            pass

    max_cycles = 1 if args.once else args.cycles
    start_cycle = runtime.store.next_cycle_index()
    _LOGGER.info(
        "starting continuous learning loop at cycle %d (knowledge dir: %s)",
        start_cycle,
        runtime.config.knowledge_dir,
    )
    await runtime.loop.run(
        stop_event=stop_event,
        start_cycle=start_cycle,
        max_cycles=max_cycles,
    )
    _LOGGER.info(
        "learning loop stopped; total lessons: %d",
        runtime.store.total_lessons,
    )


def _healthcheck(args: argparse.Namespace) -> int:
    config = LearningConfig.from_environment()
    cycles_dir = config.knowledge_dir / "cycles"
    paths = sorted(cycles_dir.glob("cycle-*.json"), reverse=True)
    if not paths:
        _LOGGER.error("healthcheck: no completed learning cycle")
        return 1
    latest = paths[0]
    max_age = args.max_age or max(config.interval_seconds * 4, 300.0)
    age = time.time() - latest.stat().st_mtime
    if age > max_age:
        _LOGGER.error(
            "healthcheck: latest cycle is stale (age=%.1fs, max=%.1fs)",
            age,
            max_age,
        )
        return 1
    recent = [
        CycleReport.model_validate_json(path.read_text(encoding="utf-8"))
        for path in paths[:3]
    ]
    if len(recent) >= 3 and all(report.status == "error" for report in recent):
        _LOGGER.error("healthcheck: three consecutive cycles failed")
        return 1
    _LOGGER.info(
        "healthcheck: cycle=%d status=%s age=%.1fs",
        recent[0].cycle,
        recent[0].status,
        age,
    )
    return 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args()
    if args.healthcheck:
        raise SystemExit(_healthcheck(args))
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
