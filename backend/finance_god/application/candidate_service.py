"""Deterministic, explainable portfolio-candidate scoring.

The candidate list is *not* a buy instruction. It surfaces assets the system
proposes for further research given the owner's real simulated holdings and the
target-direction universe. Every candidate is decomposed into five independent,
explainable dimensions — portfolio fit, risk, cost, liquidity and evidence —
and **no mystery aggregate score is ever produced**. When an input is missing
the affected dimension is explicitly marked ``missing`` rather than guessed, and
a candidate whose critical facts are unavailable or in conflict is not tradable.

All numeric bands reuse the canonical pre-submit risk thresholds
(``trading/rules_v1``) so the explanations are consistent with the risk gate the
order will later face; nothing here is fabricated.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from finance_god.domain.simulation_rules import SIMULATION_RULE_VERSION
from finance_god.market_data.service import MarketQuote, QuoteBatch
from finance_god.trading.rules_v1 import (
    HARD_ALL_IN_COST_RATIO,
    HARD_SINGLE_ASSET_RATIO,
    SOFT_ALL_IN_COST_RATIO,
    SOFT_SINGLE_ASSET_RATIO,
)

ZERO = Decimal("0")
# Modelled deterministic execution cost floor for an A-share round trip. This is
# an explicit, documented assumption used only to explain the cost dimension; it
# is never presented as an executed fee.
BASE_COMMISSION_BPS = Decimal("6")
# Turnover (成交额, RMB) bands used to explain liquidity and modelled slippage.
DEEP_LIQUIDITY_AMOUNT = Decimal("1000000000")  # 10e RMB daily turnover
THIN_LIQUIDITY_AMOUNT = Decimal("100000000")  # 1e RMB daily turnover

Dimension = Literal["portfolio_fit", "risk", "cost", "liquidity", "evidence"]
Rating = Literal["strong", "adequate", "weak", "missing"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DimensionScore(StrictModel):
    dimension: Dimension
    label: str
    rating: Rating
    detail: str
    metrics: dict[str, str] = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()


class CandidateExclusion(StrictModel):
    reason_code: str
    detail: str


class Candidate(StrictModel):
    instrument_id: str
    symbol: str
    name: str | None
    asset_type: str | None
    market: str | None
    currency: str | None
    direction: str
    direction_label: str
    purpose: str
    dimensions: tuple[DimensionScore, ...]
    exclusions: tuple[CandidateExclusion, ...] = ()
    tradable: bool
    ignored: bool = False
    ignore_reason: str | None = None
    as_of: str | None = None
    provider: str | None = None


class CandidateResponse(StrictModel):
    generated_at: AwareDatetime
    rule_version: str
    purpose_summary: str
    candidates: tuple[Candidate, ...] = ()
    unavailable_reason: str | None = None


class _DirectionEntry(StrictModel):
    symbol: str
    direction: str
    direction_label: str


# Backend-fixed universe, mirroring the frontend direction desk pools. Only
# A-share symbols with verified real-time PandaData snapshots are used.
_UNIVERSE: tuple[_DirectionEntry, ...] = (
    _DirectionEntry(symbol="000001.SZ", direction="equities", direction_label="权益股票"),
    _DirectionEntry(symbol="600519.SH", direction="equities", direction_label="权益股票"),
    _DirectionEntry(symbol="000002.SZ", direction="equities", direction_label="权益股票"),
    _DirectionEntry(symbol="601318.SH", direction="cash_fixed_income", direction_label="现金固收"),
    _DirectionEntry(symbol="600036.SH", direction="cash_fixed_income", direction_label="现金固收"),
    _DirectionEntry(symbol="000858.SZ", direction="alternatives", direction_label="另类配置"),
    _DirectionEntry(symbol="300750.SZ", direction="alternatives", direction_label="另类配置"),
    _DirectionEntry(symbol="002594.SZ", direction="alternatives", direction_label="另类配置"),
)


class PortfolioReader(Protocol):
    async def positions(self, *, owner_id: str) -> object: ...


QuotesProvider = Callable[[list[str]], Awaitable[QuoteBatch]]


class CandidateScoringService:
    """Score the fixed candidate universe against an owner's real holdings."""

    def __init__(
        self,
        *,
        portfolio: PortfolioReader,
        quotes_provider: QuotesProvider,
        rule_version: str = SIMULATION_RULE_VERSION,
    ) -> None:
        self._portfolio = portfolio
        self._quotes = quotes_provider
        self._rule_version = rule_version

    async def candidates(
        self,
        *,
        owner_id: str,
        now: datetime,
        ignored: Mapping[str, str] | None = None,
    ) -> CandidateResponse:
        ignored = dict(ignored or {})
        held_weights, missing_portfolio = await self._held_weights(owner_id)
        symbols = [entry.symbol for entry in _UNIVERSE]
        quotes_by_symbol: dict[str, MarketQuote] = {}
        quote_errors: dict[str, str] = {}
        unavailable_reason: str | None = None
        try:
            batch = await self._quotes(symbols)
            quotes_by_symbol = {quote.symbol: quote for quote in batch.quotes}
            quote_errors = dict(batch.errors)
        except Exception:  # noqa: BLE001 - explicit safe degradation boundary
            unavailable_reason = "MARKET_DATA_UNAVAILABLE"

        candidates = tuple(
            self._score(
                entry=entry,
                quote=quotes_by_symbol.get(entry.symbol),
                quote_error=quote_errors.get(entry.symbol),
                held_weights=held_weights,
                missing_portfolio=missing_portfolio,
                ignored=ignored,
            )
            for entry in _UNIVERSE
        )
        return CandidateResponse(
            generated_at=now,
            rule_version=self._rule_version,
            purpose_summary=(
                "系统依据目标方向标的池与当前仿真持仓生成待研究候选；"
                "候选不是买入指令，各维度独立解释，不输出单一综合分。"
            ),
            candidates=candidates,
            unavailable_reason=unavailable_reason,
        )

    async def _held_weights(self, owner_id: str) -> tuple[dict[str, Decimal], bool]:
        try:
            view = await self._portfolio.positions(owner_id=owner_id)
        except LookupError:
            # No simulation account yet: portfolio-fit context is unavailable but
            # this is a normal empty state, not an error.
            return {}, False
        except Exception:  # noqa: BLE001 - degrade portfolio-fit explicitly
            return {}, True
        positions = getattr(view, "positions", ())
        total = sum((p.cost_basis_rmb for p in positions), ZERO)
        if total <= ZERO:
            return {}, False
        return {
            p.instrument_id: (p.cost_basis_rmb / total) for p in positions
        }, False

    def _score(
        self,
        *,
        entry: _DirectionEntry,
        quote: MarketQuote | None,
        quote_error: str | None,
        held_weights: dict[str, Decimal],
        missing_portfolio: bool,
        ignored: Mapping[str, str],
    ) -> Candidate:
        dimensions = (
            _portfolio_fit(entry, held_weights, missing_portfolio),
            _risk(quote),
            _cost(quote),
            _liquidity(quote),
            _evidence(quote, quote_error),
        )
        exclusions = _exclusions(entry, quote, held_weights)
        critical_missing = any(
            dim.rating == "missing" and dim.dimension in {"risk", "liquidity", "evidence"}
            for dim in dimensions
        )
        hard_excluded = any(exc.reason_code == "concentration_hard" for exc in exclusions)
        tradable = not critical_missing and not hard_excluded
        weight = held_weights.get(entry.symbol)
        if weight is None:
            purpose = f"对齐目标方向「{entry.direction_label}」，当前组合尚未覆盖，建议研究。"
        else:
            purpose = (
                f"已持有该标的（成本占比 {(weight * 100):.1f}%），"
                f"评估其在「{entry.direction_label}」方向的加仓适配。"
            )
        return Candidate(
            instrument_id=entry.symbol,
            symbol=entry.symbol,
            name=quote.name if quote else None,
            asset_type=quote.asset_type if quote else None,
            market=quote.market if quote else None,
            currency=quote.currency if quote else None,
            direction=entry.direction,
            direction_label=entry.direction_label,
            purpose=purpose,
            dimensions=dimensions,
            exclusions=exclusions,
            tradable=tradable,
            ignored=entry.symbol in ignored,
            ignore_reason=ignored.get(entry.symbol),
            as_of=quote.provider_time if quote else None,
            provider=quote.provider if quote else None,
        )


