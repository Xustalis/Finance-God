"""Read-only PandaData monitor adapters built from public Agent contracts."""

from __future__ import annotations

from collections.abc import Iterable
from math import isfinite
from statistics import mean, median

from .models import (
    DataArtifact,
    DataQuery,
    PandaDataDataset,
    PandaMonitorKind,
    PandaMonitorRequest,
    PandaMonitorSnapshot,
)


def build_monitor_queries(request: PandaMonitorRequest) -> list[DataQuery]:
    """Create the minimal, deterministic query plan for one monitor kind."""

    if request.kind == PandaMonitorKind.CORRELATION_BREAK:
        queries = [
            DataQuery(
                identifier="corr-current",
                dataset=PandaDataDataset.FUTURE_DOMINANT_CORR,
                symbols=request.future_symbols,
                start_date=request.start_date,
                end_date=request.end_date,
            )
        ]
        if request.baseline_start_date and request.baseline_end_date:
            queries.append(
                DataQuery(
                    identifier="corr-baseline",
                    dataset=PandaDataDataset.FUTURE_DOMINANT_CORR,
                    symbols=request.future_symbols,
                    start_date=request.baseline_start_date,
                    end_date=request.baseline_end_date,
                )
            )
        return queries
    if request.kind == PandaMonitorKind.CROWDING_RISK:
        return _funding_and_lhb_queries(request)
    if request.kind == PandaMonitorKind.DERIVATIVES_IV_PREMIUM:
        return _option_queries(request)
    return [
        DataQuery(
            identifier="regime-index",
            dataset=PandaDataDataset.MARKET_BARS,
            symbols=[request.index_symbol],
            start_date=request.start_date,
            end_date=request.end_date,
            market_type="index",
        ),
        *_funding_and_lhb_queries(request),
        *_option_hv_query(request),
    ]


def analyze_monitor(
    request: PandaMonitorRequest, artifacts: Iterable[DataArtifact]
) -> PandaMonitorSnapshot:
    """Evaluate one monitor from already-fetched artifacts only."""

    artifact_by_id = {artifact.query.identifier: artifact for artifact in artifacts}
    if request.kind == PandaMonitorKind.CORRELATION_BREAK:
        return _analyze_correlation(request, artifact_by_id)
    if request.kind == PandaMonitorKind.CROWDING_RISK:
        return _analyze_crowding(artifact_by_id)
    if request.kind == PandaMonitorKind.DERIVATIVES_IV_PREMIUM:
        return _analyze_iv_premium(request, artifact_by_id)
    return _analyze_regime(artifact_by_id)


def _funding_and_lhb_queries(request: PandaMonitorRequest) -> list[DataQuery]:
    return [
        DataQuery(
            identifier="funding",
            dataset=PandaDataDataset.MARGIN,
            symbols=[request.symbol or ""],
            start_date=request.start_date,
            end_date=request.end_date,
        ),
        DataQuery(
            identifier="lhb-market-events",
            dataset=PandaDataDataset.LHB_LIST,
            start_date=request.start_date,
            end_date=request.end_date,
        ),
    ]


def _option_queries(request: PandaMonitorRequest) -> list[DataQuery]:
    return [
        DataQuery(
            identifier="iv",
            dataset=PandaDataDataset.OPTION_IMPLIED_VOLATILITY,
            symbols=request.option_symbols,
            start_date=request.end_date,
            end_date=request.end_date,
        ),
        *_option_hv_query(request),
    ]


def _option_hv_query(request: PandaMonitorRequest) -> list[DataQuery]:
    return [
        DataQuery(
            identifier="underlying-hv",
            dataset=PandaDataDataset.OPTION_UNDERLYING_VOLATILITY,
            symbols=[request.option_underlying or ""],
            start_date=request.end_date,
            end_date=request.end_date,
            volatility_period=request.volatility_period,
        )
    ]


def _analyze_correlation(
    request: PandaMonitorRequest, artifacts: dict[str, DataArtifact]
) -> PandaMonitorSnapshot:
    current = _unique_cross_correlations(artifacts["corr-current"].records)
    baseline = (
        _unique_cross_correlations(artifacts["corr-baseline"].records)
        if "corr-baseline" in artifacts
        else {}
    )
    current_mean = mean(current.values()) if current else None
    if not baseline:
        return PandaMonitorSnapshot(
            kind=request.kind,
            state="correlation-structure-observed",
            confidence="low",
            metrics={"pair_count": len(current), "current_mean_correlation": current_mean},
            limitations=["No baseline window was supplied; correlation change cannot be assessed."],
        )
    shared_pairs = sorted(set(current).intersection(baseline))
    shifts = [abs(current[pair] - baseline[pair]) for pair in shared_pairs]
    mean_shift = mean(shifts) if shifts else None
    state = (
        "correlation-break-watch"
        if mean_shift is not None and mean_shift >= 0.2
        else "correlation-stable-watch"
    )
    return PandaMonitorSnapshot(
        kind=request.kind,
        state=state,
        confidence="medium" if len(shared_pairs) >= 2 else "low",
        metrics={
            "current_pair_count": len(current),
            "baseline_pair_count": len(baseline),
            "comparable_pair_count": len(shared_pairs),
            "current_mean_correlation": current_mean,
            "mean_absolute_correlation_shift": mean_shift,
        },
        limitations=[]
        if shared_pairs
        else ["No comparable non-self correlation pairs were returned."],
    )


