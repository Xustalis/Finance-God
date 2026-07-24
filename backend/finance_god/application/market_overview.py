"""Versioned market-indicator view for the T01 overview.

The browser renders this DTO verbatim.  All values that classify, rank, or
summarize market facts are calculated here so their algorithm and inputs are
auditable together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict

from finance_god.market_data.service import MarketQuote, QuoteBatch

MARKET_OVERVIEW_ALGORITHM_VERSION = "market-overview-v1"


class ViewModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MarketOverviewObject(ViewModel):
    type: Literal["market_overview"] = "market_overview"
    id: str
    symbols: tuple[str, ...]


class MarketOverviewDataStatus(ViewModel):
    provider: str
    provider_time: str | None
    frequency: str | None
    freshness: Literal["fresh", "delayed", "stale", "unknown"]
    last_success_at: datetime


class MarketSignal(ViewModel):
    tendency: Literal["positive", "cautious", "neutral", "unavailable"]
    tendency_label: str
    consistency_percent: Decimal | None
    definition: str


class MarketForce(ViewModel):
    code: Literal["leader", "laggard", "average_change", "volume_leader"]
    label: str


class MarketIndicator(ViewModel):
    code: Literal[
        "advance_ratio",
        "change_dispersion",
        "average_change",
        "fresh_coverage",
    ]
    name: str
    value: Decimal | None
    unit: Literal["percent", "percentage_points"]
    definition: str


class MarketOverviewData(ViewModel):
    quotes: tuple[MarketQuote, ...]
    signal: MarketSignal
    forces: tuple[MarketForce, ...]
    indicators: tuple[MarketIndicator, ...]


class MarketOverviewWarning(ViewModel):
    code: str
    severity: Literal["info", "warning", "blocking"]
    message: str
    affected_fields: tuple[str, ...]


class MarketOverviewView(ViewModel):
    object: MarketOverviewObject
    data: MarketOverviewData
    version: str
    algorithm_version: str
    generated_at: datetime
    data_status: MarketOverviewDataStatus
    warnings: tuple[MarketOverviewWarning, ...]


def build_market_overview(batch: QuoteBatch) -> MarketOverviewView:
    """Build the authoritative T01 market-indicator DTO from one quote batch."""
    quotes = tuple(sorted(batch.quotes, key=lambda quote: quote.symbol))
    changes = tuple(
        quote.change_percent
        for quote in quotes
        if quote.change_percent is not None
    )
    advancing = sum(change > 0 for change in changes)
    declining = sum(change < 0 for change in changes)
    directional = advancing + declining
    advance_ratio = _percent(Decimal(advancing), Decimal(len(changes)))
    agreement = _percent(
        Decimal(max(advancing, declining)),
        Decimal(directional),
    )

    if not changes:
        tendency = "unavailable"
        tendency_label = "不可用"
        agreement = None
    elif advance_ratio is not None and advance_ratio >= Decimal("60"):
        tendency = "positive"
        tendency_label = "积极"
    elif advance_ratio is not None and advance_ratio <= Decimal("40"):
        tendency = "cautious"
        tendency_label = "谨慎"
    else:
        tendency = "neutral"
        tendency_label = "中性"

    average_change = (
        sum(changes, Decimal(0)) / Decimal(len(changes))
        if changes
        else None
    )
    dispersion = _population_standard_deviation(changes)
    fresh_count = sum(quote.freshness == "current" for quote in quotes)
    fresh_coverage = _percent(Decimal(fresh_count), Decimal(len(quotes)))

    warnings = _warnings(batch, changes)
    generated_at = datetime.now(UTC)
    return MarketOverviewView(
        object=MarketOverviewObject(
            id="cn-equity-requested-coverage",
            symbols=tuple(quote.symbol for quote in quotes),
        ),
        data=MarketOverviewData(
            quotes=quotes,
            signal=MarketSignal(
                tendency=tendency,
                tendency_label=tendency_label,
                consistency_percent=agreement,
                definition=(
                    "基于本 DTO 覆盖标的的涨跌方向；上涨占比不低于 60% 为积极，"
                    "不高于 40% 为谨慎，其余为中性。方向一致性为非平盘标的中"
                    "占多数方向的比例，不代表全市场或交易建议。"
                ),
            ),
            forces=_forces(quotes, average_change),
            indicators=(
                MarketIndicator(
                    code="advance_ratio",
                    name="上涨覆盖率",
                    value=advance_ratio,
                    unit="percent",
                    definition="有可用涨跌幅的覆盖标的中，上涨标的所占比例。",
                ),
                MarketIndicator(
                    code="change_dispersion",
                    name="涨跌幅离散度",
                    value=_percentage_points(dispersion),
                    unit="percentage_points",
                    definition="覆盖标的涨跌幅的总体标准差，以百分点表示。",
                ),
                MarketIndicator(
                    code="average_change",
                    name="平均涨跌幅",
                    value=_percentage_points(average_change),
                    unit="percentage_points",
                    definition="有可用涨跌幅的覆盖标的算术平均涨跌幅。",
                ),
                MarketIndicator(
                    code="fresh_coverage",
                    name="新鲜数据覆盖率",
                    value=fresh_coverage,
                    unit="percent",
                    definition="本 DTO 覆盖标的中 freshness 为 current 的比例。",
                ),
            ),
        ),
        version=_version(quotes, batch.errors),
        algorithm_version=MARKET_OVERVIEW_ALGORITHM_VERSION,
        generated_at=generated_at,
        data_status=MarketOverviewDataStatus(
            provider=batch.provider,
            provider_time=max(
                (quote.provider_time for quote in quotes),
                default=None,
            ),
            frequency=_frequency(quotes),
            freshness=_freshness(quotes),
            last_success_at=max(
                (quote.retrieved_at for quote in quotes),
                default=batch.requested_at,
            ),
        ),
        warnings=warnings,
    )


def _forces(
    quotes: tuple[MarketQuote, ...],
    average_change: Decimal | None,
) -> tuple[MarketForce, ...]:
    with_change = tuple(
        quote for quote in quotes if quote.change_percent is not None
    )
    forces: list[MarketForce] = []
    if with_change:
        leader = max(with_change, key=lambda quote: quote.change_percent or Decimal(0))
        laggard = min(
            with_change,
            key=lambda quote: quote.change_percent or Decimal(0),
        )
        if leader.change_percent is not None and leader.change_percent > 0:
            forces.append(
                MarketForce(
                    code="leader",
                    label=(
                        f"{leader.symbol} 领涨 "
                        f"{_format_percentage_points(leader.change_percent)}"
                    ),
                )
            )
        if laggard.change_percent is not None and laggard.change_percent < 0:
            forces.append(
                MarketForce(
                    code="laggard",
                    label=(
                        f"{laggard.symbol} 领跌 "
                        f"{_format_percentage_points(laggard.change_percent)}"
                    ),
                )
            )
        if average_change is not None:
            forces.append(
                MarketForce(
                    code="average_change",
                    label=(
                        "覆盖标的平均涨跌幅 "
                        f"{_format_percentage_points(average_change)}"
                    ),
                )
            )
    if quotes:
        volume_leader = max(quotes, key=lambda quote: quote.volume)
        forces.append(
            MarketForce(
                code="volume_leader",
                label=f"{volume_leader.symbol} 成交量居覆盖标的首位",
            )
        )
    return tuple(forces)


def _warnings(
    batch: QuoteBatch,
    changes: tuple[Decimal, ...],
) -> tuple[MarketOverviewWarning, ...]:
    warnings: list[MarketOverviewWarning] = []
    if batch.errors:
        warnings.append(
            MarketOverviewWarning(
                code="PARTIAL_QUOTE_FAILURE",
                severity="warning",
                message="部分请求标的行情不可用，统计只覆盖成功返回的标的。",
                affected_fields=("data.signal", "data.forces", "data.indicators"),
            )
        )
    if not changes:
        warnings.append(
            MarketOverviewWarning(
                code="CHANGE_PERCENT_UNAVAILABLE",
                severity="blocking",
                message="覆盖标的均缺少涨跌幅，方向与涨跌统计不可用。",
                affected_fields=(
                    "data.signal",
                    "data.indicators.advance_ratio",
                    "data.indicators.change_dispersion",
                    "data.indicators.average_change",
                ),
            )
        )
    return tuple(warnings)


def _version(quotes: tuple[MarketQuote, ...], errors: dict[str, str]) -> str:
    input_identity = "|".join(
        ":".join(
            (
                quote.symbol,
                quote.provider_time,
                quote.capability_version,
                quote.instrument_master_version,
                str(quote.last),
                str(quote.change_percent),
            )
        )
        for quote in quotes
    )
    error_identity = "|".join(
        f"{symbol}:{code}" for symbol, code in sorted(errors.items())
    )
    digest = sha256(
        (
            f"{MARKET_OVERVIEW_ALGORITHM_VERSION}|"
            f"{input_identity}|{error_identity}"
        ).encode()
    ).hexdigest()
    return f"market-overview:{digest}"


def _frequency(quotes: tuple[MarketQuote, ...]) -> str | None:
    frequencies = sorted({quote.frequency for quote in quotes})
    return ", ".join(frequencies) if frequencies else None


def _freshness(
    quotes: tuple[MarketQuote, ...],
) -> Literal["fresh", "delayed", "stale", "unknown"]:
    if not quotes:
        return "unknown"
    statuses = {quote.freshness for quote in quotes}
    if "stale" in statuses:
        return "stale"
    if "not_released" in statuses:
        return "delayed"
    if statuses == {"current"}:
        return "fresh"
    return "unknown"


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return (numerator / denominator * Decimal(100)).quantize(Decimal("0.01"))


def _population_standard_deviation(
    values: tuple[Decimal, ...],
) -> Decimal | None:
    if not values:
        return None
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
    return variance.sqrt()


def _percentage_points(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return (value * Decimal(100)).quantize(Decimal("0.01"))


def _format_percentage_points(value: Decimal) -> str:
    percentage_points = _percentage_points(value) or Decimal(0)
    return f"{percentage_points:+.2f}%"