def _portfolio_fit(
    entry: _DirectionEntry,
    held_weights: dict[str, Decimal],
    missing_portfolio: bool,
) -> DimensionScore:
    label = "组合适配"
    if missing_portfolio:
        return DimensionScore(
            dimension="portfolio_fit",
            label=label,
            rating="missing",
            detail="无法读取当前仿真持仓，组合适配暂不可评估。",
            missing_fields=("portfolio",),
        )
    weight = held_weights.get(entry.symbol)
    if weight is None:
        return DimensionScore(
            dimension="portfolio_fit",
            label=label,
            rating="strong",
            detail=f"组合当前未持有，可补充「{entry.direction_label}」方向敞口。",
            metrics={"current_weight": "0.0%"},
        )
    pct = f"{(weight * 100):.1f}%"
    if weight >= HARD_SINGLE_ASSET_RATIO:
        return DimensionScore(
            dimension="portfolio_fit",
            label=label,
            rating="weak",
            detail=f"已持有且占比 {pct} 超过单一标的硬约束，加仓将放大集中度。",
            metrics={"current_weight": pct, "hard_limit": f"{HARD_SINGLE_ASSET_RATIO * 100:.0f}%"},
        )
    if weight >= SOFT_SINGLE_ASSET_RATIO:
        return DimensionScore(
            dimension="portfolio_fit",
            label=label,
            rating="adequate",
            detail=f"已持有且占比 {pct} 接近软约束，加仓需关注集中度。",
            metrics={"current_weight": pct, "soft_limit": f"{SOFT_SINGLE_ASSET_RATIO * 100:.0f}%"},
        )
    return DimensionScore(
        dimension="portfolio_fit",
        label=label,
        rating="adequate",
        detail=f"已持有且占比 {pct} 处于合理区间，可评估适度调整。",
        metrics={"current_weight": pct},
    )


