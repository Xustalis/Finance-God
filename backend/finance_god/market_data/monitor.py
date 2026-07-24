"""Server-side market monitor: snapshot/alert value objects and detection.

The monitor persists the latest polled snapshot per instrument and, when an
instrument's change crosses a configured magnitude threshold, records a global
market alert. Alerts are deduplicated on *crossing*: a new alert is only raised
when the previous snapshot was below the threshold (or missing), so a persistent
mover does not spam an alert on every poll cycle.

Market data is real; alerts mirror the upstream provider timestamp and never
fabricate a value. This module contains only pure value objects and the pure
``detect_market_alert`` decision — no I/O — so it is trivially testable.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AlertKind(str, Enum):
    SURGE = "surge"
    PLUNGE = "plunge"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class MarketSnapshot(BaseModel):
    """The latest polled fact for one instrument (baseline for detection)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    last: Decimal
    change_percent: Decimal | None
    provider_time: str = Field(min_length=1, max_length=80)
    frequency: str = Field(min_length=1, max_length=40)
    freshness: str = Field(min_length=1, max_length=40)
    retrieved_at: datetime


class MarketAlert(BaseModel):
    """A global, reviewable record of a significant market move."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    alert_id: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    kind: AlertKind
    severity: AlertSeverity
    change_percent: Decimal
    last: Decimal
    message: str = Field(min_length=1, max_length=1000)
    provider_time: str = Field(min_length=1, max_length=80)
    detected_at: datetime


def _magnitude(change_percent: Decimal | None) -> Decimal | None:
    return abs(change_percent) if change_percent is not None else None


def detect_market_alert(
    *,
    previous: MarketSnapshot | None,
    current: MarketSnapshot,
    threshold: Decimal,
    now: datetime,
    alert_id: str,
    escalate_threshold: Decimal | None = None,
) -> MarketAlert | None:
    """Decide whether ``current`` warrants a new alert versus ``previous``.

    Returns ``None`` unless the current absolute change is at or above
    ``threshold`` *and* the previous snapshot was below it (crossing dedupe).
    ``escalate_threshold`` (if given) marks the alert severity ``error``.
    """
    change = current.change_percent
    magnitude = _magnitude(change)
    if change is None or magnitude is None or magnitude < threshold:
        return None
    previous_magnitude = _magnitude(previous.change_percent) if previous else None
    if previous_magnitude is not None and previous_magnitude >= threshold:
        # Already alerted while crossing the threshold; do not repeat.
        return None
    kind = AlertKind.SURGE if change > 0 else AlertKind.PLUNGE
    severity = AlertSeverity.WARNING
    if escalate_threshold is not None and magnitude >= escalate_threshold:
        severity = AlertSeverity.ERROR
    percent_text = f"{change * Decimal(100):.2f}%"
    direction = "大幅上涨" if kind is AlertKind.SURGE else "大幅下跌"
    message = (
        f"{current.name}（{current.symbol}）{direction} {percent_text}，"
        f"最新价 {current.last}（数据时点 {current.provider_time}）。"
    )
    return MarketAlert(
        alert_id=alert_id,
        symbol=current.symbol,
        name=current.name,
        kind=kind,
        severity=severity,
        change_percent=change,
        last=current.last,
        message=message,
        provider_time=current.provider_time,
        detected_at=now,
    )
