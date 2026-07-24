from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from finance_god.domain.models import VersionReference

RISK_RULE_REFERENCE = VersionReference(
    object_type="risk_rule_set",
    object_id="pre_submit",
    version="risk-rules-v1",
)

ACCESS_PROVIDER_MAX_AGE = timedelta(seconds=30)
CALENDAR_SESSION_MAX_AGE = timedelta(seconds=60)
TRUE_SNAPSHOT_MAX_AGE = timedelta(seconds=15)
BORROW_MAX_AGE = timedelta(minutes=60)
EXCHANGE_RISK_TTL = timedelta(seconds=120)
FUND_RISK_TTL = timedelta(minutes=15)

MARKET_BUY_FREEZE_MULTIPLIER = Decimal("1.10")

HARD_ALL_IN_COST_RATIO = Decimal("0.02")
SOFT_ALL_IN_COST_RATIO = Decimal("0.01")
HARD_SLIPPAGE_BPS = Decimal("100")
SOFT_SLIPPAGE_BPS = Decimal("50")
HARD_PRICE_DEVIATION_RATIO = Decimal("0.10")
SOFT_PRICE_DEVIATION_RATIO = Decimal("0.05")
HARD_RISK_INCREASING_ORDER_RATIO = Decimal("0.10")
SOFT_ORDER_RATIO = Decimal("0.05")
HARD_DAILY_ADDED_TURNOVER_RATIO = Decimal("0.25")
SOFT_DAILY_TURNOVER_RATIO = Decimal("0.15")

HARD_SINGLE_ASSET_RATIO = Decimal("0.20")
SOFT_SINGLE_ASSET_RATIO = Decimal("0.10")
HARD_BROAD_ETF_RATIO = Decimal("0.35")
SOFT_BROAD_ETF_RATIO = Decimal("0.20")
HARD_OTC_FUND_RATIO = Decimal("0.30")
SOFT_OTC_FUND_RATIO = Decimal("0.15")
HARD_INDUSTRY_RATIO = Decimal("0.35")
SOFT_INDUSTRY_RATIO = Decimal("0.25")
HARD_LONG_ONLY_GROSS_RATIO = Decimal("1.00")
HARD_SHORT_ENABLED_GROSS_RATIO = Decimal("1.30")
HARD_SHORT_GROSS_RATIO = Decimal("0.30")
SOFT_SHORT_GROSS_RATIO = Decimal("0.15")
HARD_SINGLE_SHORT_RATIO = Decimal("0.10")
SOFT_SINGLE_SHORT_RATIO = Decimal("0.05")
HARD_BORROW_FEE_RATIO = Decimal("0.25")
SOFT_BORROW_FEE_RATIO = Decimal("0.10")

HK_INITIAL_MARGIN_RATIO = Decimal("1.50")
HK_MAINTENANCE_MARGIN_RATIO = Decimal("1.30")
US_INITIAL_MARGIN_RATIO = Decimal("1.50")
US_MAINTENANCE_MARGIN_RATIO = Decimal("1.35")

SUPPORTED_MARKETS = frozenset({"CN", "HK", "US"})