def _risk(quote: MarketQuote | None) -> DimensionScore:
    label = "风险"
    if quote is None or quote.previous_close is None or quote.previous_close <= ZERO:
        return DimensionScore(
            dimension="risk",
            label=label,
            rating="missing",
            detail="缺少昨收或实时行情，无法估计当日波动。",
            missing_fields=("previous_close", "high", "low"),
        )
    intraday_range = (quote.high - quote.low) / quote.previous_close
    pct = f"{(intraday_range * 100):.2f}%"
    change_pct = (
        f"{quote.change_percent:.2f}%" if quote.change_percent is not None else "—"
    )
    metrics = {"intraday_range": pct, "change_percent": change_pct}
    if intraday_range < Decimal("0.02"):
        return DimensionScore(
            dimension="risk", label=label, rating="strong",
            detail=f"当日振幅 {pct}，波动较低。", metrics=metrics,
        )
    if intraday_range < Decimal("0.05"):
        return DimensionScore(
            dimension="risk", label=label, rating="adequate",
            detail=f"当日振幅 {pct}，波动适中。", metrics=metrics,
        )
    return DimensionScore(
        dimension="risk", label=label, rating="weak",
        detail=f"当日振幅 {pct}，波动偏高，需评估回撤承受度。", metrics=metrics,
    )


def _cost(quote: MarketQuote | None) -> DimensionScore:
    label = "成本"
    if quote is None or quote.amount is None or quote.volume <= ZERO:
        return DimensionScore(
            dimension="cost",
            label=label,
            rating="missing",
            detail="缺少成交额或成交量，无法估计滑点与全成本。",
            missing_fields=("amount", "volume"),
        )
    slippage_bps = _modelled_slippage_bps(quote.amount)
    all_in_ratio = (BASE_COMMISSION_BPS + slippage_bps) / Decimal("10000")
    ratio_pct = f"{(all_in_ratio * 100):.3f}%"
    metrics = {
        "base_commission_bps": f"{BASE_COMMISSION_BPS:.0f}",
        "modelled_slippage_bps": f"{slippage_bps:.0f}",
        "estimated_all_in": ratio_pct,
    }
    if all_in_ratio <= SOFT_ALL_IN_COST_RATIO:
        rating: Rating = "strong"
        detail = f"估算全成本 {ratio_pct} 低于软阈值，成本友好。"
    elif all_in_ratio <= HARD_ALL_IN_COST_RATIO:
        rating = "adequate"
        detail = f"估算全成本 {ratio_pct} 处于软硬阈值之间，需关注滑点。"
    else:
        rating = "weak"
        detail = f"估算全成本 {ratio_pct} 超过硬阈值，成本偏高。"
    return DimensionScore(
        dimension="cost", label=label, rating=rating, detail=detail, metrics=metrics
    )


