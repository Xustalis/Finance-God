"""Versioned market/category/frequency freshness policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contracts import (
    DataCategory,
    DataFrequency,
    Freshness,
    FreshnessStatus,
    MarketType,
    ReleaseState,
)

FRESHNESS_POLICY_VERSION = "market-freshness-v1"


@dataclass(frozen=True)
class FreshnessPolicyKey:
    workflow_key: str
    market: MarketType
    category: DataCategory
    frequency: DataFrequency


class FreshnessPolicy:
    def __init__(
        self,
        thresholds: dict[FreshnessPolicyKey, int] | None = None,
    ) -> None:
        display_thresholds = {
            FreshnessPolicyKey(
                "market_display",
                MarketType.CN,
                DataCategory.SNAPSHOT,
                DataFrequency.SNAPSHOT,
            ): 5,
            FreshnessPolicyKey(
                "market_display",
                MarketType.CN,
                DataCategory.BAR,
                DataFrequency.MINUTE_1,
            ): 120,
            FreshnessPolicyKey(
                "market_display", MarketType.CN, DataCategory.BAR, DataFrequency.DAILY
            ): 129_600,
            FreshnessPolicyKey(
                "market_display", MarketType.HK, DataCategory.BAR, DataFrequency.DAILY
            ): 129_600,
            FreshnessPolicyKey(
                "market_display", MarketType.US, DataCategory.BAR, DataFrequency.DAILY
            ): 129_600,
            FreshnessPolicyKey(
                "market_display",
                MarketType.CN,
                DataCategory.CALENDAR,
                DataFrequency.DAILY,
            ): 172_800,
            FreshnessPolicyKey(
                "market_display",
                MarketType.HK,
                DataCategory.CALENDAR,
                DataFrequency.DAILY,
            ): 172_800,
            FreshnessPolicyKey(
                "market_display",
                MarketType.US,
                DataCategory.CALENDAR,
                DataFrequency.DAILY,
            ): 172_800,
            FreshnessPolicyKey(
                "market_display",
                MarketType.CN,
                DataCategory.MASTER,
                DataFrequency.STATIC,
            ): 604_800,
            FreshnessPolicyKey(
                "market_display",
                MarketType.HK,
                DataCategory.MASTER,
                DataFrequency.STATIC,
            ): 604_800,
            FreshnessPolicyKey(
                "market_display",
                MarketType.US,
                DataCategory.MASTER,
                DataFrequency.STATIC,
            ): 604_800,
            FreshnessPolicyKey(
                "market_display",
                MarketType.CN,
                DataCategory.FACTOR,
                DataFrequency.DAILY,
            ): 129_600,
        }
        if thresholds is not None:
            self._thresholds = dict(thresholds)
        else:
            trade_thresholds = {
                FreshnessPolicyKey(
                    "trade_plan",
                    key.market,
                    key.category,
                    key.frequency,
                ): value
                for key, value in display_thresholds.items()
            }
            self._thresholds = display_thresholds | trade_thresholds

    def evaluate(
        self,
        *,
        market: MarketType,
        category: DataCategory,
        frequency: DataFrequency,
        data_time: datetime,
        trading_date: str,
        provider_published_at: datetime | None,
        evaluated_at: datetime,
        release_state: ReleaseState,
        workflow_key: str = "market_display",
    ) -> Freshness:
        if data_time.tzinfo is None or evaluated_at.tzinfo is None:
            raise ValueError("freshness evaluation requires timezone-aware timestamps")
        key = FreshnessPolicyKey(workflow_key, market, category, frequency)
        threshold = self._thresholds.get(key)
        if threshold is None:
            raise ValueError(f"no freshness policy for {key}")
        raw_age_seconds = int(
            (evaluated_at.astimezone(data_time.tzinfo) - data_time).total_seconds()
        )
        age_seconds = max(0, raw_age_seconds)
        if release_state in {ReleaseState.IN_SESSION, ReleaseState.CLOSED_PENDING}:
            status = FreshnessStatus.NOT_RELEASED
            reason = "market date exists but the requested data release is not complete"
        elif release_state is ReleaseState.UNKNOWN:
            status = FreshnessStatus.UNKNOWN
            reason = "upstream release state is unknown"
        elif provider_published_at is None:
            status = FreshnessStatus.UNKNOWN
            reason = "provider publication time is unavailable"
        elif raw_age_seconds < 0:
            status = FreshnessStatus.UNKNOWN
            reason = "upstream data timestamp is later than the evaluation time"
        elif age_seconds > threshold:
            status = FreshnessStatus.STALE
            reason = f"age exceeds {threshold}s policy threshold"
        else:
            status = FreshnessStatus.CURRENT
            reason = f"age is within {threshold}s policy threshold"
        return Freshness(
            status=status,
            evaluated_at=evaluated_at,
            data_time=data_time,
            trading_date=trading_date,
            provider_published_at=provider_published_at,
            threshold_seconds=threshold,
            age_seconds=age_seconds,
            release_state=release_state,
            rule_version=FRESHNESS_POLICY_VERSION,
            workflow_key=workflow_key,
            reason=reason,
        )


DEFAULT_FRESHNESS_POLICY = FreshnessPolicy()