def _analyze_crowding(artifacts: dict[str, DataArtifact]) -> PandaMonitorSnapshot:
    margin = _sort_by_date(artifacts["funding"].records)
    lhb = artifacts["lhb-market-events"].records
    funding_change = _percent_change(
        _number(margin[0].get("total_balance")), _number(margin[-1].get("total_balance"))
    )
    lhb_change = _mean_field(lhb, "change_rate")
    if lhb_change is None:
        state = "crowding-partial-observation"
    elif (funding_change or 0) > 0 and lhb_change > 0:
        state = "crowding-watch"
    else:
        state = "crowding-mixed"
    limitations = [
        "Funding is symbol-scoped while LHB events are market-scoped; "
        "interpret as a cross-scope watch."
    ]
    if lhb_change is None:
        limitations.append("LHB change_rate has no finite values; event direction is unavailable.")
    return PandaMonitorSnapshot(
        kind=PandaMonitorKind.CROWDING_RISK,
        state=state,
        confidence="medium" if len(margin) >= 2 and lhb_change is not None else "low",
        metrics={
            "funding_observation_count": len(margin),
            "market_event_count": len(lhb),
            "funding_total_balance_change": funding_change,
            "short_balance_change": _percent_change(
                _number(margin[0].get("short_balance")), _number(margin[-1].get("short_balance"))
            ),
            "market_event_mean_change_rate": lhb_change,
            "market_event_mean_amount": _mean_field(lhb, "amount"),
        },
        limitations=limitations,
    )


def _analyze_iv_premium(
    request: PandaMonitorRequest, artifacts: dict[str, DataArtifact]
) -> PandaMonitorSnapshot:
    iv_values = _numbers(artifacts["iv"].records, "implied_volatility")
    hv_values = _numbers(artifacts["underlying-hv"].records, "historical_volatility")
    iv = median(iv_values) if iv_values else None
    hv = median(hv_values) if hv_values else None
    hv_percent = hv * 100 if hv is not None and abs(hv) <= 1 else hv
    premium = iv - hv_percent if iv is not None and hv_percent is not None else None
    scope = "provided_option_symbols" if request.option_symbols else "market_wide_iv"
    return PandaMonitorSnapshot(
        kind=request.kind,
        state="iv-premium-watch" if premium is not None and premium > 0 else "iv-neutral-watch",
        confidence="medium" if iv is not None and hv_percent is not None else "low",
        metrics={
            "iv_observation_count": len(iv_values),
            "median_implied_volatility": iv,
            "underlying_historical_volatility_pct": hv_percent,
            "iv_minus_hv": premium,
            "iv_scope": scope,
        },
        limitations=(
            []
            if request.option_symbols
            else ["IV is market-wide, not a strike/expiry matched skew measure for the underlying."]
        ),
    )


def _analyze_regime(artifacts: dict[str, DataArtifact]) -> PandaMonitorSnapshot:
    bars = _sort_by_date(artifacts["regime-index"].records)
    margin = _sort_by_date(artifacts["funding"].records)
    lhb = artifacts["lhb-market-events"].records
    index_return = _percent_change(_number(bars[0].get("close")), _number(bars[-1].get("close")))
    funding_change = _percent_change(
        _number(margin[0].get("total_balance")), _number(margin[-1].get("total_balance"))
    )
    lhb_change = _mean_field(lhb, "change_rate")
    if lhb_change is None:
        state = "regime-partial-observation"
    elif (index_return or 0) > 0 and (funding_change or 0) > 0 and lhb_change > 0:
        state = "heat-expansion-watch"
    else:
        state = "mixed-regime-watch"
    hv_values = _numbers(artifacts["underlying-hv"].records, "historical_volatility")
    limitations = [
        "No market breadth dataset was supplied; LHB events are not a breadth substitute."
    ]
    if lhb_change is None:
        limitations.append("LHB change_rate has no finite values; event direction is unavailable.")
    return PandaMonitorSnapshot(
        kind=PandaMonitorKind.MARKET_REGIME,
        state=state,
        confidence="medium"
        if len(bars) >= 2 and len(margin) >= 2 and lhb_change is not None
        else "low",
        metrics={
            "index_return": index_return,
            "funding_total_balance_change": funding_change,
            "market_event_mean_change_rate": lhb_change,
            "underlying_historical_volatility": median(hv_values) if hv_values else None,
            "index_observation_count": len(bars),
            "market_event_count": len(lhb),
        },
        limitations=limitations,
    )


def _unique_cross_correlations(rows: list[dict[str, object]]) -> dict[tuple[str, str], float]:
    values: dict[tuple[str, str], float] = {}
    for row in rows:
        pair = str(row.get("pair", ""))
        parts = [part.strip() for part in pair.split(":", maxsplit=1)]
        value = _number(row.get("correlation"))
        if len(parts) != 2 or not parts[0] or parts[0] == parts[1] or value is None:
            continue
        values[tuple(sorted(parts))] = value
    return values


def _sort_by_date(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(rows, key=lambda row: str(row.get("date", "")))


def _numbers(rows: list[dict[str, object]], field: str) -> list[float]:
    return [value for value in (_number(row.get(field)) for row in rows) if value is not None]


def _mean_field(rows: list[dict[str, object]], field: str) -> float | None:
    values = _numbers(rows, field)
    return mean(values) if values else None


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _percent_change(first: float | None, last: float | None) -> float | None:
    if first is None or last is None or first == 0:
        return None
    return (last - first) / abs(first)