def _modelled_slippage_bps(amount: Decimal) -> Decimal:
    """Deterministic slippage model: deeper turnover implies lower slippage."""
    if amount >= DEEP_LIQUIDITY_AMOUNT:
        return Decimal("5")
    if amount >= THIN_LIQUIDITY_AMOUNT:
        return Decimal("25")
    return Decimal("80")


def _liquidity(quote: MarketQuote | None) -> DimensionScore:
    label = "流动性"
    if quote is None or quote.amount is None:
        return DimensionScore(
            dimension="liquidity",
            label=label,
            rating="missing",
            detail="缺少成交额，无法评估流动性。",
            missing_fields=("amount",),
        )
    amount_yi = quote.amount / Decimal("100000000")
    metrics = {"turnover_rmb_yi": f"{amount_yi:.2f}", "volume": f"{quote.volume:.0f}"}
    if quote.amount >= DEEP_LIQUIDITY_AMOUNT:
        return DimensionScore(
            dimension="liquidity", label=label, rating="strong",
            detail=f"当日成交额约 {amount_yi:.2f} 亿元，流动性充裕。", metrics=metrics,
        )
    if quote.amount >= THIN_LIQUIDITY_AMOUNT:
        return DimensionScore(
            dimension="liquidity", label=label, rating="adequate",
            detail=f"当日成交额约 {amount_yi:.2f} 亿元，流动性适中。", metrics=metrics,
        )
    return DimensionScore(
        dimension="liquidity", label=label, rating="weak",
        detail=f"当日成交额约 {amount_yi:.2f} 亿元，流动性偏弱。", metrics=metrics,
    )


def _evidence(quote: MarketQuote | None, quote_error: str | None) -> DimensionScore:
    label = "证据完整度"
    if quote is None:
        detail = (
            f"行情获取失败（{quote_error}）。" if quote_error else "行情数据缺失。"
        )
        return DimensionScore(
            dimension="evidence",
            label=label,
            rating="missing",
            detail=detail,
            missing_fields=("quote",),
        )
    metrics = {
        "provider": quote.provider,
        "provider_time": quote.provider_time,
        "freshness": quote.freshness,
        "market_status": quote.market_status,
    }
    if quote.freshness == "fresh":
        return DimensionScore(
            dimension="evidence", label=label, rating="strong",
            detail=f"{quote.provider} 实时快照，时点 {quote.provider_time}。", metrics=metrics,
        )
    return DimensionScore(
        dimension="evidence", label=label, rating="adequate",
        detail=f"{quote.provider} 数据非实时（{quote.freshness}），时点 {quote.provider_time}。",
        metrics=metrics,
    )


def _exclusions(
    entry: _DirectionEntry,
    quote: MarketQuote | None,
    held_weights: dict[str, Decimal],
) -> tuple[CandidateExclusion, ...]:
    exclusions: list[CandidateExclusion] = []
    weight = held_weights.get(entry.symbol)
    if weight is not None and weight >= HARD_SINGLE_ASSET_RATIO:
        exclusions.append(
            CandidateExclusion(
                reason_code="concentration_hard",
                detail=(
                    f"已持有占比 {(weight * 100):.1f}% 超过单一标的硬约束 "
                    f"{HARD_SINGLE_ASSET_RATIO * 100:.0f}%，不建议继续加仓。"
                ),
            )
        )
    if quote is None:
        exclusions.append(
            CandidateExclusion(
                reason_code="data_insufficient",
                detail="缺少实时行情，数据不足时不提供进入交易台入口。",
            )
        )
    return tuple(exclusions)
