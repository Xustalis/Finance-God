"""Pure unit tests for the market anomaly detection decision."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from finance_god.market_data.monitor import (
    AlertKind,
    AlertSeverity,
    MarketSnapshot,
    detect_market_alert,
)

NOW = datetime(2026, 7, 24, 9, 30, tzinfo=UTC)


def _snapshot(change_percent: str | None, *, symbol: str = "600519.SH") -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        name="贵州茅台",
        last=Decimal("1680.00"),
        change_percent=Decimal(change_percent) if change_percent is not None else None,
        provider_time="2026-07-24T09:30:00+08:00",
        frequency="1min",
        freshness="realtime",
        retrieved_at=NOW,
    )


def test_no_alert_when_change_is_below_threshold() -> None:
    alert = detect_market_alert(
        previous=None,
        current=_snapshot("0.03"),
        threshold=Decimal("0.05"),
        now=NOW,
        alert_id="alert-1",
    )
    assert alert is None


def test_no_alert_when_change_percent_missing() -> None:
    alert = detect_market_alert(
        previous=None,
        current=_snapshot(None),
        threshold=Decimal("0.05"),
        now=NOW,
        alert_id="alert-1",
    )
    assert alert is None


def test_surge_alert_when_crossing_up_from_no_baseline() -> None:
    alert = detect_market_alert(
        previous=None,
        current=_snapshot("0.061"),
        threshold=Decimal("0.05"),
        now=NOW,
        alert_id="alert-1",
    )
    assert alert is not None
    assert alert.kind is AlertKind.SURGE
    assert alert.severity is AlertSeverity.WARNING
    assert alert.change_percent == Decimal("0.061")
    assert "6.10%" in alert.message
    assert alert.provider_time == "2026-07-24T09:30:00+08:00"


def test_plunge_alert_when_crossing_down() -> None:
    alert = detect_market_alert(
        previous=_snapshot("-0.01"),
        current=_snapshot("-0.07"),
        threshold=Decimal("0.05"),
        now=NOW,
        alert_id="alert-1",
    )
    assert alert is not None
    assert alert.kind is AlertKind.PLUNGE


def test_no_repeat_alert_while_already_above_threshold() -> None:
    # Previous snapshot already crossed the threshold: do not spam again.
    alert = detect_market_alert(
        previous=_snapshot("0.06"),
        current=_snapshot("0.07"),
        threshold=Decimal("0.05"),
        now=NOW,
        alert_id="alert-1",
    )
    assert alert is None


def test_escalated_severity_when_magnitude_exceeds_escalate_threshold() -> None:
    alert = detect_market_alert(
        previous=None,
        current=_snapshot("-0.11"),
        threshold=Decimal("0.05"),
        now=NOW,
        alert_id="alert-1",
        escalate_threshold=Decimal("0.09"),
    )
    assert alert is not None
    assert alert.kind is AlertKind.PLUNGE
    assert alert.severity is AlertSeverity.ERROR
