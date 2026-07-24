"""Investment mandate — the persisted, versioned trading authorization.

Reuses the deterministic authorization vocabulary from :mod:`access` (autonomy
levels, status, scope allow-lists and limits) and adds a concrete, ownable,
versioned record that the simulation risk boundary and the T00 authorization UI
operate on.  Every authorization change creates a **new version** and never
overwrites history; the current authorization is the highest version for an
owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .access import (
    ALLOWED_ASSETS,
    ALLOWED_MARKETS,
    ALLOWED_ORDER_TYPES,
    ALLOWED_SIDES,
    SHORT_MARKETS,
    AuthorizationLimits,
    AuthorizationStatus,
    AutonomyLevel,
    FrozenModel,
)

MANDATE_VALIDITY = timedelta(days=365)

#: Lenient simulation defaults.  Ratios stay at their maximum (1) so that the
#: auto-created default mandate never blocks pre-existing manual order flows;
#: the single-order amount cap is generous but finite so the limit path is
#: still exercised.
DEFAULT_LIMITS = AuthorizationLimits(
    max_single_order_amount=Decimal("1000000"),
    max_daily_turnover_amount=Decimal("5000000"),
    max_single_asset_ratio=Decimal("1"),
    max_broad_etf_ratio=Decimal("1"),
    max_otc_fund_ratio=Decimal("1"),
    max_industry_ratio=Decimal("1"),
    max_gross_ratio=Decimal("1"),
    max_short_gross_ratio=Decimal("1"),
    max_single_short_ratio=Decimal("1"),
    max_price_deviation_ratio=Decimal("1"),
    max_slippage_bps=Decimal("100"),
    max_all_in_cost_ratio=Decimal("1"),
)

_CN_SUFFIXES = (".SH", ".SZ", ".BJ")


class InvestmentMandate(FrozenModel):
    """One immutable version of a user's trading authorization."""

    mandate_id: str = Field(min_length=1, max_length=160)
    owner_user_id: str = Field(min_length=1, max_length=160)
    version: int = Field(ge=1)
    status: AuthorizationStatus
    autonomy_level: AutonomyLevel
    allowed_markets: tuple[str, ...] = Field(min_length=1)
    allowed_assets: tuple[str, ...] = Field(min_length=1)
    allowed_sides: tuple[str, ...] = Field(min_length=1)
    allowed_order_types: tuple[str, ...] = Field(min_length=1)
    short_markets: tuple[str, ...]
    limits: AuthorizationLimits
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    created_at: AwareDatetime
    created_by: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=500)

    @field_validator(
        "allowed_markets",
        "allowed_assets",
        "allowed_sides",
        "allowed_order_types",
        "short_markets",
        mode="before",
    )
    @classmethod
    def normalize_scope(cls, values: object) -> tuple[str, ...]:
        if not isinstance(values, (tuple, list)):
            raise ValueError("mandate scope must be a sequence")
        normalized = tuple(str(value).strip() for value in values)
        if any(not value or len(value) > 80 for value in normalized):
            raise ValueError("mandate scope values must be non-blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("mandate scope cannot contain duplicates")
        return tuple(sorted(normalized))

    @model_validator(mode="after")
    def validate_scope_values(self) -> Self:
        scopes = (
            ("allowed_markets", self.allowed_markets, ALLOWED_MARKETS),
            ("allowed_assets", self.allowed_assets, ALLOWED_ASSETS),
            ("allowed_sides", self.allowed_sides, ALLOWED_SIDES),
            ("allowed_order_types", self.allowed_order_types, ALLOWED_ORDER_TYPES),
            ("short_markets", self.short_markets, SHORT_MARKETS),
        )
        for name, values, allowed in scopes:
            unknown = set(values) - allowed
            if unknown:
                raise ValueError(f"{name} contains unsupported values: {sorted(unknown)}")
        if not set(self.short_markets).issubset(self.allowed_markets):
            raise ValueError("short_markets must be a subset of allowed_markets")
        return self

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("mandate validity must end after it begins")
        return self

    def is_active(self, now: datetime) -> bool:
        """A mandate authorizes new orders only while active and inside its window."""
        return (
            self.status is AuthorizationStatus.ACTIVE
            and self.valid_from <= now < self.valid_until
        )

    def effective_status(self, now: datetime) -> AuthorizationStatus:
        """Status as observed at ``now`` — an active-but-elapsed window reads EXPIRED."""
        if self.status is AuthorizationStatus.ACTIVE and now >= self.valid_until:
            return AuthorizationStatus.EXPIRED
        return self.status


@dataclass(frozen=True)
class AuthorizationDenial:
    """A single deterministic reason an order intent is not authorized."""

    code: str
    message: str


def default_mandate(
    *, mandate_id: str, owner_user_id: str, now: datetime, actor: str
) -> InvestmentMandate:
    """First-run default: an active L0 mandate that keeps manual trading usable."""
    return InvestmentMandate(
        mandate_id=mandate_id,
        owner_user_id=owner_user_id,
        version=1,
        status=AuthorizationStatus.ACTIVE,
        autonomy_level=AutonomyLevel.L0,
        allowed_markets=("CN", "HK", "US"),
        allowed_assets=("etf", "lof", "otc_fund", "stock"),
        allowed_sides=("buy", "sell"),
        allowed_order_types=("fund", "limit", "market"),
        short_markets=(),
        limits=DEFAULT_LIMITS,
        valid_from=now,
        valid_until=now + MANDATE_VALIDITY,
        created_at=now,
        created_by=actor,
        note="系统默认仿真授权(首次进入自动创建)",
    )


def order_notional(
    *,
    order_type: str,
    quantity: Decimal | None,
    amount: Decimal | None,
    limit_price: Decimal | None,
    reference_price: Decimal | None,
) -> Decimal | None:
    """Best-effort single-order notional for the single-order amount cap.

    Fund orders that carry an ``amount`` use it directly; exchange orders use
    ``quantity`` times the limit price, falling back to a stored reference
    price.  Returns ``None`` when no price is available so the cap is skipped
    rather than guessed.
    """
    if amount is not None:
        return amount
    if quantity is None:
        return None
    price = limit_price if order_type == "limit" else reference_price
    if price is None:
        return None
    return quantity * price


def market_of(instrument_id: str) -> str:
    """Infer the trading market from an instrument code suffix.

    Deterministic and dependency-free: ``.SH``/``.SZ``/``.BJ`` are CN venues,
    ``.HK`` is Hong Kong, everything else is treated as US.
    """
    upper = instrument_id.strip().upper()
    if upper.endswith(_CN_SUFFIXES):
        return "CN"
    if upper.endswith(".HK"):
        return "HK"
    return "US"


def evaluate_order_authorization(
    mandate: InvestmentMandate,
    *,
    now: datetime,
    side: str,
    order_type: str,
    instrument_id: str,
    notional: Decimal | None,
) -> tuple[AuthorizationDenial, ...]:
    """Deterministically decide whether an order intent is authorized.

    Returns the hard denials that block submission.  An inactive mandate blocks
    everything; otherwise scope (side / order type / market) and the single-order
    amount cap are checked.  Asset-type and concentration limits require a
    portfolio snapshot and are enforced by the full pre-submit risk service, not
    here.
    """
    if not mandate.is_active(now):
        return (
            AuthorizationDenial(
                "mandate_inactive",
                f"投资授权当前为 {mandate.effective_status(now).value} 状态,无法提交新的下单意图",
            ),
        )
    denials: list[AuthorizationDenial] = []
    if side not in mandate.allowed_sides:
        denials.append(
            AuthorizationDenial(
                "side_not_authorized",
                f"当前授权未允许交易方向「{side}」",
            )
        )
    if order_type not in mandate.allowed_order_types:
        denials.append(
            AuthorizationDenial(
                "order_type_not_authorized",
                f"当前授权未允许订单类型「{order_type}」",
            )
        )
    market = market_of(instrument_id)
    if market not in mandate.allowed_markets:
        denials.append(
            AuthorizationDenial(
                "market_not_authorized",
                f"当前授权未允许交易市场「{market}」",
            )
        )
    if notional is not None and notional > mandate.limits.max_single_order_amount:
        denials.append(
            AuthorizationDenial(
                "single_order_limit_exceeded",
                (
                    f"单笔金额 {notional} 超过授权单笔上限 "
                    f"{mandate.limits.max_single_order_amount}"
                ),
            )
        )
    return tuple(denials)
