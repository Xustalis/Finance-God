from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Literal, Protocol, Self

from pydantic import AwareDatetime, Field, model_validator

from finance_god.domain.models import (
    AuditReference,
    OrderSide,
    OrderType,
    RiskCheckResult,
    RiskCheckStatus,
    RiskReason,
    RiskSeverity,
    TimeInForce,
    VersionReference,
    WorkflowRunStatus,
)

from .access import (
    AccessResolution,
    AccessResolver,
    AuthorizationSnapshot,
    AuthorizationStatus,
    AutonomyLevel,
    Clock,
    CooldownSnapshot,
    FrozenModel,
)
from .rules_v1 import (
    ACCESS_PROVIDER_MAX_AGE,
    BORROW_MAX_AGE,
    CALENDAR_SESSION_MAX_AGE,
    EXCHANGE_RISK_TTL,
    FUND_RISK_TTL,
    HARD_ALL_IN_COST_RATIO,
    HARD_BORROW_FEE_RATIO,
    HARD_BROAD_ETF_RATIO,
    HARD_DAILY_ADDED_TURNOVER_RATIO,
    HARD_INDUSTRY_RATIO,
    HARD_LONG_ONLY_GROSS_RATIO,
    HARD_OTC_FUND_RATIO,
    HARD_PRICE_DEVIATION_RATIO,
    HARD_RISK_INCREASING_ORDER_RATIO,
    HARD_SHORT_ENABLED_GROSS_RATIO,
    HARD_SHORT_GROSS_RATIO,
    HARD_SINGLE_ASSET_RATIO,
    HARD_SINGLE_SHORT_RATIO,
    HARD_SLIPPAGE_BPS,
    HK_INITIAL_MARGIN_RATIO,
    HK_MAINTENANCE_MARGIN_RATIO,
    MARKET_BUY_FREEZE_MULTIPLIER,
    RISK_RULE_REFERENCE,
    SOFT_ALL_IN_COST_RATIO,
    SOFT_BORROW_FEE_RATIO,
    SOFT_BROAD_ETF_RATIO,
    SOFT_DAILY_TURNOVER_RATIO,
    SOFT_INDUSTRY_RATIO,
    SOFT_ORDER_RATIO,
    SOFT_OTC_FUND_RATIO,
    SOFT_PRICE_DEVIATION_RATIO,
    SOFT_SHORT_GROSS_RATIO,
    SOFT_SINGLE_ASSET_RATIO,
    SOFT_SINGLE_SHORT_RATIO,
    SOFT_SLIPPAGE_BPS,
    SUPPORTED_MARKETS,
    TRUE_SNAPSHOT_MAX_AGE,
    US_INITIAL_MARGIN_RATIO,
    US_MAINTENANCE_MARGIN_RATIO,
)

ZERO = Decimal("0")


class RiskEvaluationError(RuntimeError):
    pass


class RiskEvaluationConflict(RiskEvaluationError):
    pass


class RiskStoreConflict(RiskEvaluationError):
    pass


class DraftOrigin(str, Enum):
    MANUAL = "manual"
    AGENT = "agent"


class AssetKind(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    LOF = "lof"
    OTC_FUND = "otc_fund"
    FUTURE = "future"
    OPTION = "option"


class DataFrequency(str, Enum):
    TRUE_SNAPSHOT = "true_snapshot"
    DAILY = "daily"
    FUND_NAV = "fund_nav"


class MarketSessionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    HALTED = "halted"
    AUCTION = "auction"
    NAV_PROCESSING = "nav_processing"


class EvidenceSnapshot(FrozenModel):
    reference: VersionReference
    revision: str = Field(min_length=1, max_length=80)
    captured_at: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        _require_utc(self.captured_at, "captured_at")
        _require_utc(self.valid_until, "valid_until")
        if self.valid_until <= self.captured_at:
            raise ValueError("evidence validity must end after capture")
        if self.reference.version != self.revision:
            raise ValueError("evidence revision must equal reference version")
        return self


class AgentControlSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    user_id: str = Field(min_length=1, max_length=160)
    new_workflows_paused: bool

    @model_validator(mode="after")
    def bind_identity(self) -> Self:
        _bind_evidence(self.evidence, "agent_control", self.user_id)
        return self


class HardHaltSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    active: bool

    @model_validator(mode="after")
    def bind_identity(self) -> Self:
        _bind_evidence(self.evidence, "hard_halt", "global")
        return self


class DraftRiskSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    draft_id: str = Field(min_length=1, max_length=160)
    draft_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    draft_revision: int = Field(ge=1)
    account_id: str = Field(min_length=1, max_length=160)
    owner_user_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    origin: DraftOrigin
    side: OrderSide
    order_type: OrderType
    quantity: Decimal | None = Field(gt=0)
    amount: Decimal | None = Field(gt=0)
    limit_price: Decimal | None = Field(gt=0)
    time_in_force: TimeInForce | None

    @model_validator(mode="after")
    def bind_identity(self) -> Self:
        _bind_evidence(
            self.evidence,
            "order_draft",
            self.draft_id,
            str(self.draft_revision),
        )
        return self


class IndustryExposure(FrozenModel):
    industry: str = Field(min_length=1, max_length=160)
    market_value: Decimal = Field(ge=0, max_digits=28, decimal_places=8)


class AccountRiskSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    account_id: str = Field(min_length=1, max_length=160)
    owner_user_id: str = Field(min_length=1, max_length=160)
    account_currency: Literal["CNY"]
    revision: int = Field(ge=1)
    available_cash: Decimal = Field(ge=0, max_digits=28, decimal_places=8)
    net_asset_value: Decimal = Field(gt=0, max_digits=28, decimal_places=8)
    daily_turnover: Decimal = Field(ge=0, max_digits=28, decimal_places=8)
    gross_long_value: Decimal = Field(ge=0, max_digits=28, decimal_places=8)
    gross_short_value: Decimal = Field(ge=0, max_digits=28, decimal_places=8)
    similar_open_order_count: int = Field(ge=0)
    industry_exposures: tuple[IndustryExposure, ...]

    @model_validator(mode="after")
    def unique_industries(self) -> Self:
        _bind_evidence(
            self.evidence,
            "account",
            self.account_id,
            str(self.revision),
        )
        industries = [item.industry for item in self.industry_exposures]
        if len(industries) != len(set(industries)):
            raise ValueError("industry exposure entries must be unique")
        return self


class PositionLine(FrozenModel):
    instrument_id: str = Field(min_length=1, max_length=160)
    asset_kind: AssetKind
    industry: str = Field(min_length=1, max_length=160)
    long_quantity: Decimal = Field(ge=0, max_digits=28, decimal_places=8)
    short_quantity: Decimal = Field(ge=0, max_digits=28, decimal_places=8)
    settled_quantity: Decimal = Field(ge=0, max_digits=28, decimal_places=8)
    sellable_quantity: Decimal = Field(ge=0, max_digits=28, decimal_places=8)
    fund_shares: Decimal = Field(ge=0, max_digits=28, decimal_places=8)
    long_market_value: Decimal = Field(ge=0, max_digits=28, decimal_places=8)
    short_market_value: Decimal = Field(ge=0, max_digits=28, decimal_places=8)

    @model_validator(mode="after")
    def validate_quantities(self) -> Self:
        reducible = (
            self.fund_shares
            if self.asset_kind is AssetKind.OTC_FUND
            else self.long_quantity
        )
        if self.settled_quantity > reducible:
            raise ValueError("settled quantity cannot exceed owned quantity")
        if self.sellable_quantity > self.settled_quantity:
            raise ValueError("sellable quantity cannot exceed settled quantity")
        return self


class PositionBookSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    account_id: str = Field(min_length=1, max_length=160)
    revision: int = Field(ge=1)
    positions: tuple[PositionLine, ...]

    @model_validator(mode="after")
    def unique_instruments(self) -> Self:
        _bind_evidence(
            self.evidence,
            "position_book",
            self.account_id,
            str(self.revision),
        )
        ids = [item.instrument_id for item in self.positions]
        if len(ids) != len(set(ids)):
            raise ValueError("position book cannot duplicate instruments")
        return self


class InstrumentSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    instrument_id: str = Field(min_length=1, max_length=160)
    market: str = Field(min_length=1, max_length=16)
    asset_kind: AssetKind
    industry: str = Field(min_length=1, max_length=160)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    supported: bool
    master_current: bool
    broad_master_confirmed: bool
    quantity_step: Decimal | None = Field(gt=0)
    minimum_quantity: Decimal | None = Field(gt=0)
    maximum_quantity: Decimal | None = Field(gt=0)
    price_tick: Decimal | None = Field(gt=0)
    allowed_time_in_force: tuple[TimeInForce, ...]

    @model_validator(mode="after")
    def bind_identity(self) -> Self:
        _bind_evidence(
            self.evidence,
            "instrument_master",
            self.instrument_id,
        )
        if self.broad_master_confirmed and self.asset_kind is not AssetKind.ETF:
            raise ValueError("broad qualification belongs only to an ETF")
        return self


class CalendarSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    market: str = Field(min_length=1, max_length=16)
    trading_date: date
    latest_completed_trading_date: date
    is_trading_day: bool
    session_start: AwareDatetime
    session_end: AwareDatetime

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        _bind_evidence(self.evidence, "trading_calendar", self.market)
        _require_utc(self.session_start, "session_start")
        _require_utc(self.session_end, "session_end")
        if self.session_end <= self.session_start:
            raise ValueError("market session must end after it starts")
        return self


class MarketSessionSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    market: str = Field(min_length=1, max_length=16)
    status: MarketSessionStatus

    @model_validator(mode="after")
    def bind_identity(self) -> Self:
        _bind_evidence(self.evidence, "market_session", self.market)
        return self


class MarketDataSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    instrument_id: str = Field(min_length=1, max_length=160)
    market: str = Field(min_length=1, max_length=16)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    available: bool
    reference_price: Decimal | None = Field(gt=0)
    frequency: DataFrequency
    data_date: date
    execution_mode: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def bind_identity(self) -> Self:
        _bind_evidence(self.evidence, "market_data", self.instrument_id)
        return self


class FxSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    available: bool
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    quote_currency: str = Field(pattern=r"^[A-Z]{3}$")
    rate: Decimal | None = Field(gt=0)

    @model_validator(mode="after")
    def bind_identity(self) -> Self:
        _bind_evidence(
            self.evidence,
            "fx_snapshot",
            f"{self.base_currency}/{self.quote_currency}",
        )
        if (
            self.base_currency == "CNY"
            and self.quote_currency == "CNY"
            and self.rate != Decimal("1")
        ):
            raise ValueError("CNY/CNY FX rate must equal one")
        return self


class FeeSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    draft_id: str = Field(min_length=1, max_length=160)
    available: bool
    currency: Literal["CNY"]
    estimated_fee: Decimal | None = Field(ge=0)
    maximum_fee: Decimal | None = Field(ge=0)

    @model_validator(mode="after")
    def validate_fee(self) -> Self:
        _bind_evidence(self.evidence, "fee_quote", self.draft_id)
        if (
            self.estimated_fee is not None
            and self.maximum_fee is not None
            and self.maximum_fee < self.estimated_fee
        ):
            raise ValueError("maximum fee cannot be below estimated fee")
        return self


class SlippageSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    draft_id: str = Field(min_length=1, max_length=160)
    available: bool
    currency: Literal["CNY"]
    estimated_amount: Decimal | None = Field(ge=0)
    bps: Decimal | None = Field(ge=0)

    @model_validator(mode="after")
    def bind_identity(self) -> Self:
        _bind_evidence(self.evidence, "slippage_quote", self.draft_id)
        return self


class BorrowSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    instrument_id: str = Field(min_length=1, max_length=160)
    market: str = Field(min_length=1, max_length=16)
    shortable: bool
    available_quantity: Decimal = Field(ge=0)
    annual_fee_ratio: Decimal = Field(ge=0)
    initial_margin_ratio: Decimal = Field(ge=0)
    maintenance_margin_ratio: Decimal = Field(ge=0)
    recall_active: bool
    short_sale_restricted: bool
    liquidation_margin_ratio: Decimal = Field(gt=0)
    margin_rule_reference: VersionReference

    @model_validator(mode="after")
    def validate_borrow_contract(self) -> Self:
        _bind_evidence(self.evidence, "borrow_snapshot", self.instrument_id)
        if (
            self.margin_rule_reference.object_type != "margin_rule"
            or self.margin_rule_reference.object_id != self.market
            or self.margin_rule_reference.version != RISK_RULE_REFERENCE.version
        ):
            raise ValueError("borrow margin rule is not bound to market/risk-rules-v1")
        if self.maintenance_margin_ratio > self.initial_margin_ratio:
            raise ValueError("maintenance margin cannot exceed initial margin")
        if self.liquidation_margin_ratio >= self.maintenance_margin_ratio:
            raise ValueError("liquidation margin must be below maintenance margin")
        return self


class FundRuleSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    instrument_id: str = Field(min_length=1, max_length=160)
    minimum_amount: Decimal = Field(gt=0)
    minimum_redeem_shares: Decimal = Field(gt=0)
    effective_cutoff_at: AwareDatetime
    application_date: date
    expected_application_date: date
    expected_confirmation_date: date
    latest_official_nav_date: date
    expected_nav_date: date
    expected_nav_publication_at: AwareDatetime
    final_nav: Decimal | None = Field(gt=0)
    final_nav_date: date | None

    @model_validator(mode="after")
    def validate_times(self) -> Self:
        _bind_evidence(self.evidence, "fund_rule", self.instrument_id)
        _require_utc(self.effective_cutoff_at, "effective_cutoff_at")
        _require_utc(
            self.expected_nav_publication_at,
            "expected_nav_publication_at",
        )
        if self.expected_confirmation_date < self.expected_application_date:
            raise ValueError("fund confirmation cannot precede application")
        if (self.final_nav is None) != (self.final_nav_date is None):
            raise ValueError("final NAV and final NAV date must appear together")
        if (
            self.final_nav_date is not None
            and self.final_nav_date != self.expected_nav_date
        ):
            raise ValueError("final NAV date must equal expected NAV date")
        if self.latest_official_nav_date > self.expected_nav_date:
            raise ValueError("latest official NAV cannot follow expected NAV date")
        return self


class FundConversionSnapshot(FrozenModel):
    evidence: EvidenceSnapshot
    source_instrument_id: str = Field(min_length=1, max_length=160)
    target_instrument_id: str = Field(min_length=1, max_length=160)
    target_market: str = Field(min_length=1, max_length=16)
    target_asset_kind: AssetKind
    target_industry: str = Field(min_length=1, max_length=160)
    target_currency: str = Field(pattern=r"^[A-Z]{3}$")
    target_supported: bool
    target_master_current: bool

    @model_validator(mode="after")
    def validate_distinct_instruments(self) -> Self:
        _bind_evidence(
            self.evidence,
            "fund_conversion_target",
            self.target_instrument_id,
        )
        if self.source_instrument_id == self.target_instrument_id:
            raise ValueError("fund conversion target must differ from source")
        return self


class RiskWorkflowDependency(FrozenModel):
    evidence: EvidenceSnapshot
    owner_user_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    run_reference: VersionReference
    workflow_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    status: WorkflowRunStatus
    trade_eligible: bool
    artifact_type: str = Field(min_length=1, max_length=80)
    artifact_reference: VersionReference

    @model_validator(mode="after")
    def validate_dependency(self) -> Self:
        _bind_evidence(self.evidence, "workflow_dependency", self.run_id)
        if (
            self.run_reference.object_type != "workflow_run"
            or self.run_reference.object_id != self.run_id
        ):
            raise ValueError("workflow run reference is not bound to run_id")
        if self.status is not WorkflowRunStatus.COMPLETED or not self.trade_eligible:
            raise ValueError(
                "risk workflow dependency must be completed/trade eligible"
            )
        if self.artifact_reference.object_type != "workflow_artifact":
            raise ValueError("workflow artifact reference has invalid object_type")
        return self


class RiskInputSnapshot(FrozenModel):
    agent_control: AgentControlSnapshot
    hard_halt: HardHaltSnapshot
    draft: DraftRiskSnapshot
    account: AccountRiskSnapshot
    positions: PositionBookSnapshot
    instrument: InstrumentSnapshot
    calendar: CalendarSnapshot
    session: MarketSessionSnapshot
    market_data: MarketDataSnapshot
    fx: FxSnapshot
    fee: FeeSnapshot
    slippage: SlippageSnapshot
    borrow: BorrowSnapshot | None
    fund_rule: FundRuleSnapshot | None
    fund_conversion: FundConversionSnapshot | None
    rule: EvidenceSnapshot
    plan_workflows: tuple[RiskWorkflowDependency, ...]

    def input_versions(
        self,
        access: AccessResolution,
    ) -> tuple[VersionReference, ...]:
        references = [
            access.resolution_reference,
            self.agent_control.evidence.reference,
            self.hard_halt.evidence.reference,
            self.draft.evidence.reference,
            self.account.evidence.reference,
            self.positions.evidence.reference,
            self.instrument.evidence.reference,
            self.calendar.evidence.reference,
            self.session.evidence.reference,
            self.market_data.evidence.reference,
            self.fx.evidence.reference,
            self.fee.evidence.reference,
            self.slippage.evidence.reference,
            self.rule.reference,
            *(item.evidence.reference for item in self.plan_workflows),
            *(item.run_reference for item in self.plan_workflows),
            *(item.artifact_reference for item in self.plan_workflows),
        ]
        if self.borrow is not None:
            references.append(self.borrow.evidence.reference)
            references.append(self.borrow.margin_rule_reference)
        if self.fund_rule is not None:
            references.append(self.fund_rule.evidence.reference)
        if self.fund_conversion is not None:
            references.append(self.fund_conversion.evidence.reference)
        if access.allowed:
            assert access.principal is not None
            assert access.authorization is not None
            assert access.cooldown is not None
            references.extend(
                (
                    access.principal.source_version,
                    access.authorization.source_version,
                    access.cooldown.source_version,
                )
            )
        return tuple(references)

    def valid_until_values(
        self,
        access: AccessResolution,
    ) -> tuple[datetime, ...]:
        values = [
            access.valid_until,
            self.agent_control.evidence.valid_until,
            self.hard_halt.evidence.valid_until,
            self.draft.evidence.valid_until,
            self.account.evidence.valid_until,
            self.positions.evidence.valid_until,
            self.instrument.evidence.valid_until,
            self.calendar.evidence.valid_until,
            self.session.evidence.valid_until,
            self.market_data.evidence.valid_until,
            self.fx.evidence.valid_until,
            self.fee.evidence.valid_until,
            self.slippage.evidence.valid_until,
            self.rule.valid_until,
            *(item.evidence.valid_until for item in self.plan_workflows),
        ]
        if self.borrow is not None:
            values.append(self.borrow.evidence.valid_until)
        if self.fund_rule is not None:
            values.append(self.fund_rule.evidence.valid_until)
        if self.fund_conversion is not None:
            values.append(self.fund_conversion.evidence.valid_until)
        if access.allowed:
            assert access.principal is not None
            assert access.authorization is not None
            assert access.cooldown is not None
            values.extend(
                (
                    access.principal.valid_until,
                    access.authorization.valid_until,
                    access.cooldown.valid_until,
                )
            )
        return tuple(values)


class RiskCheckStore(Protocol):
    def get(self, review_id: str) -> StoredRiskReview | None: ...

    def append(
        self,
        review_id: str,
        *,
        expected_revision: int,
        review: StoredRiskReview,
    ) -> StoredRiskReview: ...


class StoredRiskReview(FrozenModel):
    input_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner_user_id: str | None = Field(max_length=160)
    reason_summary_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    result: RiskCheckResult

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.reason_summary_hash != _reason_summary_hash(self.result):
            raise ValueError("reason summary hash does not match formal result")
        return self


def risk_reducing(
    *,
    side: OrderSide,
    quantity: Decimal,
    position: PositionLine | None,
) -> bool:
    if position is None or quantity <= ZERO:
        return False
    if side is OrderSide.SELL:
        owned = position.long_quantity
    elif side is OrderSide.REDEEM:
        owned = position.fund_shares
    else:
        return False
    if quantity > owned:
        return False
    if quantity > position.settled_quantity or quantity > position.sellable_quantity:
        return False
    before_gross = position.long_market_value + position.short_market_value
    if owned == ZERO:
        return False
    reduced_long_value = position.long_market_value * (quantity / owned)
    after_gross = before_gross - reduced_long_value
    return after_gross < before_gross and after_gross >= ZERO


class _Reasons:
    def __init__(self) -> None:
        self.hard_reasons: dict[str, RiskReason] = {}
        self.soft_reasons: dict[str, RiskReason] = {}

    def hard(self, code: str, message: str) -> None:
        self.hard_reasons.setdefault(
            code, RiskReason(code=code, severity=RiskSeverity.HARD, message=message)
        )

    def soft(self, code: str, message: str) -> None:
        self.soft_reasons.setdefault(
            code, RiskReason(code=code, severity=RiskSeverity.SOFT, message=message)
        )

    def final(self) -> tuple[RiskReason, ...]:
        reasons = self.hard_reasons if self.hard_reasons else self.soft_reasons
        return tuple(reasons[code] for code in sorted(reasons))


class PreSubmitRiskService:
    def __init__(
        self,
        *,
        access_resolver: AccessResolver,
        clock: Clock,
        store: RiskCheckStore,
    ) -> None:
        self._access_resolver = access_resolver
        self._clock = clock
        self._store = store

    def evaluate(
        self, *, review_id: str, snapshot: RiskInputSnapshot
    ) -> RiskCheckResult:
        review_id = review_id.strip()
        if not review_id or len(review_id) > 160:
            raise ValueError("review_id must be non-blank and at most 160 characters")
        now = self._clock.now()
        _require_utc(now, "clock")
        access = self._access_resolver.resolve()
        fingerprint = _input_fingerprint(snapshot, access)
        versions = _formal_input_versions(snapshot, access, fingerprint)
        existing = self._store.get(review_id)
        if existing is not None:
            self._require_same_review(
                existing,
                snapshot,
                versions,
                fingerprint,
            )
            return existing.result

        reasons = _Reasons()
        if not access.allowed:
            reasons.hard(
                f"access_{access.code.value}",
                "server access resolution denied formal risk evaluation",
            )
        else:
            assert access.principal is not None
            assert access.authorization is not None
            assert access.cooldown is not None
            self._evaluate_gates(snapshot, access, now, reasons)
            self._evaluate_order(snapshot, access, now, reasons)
        final_reasons = reasons.final()
        status = _status_for(final_reasons)
        expires_at = self._expiry(snapshot, access, now, reasons)
        final_reasons = reasons.final()
        status = _status_for(final_reasons)
        result = RiskCheckResult(
            risk_check_id=review_id,
            revision=1,
            status=status,
            audit_reference=AuditReference(
                audit_id=f"risk:{review_id}",
                actor_id="pre-submit-risk-service",
                recorded_at=now,
            ),
            input_versions=versions,
            invalidated_by_versions=(),
            order_version=snapshot.draft.evidence.reference,
            rule_version=RISK_RULE_REFERENCE,
            reasons=final_reasons,
            checked_at=now,
            expires_at=expires_at,
            soft_confirmation=None,
        )
        owner_user_id = (
            access.principal.user_id
            if access.allowed and access.principal is not None
            else None
        )
        proposed = StoredRiskReview(
            input_fingerprint=fingerprint,
            owner_user_id=owner_user_id,
            reason_summary_hash=_reason_summary_hash(result),
            result=result,
        )
        try:
            stored = self._store.append(
                review_id,
                expected_revision=0,
                review=proposed,
            )
        except RiskStoreConflict:
            winner = self._store.get(review_id)
            if winner is None:
                raise
            stored = winner
        self._require_same_review(stored, snapshot, versions, fingerprint)
        return stored.result

    def confirm_soft_risk(
        self,
        *,
        review_id: str,
        expected_revision: int,
        seen_rule_version: VersionReference,
        seen_reason_summary_hash: str,
    ) -> RiskCheckResult:
        access = self._access_resolver.resolve()
        if (
            not access.allowed
            or access.principal is None
            or access.authorization is None
        ):
            raise PermissionError("server access resolution denied confirmation")
        stored = self._require_stored(review_id)
        result = stored.result
        if stored.owner_user_id != access.principal.user_id:
            raise PermissionError("formal risk result belongs to another user")
        if result.revision != expected_revision:
            raise RiskStoreConflict("formal risk result revision changed")
        if result.rule_version != seen_rule_version:
            raise RiskEvaluationConflict("seen rule version differs from result")
        if stored.reason_summary_hash != seen_reason_summary_hash:
            raise RiskEvaluationConflict("seen reason summary differs from result")
        now = self._clock.now()
        _require_utc(now, "clock")
        if now >= result.expires_at:
            raise RiskEvaluationConflict("formal risk result has expired")
        confirmed = result.confirm_soft_risk(
            AuditReference(
                audit_id=f"risk:{review_id}:confirm:{expected_revision + 1}",
                actor_id=access.principal.user_id,
                recorded_at=now,
            )
        )
        appended = self._store.append(
            review_id,
            expected_revision=expected_revision,
            review=StoredRiskReview(
                input_fingerprint=stored.input_fingerprint,
                owner_user_id=stored.owner_user_id,
                reason_summary_hash=stored.reason_summary_hash,
                result=confirmed,
            ),
        )
        return appended.result

    def refresh_validity(
        self,
        *,
        review_id: str,
        expected_revision: int,
        snapshot: RiskInputSnapshot,
    ) -> RiskCheckResult:
        stored = self._require_stored(review_id)
        result = stored.result
        if result.revision != expected_revision:
            raise RiskStoreConflict("formal risk result revision changed")
        access = self._access_resolver.resolve()
        current_fingerprint = _input_fingerprint(snapshot, access)
        current_versions = _formal_input_versions(
            snapshot,
            access,
            current_fingerprint,
        )
        now = self._clock.now()
        _require_utc(now, "clock")
        audit = AuditReference(
            audit_id=f"risk:{review_id}:expire:{expected_revision + 1}",
            actor_id="pre-submit-risk-service",
            recorded_at=now,
        )
        if (
            tuple(
                sorted(
                    current_versions,
                    key=lambda item: (item.object_type, item.object_id, item.version),
                )
            )
            != result.input_versions
        ):
            refreshed = result.expire_if_inputs_changed(
                current_versions,
                audit_reference=audit,
            )
        elif now >= result.expires_at and result.status is not RiskCheckStatus.EXPIRED:
            refreshed = result.transition(
                RiskCheckStatus.EXPIRED,
                audit_reference=audit,
            )
        else:
            return result
        appended = self._store.append(
            review_id,
            expected_revision=expected_revision,
            review=StoredRiskReview(
                input_fingerprint=stored.input_fingerprint,
                owner_user_id=stored.owner_user_id,
                reason_summary_hash=_reason_summary_hash(refreshed),
                result=refreshed,
            ),
        )
        return appended.result

    def _require_stored(self, review_id: str) -> StoredRiskReview:
        review_id = review_id.strip()
        if not review_id or len(review_id) > 160:
            raise ValueError("review_id must be non-blank and at most 160 characters")
        stored = self._store.get(review_id)
        if stored is None:
            raise LookupError("formal risk result does not exist")
        return stored

    @staticmethod
    def _require_same_review(
        existing: StoredRiskReview,
        snapshot: RiskInputSnapshot,
        versions: tuple[VersionReference, ...],
        fingerprint: str,
    ) -> None:
        canonical_versions = tuple(
            sorted(
                versions,
                key=lambda item: (item.object_type, item.object_id, item.version),
            )
        )
        if (
            existing.input_fingerprint != fingerprint
            or existing.result.order_version != snapshot.draft.evidence.reference
            or existing.result.rule_version != snapshot.rule.reference
            or existing.result.input_versions != canonical_versions
        ):
            raise RiskEvaluationConflict(
                "review_id already owns a formal result for different inputs"
            )

    def _evaluate_gates(
        self,
        snapshot: RiskInputSnapshot,
        access: AccessResolution,
        now: datetime,
        reasons: _Reasons,
    ) -> None:
        assert access.principal is not None
        assert access.authorization is not None
        assert access.cooldown is not None
        principal = access.principal
        authorization = access.authorization
        cooldown = access.cooldown
        owner_ids = {
            principal.user_id,
            authorization.user_id,
            cooldown.user_id,
            snapshot.agent_control.user_id,
            snapshot.draft.owner_user_id,
            snapshot.account.owner_user_id,
        }
        if len(owner_ids) != 1:
            reasons.hard("owner_mismatch", "risk inputs do not belong to one user")
        if snapshot.draft.account_id != snapshot.account.account_id:
            reasons.hard("account_mismatch", "draft and account identifiers differ")
        if snapshot.positions.account_id != snapshot.account.account_id:
            reasons.hard(
                "position_account_mismatch",
                "position book and account identifiers differ",
            )
        if snapshot.draft.instrument_id != snapshot.instrument.instrument_id:
            reasons.hard(
                "instrument_mismatch",
                "draft and instrument master identifiers differ",
            )
        position = _find_position(snapshot)
        if (
            position is not None
            and position.asset_kind is not snapshot.instrument.asset_kind
        ):
            reasons.hard(
                "position_asset_mismatch",
                "position and instrument asset kinds differ",
            )
        self._validate_portfolio_consistency(snapshot, reasons)
        if authorization.status is not AuthorizationStatus.ACTIVE:
            reasons.hard(
                "authorization_inactive",
                f"authorization status is {authorization.status.value}",
            )
        if now < authorization.valid_from or now >= authorization.valid_until:
            reasons.hard("authorization_expired", "authorization is outside validity")
        if authorization.autonomy_level is not AutonomyLevel.L2:
            reasons.hard("l2_required", "simulation submission requires L2 authority")
        if snapshot.instrument.market not in SUPPORTED_MARKETS:
            reasons.hard("market_unsupported", "market is not enabled for trading")
        if snapshot.instrument.market not in authorization.allowed_markets:
            reasons.hard("market_not_authorized", "market is outside authorization")
        if snapshot.instrument.asset_kind.value not in authorization.allowed_assets:
            reasons.hard("asset_not_authorized", "asset is outside authorization")
        if snapshot.draft.side.value not in authorization.allowed_sides:
            reasons.hard("side_not_authorized", "side is outside authorization")
        if snapshot.draft.order_type.value not in authorization.allowed_order_types:
            reasons.hard(
                "order_type_not_authorized",
                "order type is outside authorization",
            )
        if snapshot.instrument.asset_kind in {AssetKind.FUTURE, AssetKind.OPTION}:
            reasons.hard(
                "asset_research_only",
                "futures and options are research-only in the MVP",
            )
        if not snapshot.instrument.supported:
            reasons.hard("instrument_unsupported", "instrument is not supported")
        if not snapshot.instrument.master_current:
            reasons.hard("instrument_master_stale", "instrument master is not current")
        if snapshot.rule.reference != RISK_RULE_REFERENCE:
            reasons.hard("risk_rule_not_current", "risk rule version is not current")
        if not snapshot.plan_workflows:
            reasons.hard(
                "workflow_dependency_missing",
                "formal review requires at least one workflow artifact version",
            )
        elif not any(
            item.workflow_key == "order_review"
            and item.artifact_type == "OrderReviewMemo"
            for item in snapshot.plan_workflows
        ):
            reasons.hard(
                "order_review_dependency_missing",
                "formal risk requires completed eligible OrderReviewMemo",
            )
        if any(
            item.owner_user_id != principal.user_id for item in snapshot.plan_workflows
        ):
            reasons.hard(
                "workflow_owner_mismatch",
                "workflow dependency belongs to another user",
            )
        if snapshot.hard_halt.active:
            reasons.hard("hard_halt_active", "hard trading halt is active")
        if (
            snapshot.agent_control.new_workflows_paused
            and snapshot.draft.origin is DraftOrigin.AGENT
        ):
            reasons.hard(
                "agent_control_paused",
                "agent-originated draft is paused by agent control",
            )
        if snapshot.account.similar_open_order_count:
            reasons.hard(
                "duplicate_open_order",
                "a similar open order already exists",
            )
        self._check_age(
            now,
            principal.captured_at,
            principal.valid_until,
            ACCESS_PROVIDER_MAX_AGE,
            "identity",
            reasons,
        )
        self._check_age(
            now,
            authorization.captured_at,
            authorization.valid_until,
            ACCESS_PROVIDER_MAX_AGE,
            "authorization",
            reasons,
        )
        self._check_age(
            now,
            cooldown.captured_at,
            cooldown.valid_until,
            ACCESS_PROVIDER_MAX_AGE,
            "cooldown",
            reasons,
        )
        for label, item in (
            ("calendar", snapshot.calendar.evidence),
            ("session", snapshot.session.evidence),
        ):
            self._check_age(
                now,
                item.captured_at,
                item.valid_until,
                CALENDAR_SESSION_MAX_AGE,
                label,
                reasons,
            )
        if snapshot.instrument.market != snapshot.calendar.market:
            reasons.hard("calendar_market_mismatch", "calendar market differs")
        if snapshot.instrument.market != snapshot.session.market:
            reasons.hard("session_market_mismatch", "session market differs")
        if (
            snapshot.market_data.instrument_id != snapshot.instrument.instrument_id
            or snapshot.market_data.market != snapshot.instrument.market
            or snapshot.market_data.currency != snapshot.instrument.currency
        ):
            reasons.hard(
                "market_data_identity_mismatch",
                "market data instrument, market, or currency differs",
            )
        if (
            snapshot.fx.base_currency != snapshot.instrument.currency
            or snapshot.fx.quote_currency != snapshot.account.account_currency
        ):
            reasons.hard(
                "fx_pair_mismatch",
                "FX evidence does not convert instrument currency to CNY",
            )
        if (
            snapshot.fee.evidence.reference.object_id
            != snapshot.draft.evidence.reference.object_id
        ):
            reasons.hard("fee_draft_mismatch", "fee quote belongs to another draft")
        if (
            snapshot.slippage.evidence.reference.object_id
            != snapshot.draft.evidence.reference.object_id
        ):
            reasons.hard(
                "slippage_draft_mismatch",
                "slippage quote belongs to another draft",
            )
        for item in _all_evidence(snapshot):
            if item.captured_at > now:
                reasons.hard(
                    "input_from_future",
                    f"{item.reference.object_type} capture is in the future",
                )
            if item.valid_until <= now:
                reasons.hard(
                    "input_expired",
                    f"{item.reference.object_type} input has expired",
                )

    def _evaluate_order(
        self,
        snapshot: RiskInputSnapshot,
        access: AccessResolution,
        now: datetime,
        reasons: _Reasons,
    ) -> None:
        assert access.authorization is not None
        assert access.cooldown is not None
        authorization = access.authorization
        cooldown = access.cooldown
        draft = snapshot.draft
        is_fund = snapshot.instrument.asset_kind is AssetKind.OTC_FUND
        if is_fund:
            self._validate_fund_shape(snapshot, authorization, now, reasons)
        else:
            self._validate_exchange_shape(snapshot, reasons)
        reference_price = self._validate_market_data(snapshot, now, reasons)
        self._validate_dependencies(snapshot, reasons)
        position = _find_position(snapshot)
        strictly_reducing = draft.quantity is not None and risk_reducing(
            side=draft.side,
            quantity=draft.quantity,
            position=position,
        )
        self._validate_cooldown(snapshot, cooldown, position, reasons)
        self._validate_position_availability(snapshot, position, reasons)
        if draft.side is OrderSide.SHORT:
            self._validate_short(snapshot, authorization, now, reasons)
        nominal = _nominal(draft, reference_price, snapshot.fx.rate)
        if nominal is None:
            return
        self._validate_slippage_consistency(snapshot, nominal, reasons)
        self._validate_cash(snapshot, nominal, reasons)
        self._validate_costs_and_price(
            snapshot,
            authorization,
            nominal,
            reference_price,
            reasons,
        )
        self._validate_exposure(
            snapshot,
            authorization,
            position,
            nominal,
            strictly_reducing,
            reasons,
        )

    @staticmethod
    def _validate_slippage_consistency(
        snapshot: RiskInputSnapshot,
        nominal: Decimal,
        reasons: _Reasons,
    ) -> None:
        amount = snapshot.slippage.estimated_amount
        bps = snapshot.slippage.bps
        if amount is None or bps is None:
            return
        if amount != nominal * bps / Decimal("10000"):
            reasons.hard(
                "slippage_quote_inconsistent",
                "slippage amount does not equal nominal multiplied by bps",
            )

    @staticmethod
    def _validate_portfolio_consistency(
        snapshot: RiskInputSnapshot,
        reasons: _Reasons,
    ) -> None:
        positions = snapshot.positions.positions
        if sum((item.long_market_value for item in positions), ZERO) != (
            snapshot.account.gross_long_value
        ):
            reasons.hard(
                "gross_long_mismatch",
                "account gross long does not match the position book",
            )
        if sum((item.short_market_value for item in positions), ZERO) != (
            snapshot.account.gross_short_value
        ):
            reasons.hard(
                "gross_short_mismatch",
                "account gross short does not match the position book",
            )
        position_industries: dict[str, Decimal] = {}
        for item in positions:
            position_industries[item.industry] = (
                position_industries.get(item.industry, ZERO)
                + item.long_market_value
                + item.short_market_value
            )
        account_industries = {
            item.industry: item.market_value
            for item in snapshot.account.industry_exposures
        }
        if position_industries != account_industries:
            reasons.hard(
                "industry_exposure_mismatch",
                "account industry exposure does not match the position book",
            )

    @staticmethod
    def _validate_exchange_shape(
        snapshot: RiskInputSnapshot, reasons: _Reasons
    ) -> None:
        draft = snapshot.draft
        if draft.order_type not in {OrderType.MARKET, OrderType.LIMIT}:
            reasons.hard(
                "exchange_order_type_invalid",
                "exchange asset requires market or limit order",
            )
        if draft.quantity is None or draft.amount is not None:
            reasons.hard(
                "exchange_quantity_invalid",
                "exchange order requires quantity only",
            )
        if draft.time_in_force is None:
            reasons.hard("time_in_force_missing", "exchange order requires TIF")
        elif draft.time_in_force not in snapshot.instrument.allowed_time_in_force:
            reasons.hard(
                "time_in_force_unsupported",
                "TIF is not supported by the instrument rules",
            )
        quantity_rules = (
            snapshot.instrument.quantity_step,
            snapshot.instrument.minimum_quantity,
            snapshot.instrument.maximum_quantity,
            snapshot.instrument.price_tick,
        )
        if any(value is None for value in quantity_rules):
            reasons.hard(
                "instrument_trade_rules_missing",
                "exchange quantity and price rules are incomplete",
            )
        elif draft.quantity is not None:
            step = snapshot.instrument.quantity_step
            minimum = snapshot.instrument.minimum_quantity
            maximum = snapshot.instrument.maximum_quantity
            assert step is not None and minimum is not None and maximum is not None
            if draft.quantity < minimum or draft.quantity > maximum:
                reasons.hard(
                    "quantity_out_of_range",
                    "quantity is outside instrument limits",
                )
            elif draft.quantity % step != ZERO:
                reasons.hard(
                    "quantity_step_invalid",
                    "quantity does not match the instrument step",
                )
        if draft.order_type is OrderType.LIMIT and draft.limit_price is None:
            reasons.hard("limit_price_missing", "limit order requires limit price")
        if draft.order_type is not OrderType.LIMIT and draft.limit_price is not None:
            reasons.hard(
                "market_limit_price_forbidden",
                "market order cannot carry limit price",
            )
        if draft.limit_price is not None and snapshot.instrument.price_tick is not None:
            if draft.limit_price % snapshot.instrument.price_tick != ZERO:
                reasons.hard(
                    "price_tick_invalid",
                    "limit price does not match the instrument tick",
                )

    @staticmethod
    def _validate_fund_shape(
        snapshot: RiskInputSnapshot,
        authorization: AuthorizationSnapshot,
        now: datetime,
        reasons: _Reasons,
    ) -> None:
        draft = snapshot.draft
        rule = snapshot.fund_rule
        if draft.order_type is not OrderType.FUND:
            reasons.hard("fund_order_type_invalid", "fund requires fund order type")
        if draft.time_in_force is not None or draft.limit_price is not None:
            reasons.hard(
                "fund_exchange_fields_forbidden",
                "fund order cannot carry exchange-only fields",
            )
        if (
            any(
                value is not None
                for value in (
                    snapshot.instrument.quantity_step,
                    snapshot.instrument.minimum_quantity,
                    snapshot.instrument.maximum_quantity,
                    snapshot.instrument.price_tick,
                )
            )
            or snapshot.instrument.allowed_time_in_force
        ):
            reasons.hard(
                "fund_exchange_rules_forbidden",
                "OTC fund cannot carry exchange quantity or TIF rules",
            )
        if rule is None:
            reasons.hard("fund_rule_missing", "fund rule evidence is required")
            return
        if rule.instrument_id != draft.instrument_id:
            reasons.hard("fund_rule_mismatch", "fund rule instrument differs")
        if rule.application_date != rule.expected_application_date:
            reasons.hard(
                "fund_application_date_invalid",
                "fund application date does not match cutoff calendar",
            )
        if now >= rule.expected_nav_publication_at and rule.final_nav is None:
            reasons.hard(
                "published_fund_nav_missing",
                "official NAV publication was expected but NAV is missing",
            )
        if rule.final_nav is None:
            if snapshot.market_data.data_date != rule.latest_official_nav_date:
                reasons.hard(
                    "fund_nav_date_conflict",
                    "fund reference NAV date differs from official calendar",
                )
        elif (
            snapshot.market_data.data_date != rule.final_nav_date
            or snapshot.market_data.reference_price != rule.final_nav
        ):
            reasons.hard(
                "fund_nav_value_conflict",
                "published NAV differs from market data snapshot",
            )
        if draft.side in {OrderSide.SUBSCRIBE, OrderSide.RECURRING_INVEST}:
            if draft.amount is None or draft.quantity is not None:
                reasons.hard(
                    "fund_amount_required",
                    "subscription and recurring investment require amount",
                )
            elif draft.amount < rule.minimum_amount:
                reasons.hard(
                    "fund_minimum_amount",
                    "fund amount is below versioned minimum",
                )
        elif draft.side in {OrderSide.REDEEM, OrderSide.CONVERT}:
            if draft.quantity is None or draft.amount is not None:
                reasons.hard(
                    "fund_shares_required",
                    "redemption and conversion require shares",
                )
            elif draft.quantity < rule.minimum_redeem_shares:
                reasons.hard(
                    "fund_minimum_shares",
                    "fund shares are below versioned minimum",
                )
            if draft.side is OrderSide.CONVERT:
                PreSubmitRiskService._validate_conversion(
                    snapshot,
                    authorization,
                    reasons,
                )
        else:
            reasons.hard("fund_side_invalid", "side is invalid for an OTC fund")

    @staticmethod
    def _validate_conversion(
        snapshot: RiskInputSnapshot,
        authorization: AuthorizationSnapshot,
        reasons: _Reasons,
    ) -> None:
        conversion = snapshot.fund_conversion
        if conversion is None:
            reasons.hard(
                "fund_conversion_evidence_missing",
                "fund conversion requires target master evidence",
            )
            return
        if conversion.source_instrument_id != snapshot.draft.instrument_id:
            reasons.hard(
                "fund_conversion_source_mismatch",
                "conversion source differs from the draft",
            )
        if conversion.target_market not in authorization.allowed_markets:
            reasons.hard(
                "fund_conversion_market_not_authorized",
                "conversion target market is outside authorization",
            )
        if conversion.target_asset_kind.value not in authorization.allowed_assets:
            reasons.hard(
                "fund_conversion_asset_not_authorized",
                "conversion target asset is outside authorization",
            )
        if conversion.target_asset_kind is not AssetKind.OTC_FUND:
            reasons.hard(
                "fund_conversion_target_invalid",
                "conversion target must be an OTC fund",
            )
        if not conversion.target_supported or not conversion.target_master_current:
            reasons.hard(
                "fund_conversion_target_unavailable",
                "conversion target master is unavailable or stale",
            )
        if conversion.target_currency != snapshot.account.account_currency:
            reasons.hard(
                "fund_conversion_currency_invalid",
                "conversion target currency differs from the account",
            )

    @staticmethod
    def _validate_dependencies(snapshot: RiskInputSnapshot, reasons: _Reasons) -> None:
        for label, item in (
            ("fx", snapshot.fx),
            ("fee", snapshot.fee),
            ("slippage", snapshot.slippage),
        ):
            if not item.available:
                reasons.hard(f"{label}_missing", f"{label} evidence is unavailable")
        if snapshot.fx.available and snapshot.fx.rate is None:
            reasons.hard("fx_rate_missing", "FX rate is missing")
        if snapshot.fee.available and (
            snapshot.fee.estimated_fee is None or snapshot.fee.maximum_fee is None
        ):
            reasons.hard("fee_value_missing", "fee values are missing")
        if snapshot.slippage.available and (
            snapshot.slippage.estimated_amount is None or snapshot.slippage.bps is None
        ):
            reasons.hard("slippage_value_missing", "slippage values are missing")

    def _validate_market_data(
        self,
        snapshot: RiskInputSnapshot,
        now: datetime,
        reasons: _Reasons,
    ) -> Decimal | None:
        data = snapshot.market_data
        is_fund = snapshot.instrument.asset_kind is AssetKind.OTC_FUND
        if snapshot.session.status is MarketSessionStatus.HALTED:
            reasons.hard("market_halted", "market is halted")
        if not data.available or data.reference_price is None:
            reasons.hard("market_data_missing", "reference market data is unavailable")
            return None
        if is_fund:
            if data.frequency is not DataFrequency.FUND_NAV:
                reasons.hard(
                    "fund_frequency_invalid",
                    "fund market data requires FUND_NAV frequency",
                )
            if data.execution_mode != "fund_nav":
                reasons.hard("fund_nav_mode_invalid", "fund requires fund_nav mode")
            return data.reference_price
        if data.frequency is DataFrequency.TRUE_SNAPSHOT:
            self._check_age(
                now,
                data.evidence.captured_at,
                data.evidence.valid_until,
                TRUE_SNAPSHOT_MAX_AGE,
                "market_data",
                reasons,
            )
            if data.execution_mode != "current_session":
                reasons.hard(
                    "snapshot_execution_mode_invalid",
                    "true snapshot requires current_session execution",
                )
            if data.data_date != snapshot.calendar.trading_date:
                reasons.hard(
                    "snapshot_trading_date_invalid",
                    "true snapshot must belong to current trading date",
                )
            if (
                not snapshot.calendar.is_trading_day
                or snapshot.session.status is not MarketSessionStatus.OPEN
            ):
                reasons.hard("market_closed", "market session is not open")
        elif data.frequency is DataFrequency.DAILY:
            if data.execution_mode != "next_daily_bar":
                reasons.hard(
                    "daily_execution_mode_invalid",
                    "daily data requires next_daily_bar execution",
                )
            if data.data_date != snapshot.calendar.latest_completed_trading_date:
                reasons.hard(
                    "daily_bar_not_latest",
                    "daily bar is not the latest completed trading day",
                )
        else:
            reasons.hard(
                "market_frequency_invalid",
                "exchange asset cannot use fund NAV frequency",
            )
        return data.reference_price

    @staticmethod
    def _validate_cooldown(
        snapshot: RiskInputSnapshot,
        cooldown: CooldownSnapshot,
        position: PositionLine | None,
        reasons: _Reasons,
    ) -> None:
        if not cooldown.active:
            return
        quantity = snapshot.draft.quantity
        if quantity is None or not risk_reducing(
            side=snapshot.draft.side,
            quantity=quantity,
            position=position,
        ):
            reasons.hard(
                "cooldown_new_risk_blocked",
                "cooldown permits only strictly risk-reducing sell or redeem",
            )

    @staticmethod
    def _validate_position_availability(
        snapshot: RiskInputSnapshot,
        position: PositionLine | None,
        reasons: _Reasons,
    ) -> None:
        side = snapshot.draft.side
        quantity = snapshot.draft.quantity
        if side not in {OrderSide.SELL, OrderSide.REDEEM, OrderSide.CONVERT}:
            return
        if quantity is None or position is None:
            reasons.hard(
                "position_missing",
                "position is required for sell, redeem, or convert",
            )
            return
        if side is OrderSide.SELL and (
            quantity > position.settled_quantity
            or quantity > position.sellable_quantity
            or quantity > position.long_quantity
        ):
            reasons.hard(
                "sellable_quantity_insufficient",
                "settled sellable quantity is insufficient",
            )
        if side in {OrderSide.REDEEM, OrderSide.CONVERT} and (
            quantity > position.fund_shares
            or quantity > position.settled_quantity
            or quantity > position.sellable_quantity
        ):
            reasons.hard(
                "fund_shares_insufficient",
                "settled sellable fund shares are insufficient",
            )

    def _validate_short(
        self,
        snapshot: RiskInputSnapshot,
        authorization: AuthorizationSnapshot,
        now: datetime,
        reasons: _Reasons,
    ) -> None:
        market = snapshot.instrument.market
        quantity = snapshot.draft.quantity
        if market == "CN":
            reasons.hard("a_share_short_forbidden", "A-share shorting is forbidden")
            return
        if market not in {"HK", "US"}:
            reasons.hard("short_market_unsupported", "market does not support shorting")
            return
        if market not in authorization.short_markets:
            reasons.hard("short_not_authorized", "short market is not authorized")
        borrow = snapshot.borrow
        if borrow is None:
            reasons.hard(
                "borrow_evidence_missing",
                "short order requires versioned borrow evidence",
            )
            return
        if borrow.instrument_id != snapshot.draft.instrument_id:
            reasons.hard("borrow_instrument_mismatch", "borrow instrument differs")
        if borrow.market != market:
            reasons.hard("borrow_market_mismatch", "borrow market differs")
        self._check_age(
            now,
            borrow.evidence.captured_at,
            borrow.evidence.valid_until,
            BORROW_MAX_AGE,
            "borrow",
            reasons,
        )
        if not borrow.shortable or borrow.recall_active or borrow.short_sale_restricted:
            reasons.hard("borrow_not_shortable", "borrow is not currently shortable")
        if quantity is None or borrow.available_quantity < quantity:
            reasons.hard(
                "borrow_quantity_insufficient", "borrow quantity is insufficient"
            )
        initial_required = (
            HK_INITIAL_MARGIN_RATIO if market == "HK" else US_INITIAL_MARGIN_RATIO
        )
        maintenance_required = (
            HK_MAINTENANCE_MARGIN_RATIO
            if market == "HK"
            else US_MAINTENANCE_MARGIN_RATIO
        )
        if borrow.initial_margin_ratio < initial_required:
            reasons.hard(
                "initial_margin_insufficient",
                "initial margin is below market minimum",
            )
        if borrow.maintenance_margin_ratio < maintenance_required:
            reasons.hard(
                "maintenance_margin_insufficient",
                "maintenance margin is below market minimum",
            )
        if borrow.annual_fee_ratio > HARD_BORROW_FEE_RATIO:
            reasons.hard("borrow_fee_hard_limit", "borrow annual fee exceeds 25%")
        elif borrow.annual_fee_ratio > SOFT_BORROW_FEE_RATIO:
            reasons.soft("borrow_fee_soft_limit", "borrow annual fee exceeds 10%")

    @staticmethod
    def _validate_cash(
        snapshot: RiskInputSnapshot,
        nominal: Decimal,
        reasons: _Reasons,
    ) -> None:
        side = snapshot.draft.side
        if side not in {
            OrderSide.BUY,
            OrderSide.SUBSCRIBE,
            OrderSide.RECURRING_INVEST,
            OrderSide.SHORT,
        }:
            return
        fee = snapshot.fee.maximum_fee
        if fee is None:
            return
        required = nominal + fee
        if side is OrderSide.BUY and snapshot.draft.order_type is OrderType.MARKET:
            required = nominal * MARKET_BUY_FREEZE_MULTIPLIER + fee
        if side is OrderSide.SHORT and snapshot.borrow is not None:
            required = nominal * snapshot.borrow.initial_margin_ratio + fee
        if snapshot.account.available_cash < required:
            reasons.hard("cash_insufficient", "available cash is below required freeze")

    @staticmethod
    def _validate_costs_and_price(
        snapshot: RiskInputSnapshot,
        authorization: AuthorizationSnapshot,
        nominal: Decimal,
        reference_price: Decimal | None,
        reasons: _Reasons,
    ) -> None:
        fee = snapshot.fee.estimated_fee
        slippage_amount = snapshot.slippage.estimated_amount
        slippage_bps = snapshot.slippage.bps
        if fee is not None and slippage_amount is not None:
            all_in_ratio = (fee + slippage_amount) / nominal
            auth_limit = authorization.limits.max_all_in_cost_ratio
            if all_in_ratio > HARD_ALL_IN_COST_RATIO:
                reasons.hard(
                    "all_in_cost_hard_limit",
                    "all-in cost exceeds 2%",
                )
            elif all_in_ratio > auth_limit:
                reasons.hard(
                    "authorization_all_in_cost_limit",
                    "all-in cost exceeds authorization",
                )
            elif all_in_ratio > SOFT_ALL_IN_COST_RATIO:
                reasons.soft(
                    "all_in_cost_soft_limit",
                    "all-in cost exceeds 1%",
                )
        if slippage_bps is not None:
            auth_limit = authorization.limits.max_slippage_bps
            if slippage_bps > HARD_SLIPPAGE_BPS:
                reasons.hard("slippage_hard_limit", "slippage exceeds 100 bps")
            elif slippage_bps > auth_limit:
                reasons.hard(
                    "authorization_slippage_limit",
                    "slippage exceeds authorization",
                )
            elif slippage_bps > SOFT_SLIPPAGE_BPS:
                reasons.soft("slippage_soft_limit", "slippage exceeds 50 bps")
        if snapshot.draft.limit_price is None or reference_price is None:
            return
        deviation = abs(snapshot.draft.limit_price - reference_price) / reference_price
        auth_limit = authorization.limits.max_price_deviation_ratio
        if deviation > HARD_PRICE_DEVIATION_RATIO:
            reasons.hard("price_deviation_hard_limit", "price deviation exceeds 10%")
        elif deviation > auth_limit:
            reasons.hard(
                "authorization_price_deviation_limit",
                "price deviation exceeds authorization",
            )
        elif deviation > SOFT_PRICE_DEVIATION_RATIO:
            reasons.soft("price_deviation_soft_limit", "price deviation exceeds 5%")

    @staticmethod
    def _validate_exposure(
        snapshot: RiskInputSnapshot,
        authorization: AuthorizationSnapshot,
        position: PositionLine | None,
        nominal: Decimal,
        strictly_reducing: bool,
        reasons: _Reasons,
    ) -> None:
        nav = snapshot.account.net_asset_value
        side = snapshot.draft.side
        risk_increasing = side in {
            OrderSide.BUY,
            OrderSide.SHORT,
            OrderSide.SUBSCRIBE,
            OrderSide.RECURRING_INVEST,
            OrderSide.CONVERT,
        }
        order_ratio = nominal / nav
        auth = authorization.limits
        if nominal > auth.max_single_order_amount:
            reasons.hard(
                "authorization_single_order_limit",
                "order amount exceeds authorization",
            )
        if risk_increasing and order_ratio > HARD_RISK_INCREASING_ORDER_RATIO:
            reasons.hard(
                "single_order_hard_limit",
                "risk-increasing order exceeds 10% of NAV",
            )
        elif order_ratio > SOFT_ORDER_RATIO:
            reasons.soft(
                "single_order_soft_limit",
                "order exceeds 5% of NAV",
            )
        projected_turnover = snapshot.account.daily_turnover + nominal
        if projected_turnover > auth.max_daily_turnover_amount:
            reasons.hard(
                "authorization_daily_turnover_limit",
                "daily turnover exceeds authorization",
            )
        projected_turnover_ratio = projected_turnover / nav
        if (
            risk_increasing
            and projected_turnover_ratio > HARD_DAILY_ADDED_TURNOVER_RATIO
        ):
            reasons.hard(
                "daily_turnover_hard_limit",
                "risk-increasing daily turnover exceeds 25% of NAV",
            )
        elif projected_turnover_ratio > SOFT_DAILY_TURNOVER_RATIO:
            reasons.soft(
                "daily_turnover_soft_limit",
                "daily turnover exceeds 15% of NAV",
            )

        current_long = position.long_market_value if position is not None else ZERO
        current_short = position.short_market_value if position is not None else ZERO
        long_delta = ZERO
        short_delta = ZERO
        conversion_target_delta = ZERO
        if side in {OrderSide.BUY, OrderSide.SUBSCRIBE, OrderSide.RECURRING_INVEST}:
            long_delta = nominal
        elif side in {OrderSide.SELL, OrderSide.REDEEM}:
            long_delta = -min(nominal, current_long)
        elif side is OrderSide.CONVERT:
            long_delta = -min(nominal, current_long)
            conversion_target_delta = nominal
        elif side is OrderSide.SHORT:
            short_delta = nominal
        post_long = (
            snapshot.account.gross_long_value + long_delta + conversion_target_delta
        )
        post_short = snapshot.account.gross_short_value + short_delta
        post_instrument = current_long + long_delta + current_short + short_delta
        conversion = snapshot.fund_conversion
        source_industry_delta = long_delta + short_delta
        if (
            conversion_target_delta
            and conversion is not None
            and conversion.target_industry == snapshot.instrument.industry
        ):
            source_industry_delta += conversion_target_delta
        post_industry = _industry_value(snapshot) + source_industry_delta
        post_instrument_ratio = max(ZERO, post_instrument) / nav
        post_industry_ratio = max(ZERO, post_industry) / nav
        post_short_ratio = post_short / nav
        post_gross_ratio = (post_long + post_short) / nav
        current_instrument_ratio = (current_long + current_short) / nav
        current_industry_ratio = _industry_value(snapshot) / nav
        current_short_ratio = snapshot.account.gross_short_value / nav
        current_gross_ratio = (
            snapshot.account.gross_long_value + snapshot.account.gross_short_value
        ) / nav

        platform_hard, platform_soft, auth_concentration = _concentration_limits(
            snapshot,
            authorization,
        )
        instrument_worsened = (
            not strictly_reducing or post_instrument_ratio > current_instrument_ratio
        )
        if instrument_worsened and post_instrument_ratio > platform_hard:
            reasons.hard(
                "concentration_hard_limit",
                "single asset concentration exceeds platform hard limit",
            )
        elif instrument_worsened and post_instrument_ratio > auth_concentration:
            reasons.hard(
                "authorization_concentration_limit",
                "single asset concentration exceeds authorization",
            )
        elif instrument_worsened and post_instrument_ratio > platform_soft:
            reasons.soft(
                "concentration_soft_limit",
                "single asset concentration exceeds platform soft limit",
            )
        if conversion_target_delta and conversion is not None:
            target_position = next(
                (
                    item
                    for item in snapshot.positions.positions
                    if item.instrument_id == conversion.target_instrument_id
                ),
                None,
            )
            target_current = (
                target_position.long_market_value
                if target_position is not None
                else ZERO
            )
            target_ratio = (target_current + conversion_target_delta) / nav
            if target_ratio > HARD_OTC_FUND_RATIO:
                reasons.hard(
                    "concentration_hard_limit",
                    "conversion target concentration exceeds 30%",
                )
            elif target_ratio > auth.max_otc_fund_ratio:
                reasons.hard(
                    "authorization_concentration_limit",
                    "conversion target concentration exceeds authorization",
                )
            elif target_ratio > SOFT_OTC_FUND_RATIO:
                reasons.soft(
                    "concentration_soft_limit",
                    "conversion target concentration exceeds 15%",
                )
        industry_worsened = (
            not strictly_reducing or post_industry_ratio > current_industry_ratio
        )
        if industry_worsened and post_industry_ratio > HARD_INDUSTRY_RATIO:
            reasons.hard(
                "industry_hard_limit",
                "industry concentration exceeds 35%",
            )
        elif industry_worsened and post_industry_ratio > auth.max_industry_ratio:
            reasons.hard(
                "authorization_industry_limit",
                "industry concentration exceeds authorization",
            )
        elif industry_worsened and post_industry_ratio > SOFT_INDUSTRY_RATIO:
            reasons.soft(
                "industry_soft_limit",
                "industry concentration exceeds 25%",
            )
        if (
            conversion_target_delta
            and conversion is not None
            and conversion.target_industry != snapshot.instrument.industry
        ):
            target_industry_ratio = (
                _industry_value_by_name(snapshot, conversion.target_industry)
                + conversion_target_delta
            ) / nav
            if target_industry_ratio > HARD_INDUSTRY_RATIO:
                reasons.hard(
                    "industry_hard_limit",
                    "conversion target industry concentration exceeds 35%",
                )
            elif target_industry_ratio > auth.max_industry_ratio:
                reasons.hard(
                    "authorization_industry_limit",
                    "conversion target industry exceeds authorization",
                )
            elif target_industry_ratio > SOFT_INDUSTRY_RATIO:
                reasons.soft(
                    "industry_soft_limit",
                    "conversion target industry concentration exceeds 25%",
                )
        gross_worsened = not strictly_reducing or post_gross_ratio > current_gross_ratio
        if gross_worsened and post_gross_ratio > auth.max_gross_ratio:
            reasons.hard(
                "authorization_gross_limit",
                "gross exposure exceeds authorization",
            )
        platform_gross = (
            HARD_LONG_ONLY_GROSS_RATIO
            if post_short == ZERO
            else HARD_SHORT_ENABLED_GROSS_RATIO
        )
        if gross_worsened and post_gross_ratio > platform_gross:
            reasons.hard(
                "gross_hard_limit",
                "gross exposure exceeds platform hard limit",
            )
        short_worsened = not strictly_reducing or post_short_ratio > current_short_ratio
        if short_worsened and post_short_ratio > HARD_SHORT_GROSS_RATIO:
            reasons.hard("short_gross_hard_limit", "short gross exceeds 30%")
        elif short_worsened and post_short_ratio > auth.max_short_gross_ratio:
            reasons.hard(
                "authorization_short_gross_limit",
                "short gross exceeds authorization",
            )
        elif short_worsened and post_short_ratio > SOFT_SHORT_GROSS_RATIO:
            reasons.soft("short_gross_soft_limit", "short gross exceeds 15%")
        if side is OrderSide.SHORT:
            single_short_ratio = (current_short + nominal) / nav
            if single_short_ratio > HARD_SINGLE_SHORT_RATIO:
                reasons.hard("single_short_hard_limit", "single short exceeds 10%")
            elif single_short_ratio > auth.max_single_short_ratio:
                reasons.hard(
                    "authorization_single_short_limit",
                    "single short exceeds authorization",
                )
            elif single_short_ratio > SOFT_SINGLE_SHORT_RATIO:
                reasons.soft("single_short_soft_limit", "single short exceeds 5%")

    @staticmethod
    def _check_age(
        now: datetime,
        captured_at: datetime,
        valid_until: datetime,
        maximum_age: timedelta,
        label: str,
        reasons: _Reasons,
    ) -> None:
        if now < captured_at:
            reasons.hard(f"{label}_from_future", f"{label} capture is in the future")
        elif now - captured_at > maximum_age:
            reasons.hard(f"{label}_stale", f"{label} snapshot is stale")
        if now >= valid_until:
            reasons.hard(f"{label}_expired", f"{label} snapshot has expired")

    @staticmethod
    def _expiry(
        snapshot: RiskInputSnapshot,
        access: AccessResolution,
        now: datetime,
        reasons: _Reasons,
    ) -> datetime:
        is_fund = snapshot.instrument.asset_kind is AssetKind.OTC_FUND
        candidates = [
            now + (FUND_RISK_TTL if is_fund else EXCHANGE_RISK_TTL),
            *snapshot.valid_until_values(access),
        ]
        if is_fund and snapshot.fund_rule is not None:
            candidates.append(snapshot.fund_rule.effective_cutoff_at)
        if not is_fund:
            candidates.append(snapshot.calendar.session_end)
        expiry = min(candidates)
        if expiry <= now:
            reasons.hard(
                "input_validity_exhausted",
                "one or more risk inputs have no remaining validity",
            )
            return now + timedelta(microseconds=1)
        return expiry


def _find_position(snapshot: RiskInputSnapshot) -> PositionLine | None:
    return next(
        (
            item
            for item in snapshot.positions.positions
            if item.instrument_id == snapshot.draft.instrument_id
        ),
        None,
    )


def _all_evidence(snapshot: RiskInputSnapshot) -> tuple[EvidenceSnapshot, ...]:
    items = [
        snapshot.agent_control.evidence,
        snapshot.hard_halt.evidence,
        snapshot.draft.evidence,
        snapshot.account.evidence,
        snapshot.positions.evidence,
        snapshot.instrument.evidence,
        snapshot.calendar.evidence,
        snapshot.session.evidence,
        snapshot.market_data.evidence,
        snapshot.fx.evidence,
        snapshot.fee.evidence,
        snapshot.slippage.evidence,
        snapshot.rule,
        *(item.evidence for item in snapshot.plan_workflows),
    ]
    if snapshot.borrow is not None:
        items.append(snapshot.borrow.evidence)
    if snapshot.fund_rule is not None:
        items.append(snapshot.fund_rule.evidence)
    if snapshot.fund_conversion is not None:
        items.append(snapshot.fund_conversion.evidence)
    return tuple(items)


def _input_fingerprint(
    snapshot: RiskInputSnapshot,
    access: AccessResolution,
) -> str:
    payload = (
        snapshot.model_dump_json()
        + "|"
        + access.model_dump_json(
            exclude={"checked_at", "message", "valid_until"},
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _formal_input_versions(
    snapshot: RiskInputSnapshot,
    access: AccessResolution,
    fingerprint: str,
) -> tuple[VersionReference, ...]:
    return (
        *snapshot.input_versions(access),
        VersionReference(
            object_type="risk_input_fingerprint",
            object_id=snapshot.draft.draft_id,
            version=fingerprint,
        ),
    )


def _reason_summary_hash(result: RiskCheckResult) -> str:
    return result.reason_hash


def _nominal(
    draft: DraftRiskSnapshot,
    reference_price: Decimal | None,
    fx_rate: Decimal | None,
) -> Decimal | None:
    if fx_rate is None:
        return None
    if draft.amount is not None:
        return draft.amount * fx_rate
    if draft.quantity is None or reference_price is None:
        return None
    price = draft.limit_price if draft.limit_price is not None else reference_price
    return draft.quantity * price * fx_rate


def _industry_value(snapshot: RiskInputSnapshot) -> Decimal:
    return _industry_value_by_name(snapshot, snapshot.instrument.industry)


def _industry_value_by_name(
    snapshot: RiskInputSnapshot,
    industry: str,
) -> Decimal:
    return next(
        (
            item.market_value
            for item in snapshot.account.industry_exposures
            if item.industry == industry
        ),
        ZERO,
    )


def _concentration_limits(
    snapshot: RiskInputSnapshot,
    authorization: AuthorizationSnapshot,
) -> tuple[Decimal, Decimal, Decimal]:
    kind = snapshot.instrument.asset_kind
    limits = authorization.limits
    if kind is AssetKind.ETF and snapshot.instrument.broad_master_confirmed:
        return HARD_BROAD_ETF_RATIO, SOFT_BROAD_ETF_RATIO, limits.max_broad_etf_ratio
    if kind is AssetKind.OTC_FUND:
        return HARD_OTC_FUND_RATIO, SOFT_OTC_FUND_RATIO, limits.max_otc_fund_ratio
    return (
        HARD_SINGLE_ASSET_RATIO,
        SOFT_SINGLE_ASSET_RATIO,
        limits.max_single_asset_ratio,
    )


def _status_for(reasons: tuple[RiskReason, ...]) -> RiskCheckStatus:
    if not reasons:
        return RiskCheckStatus.PASSED
    if any(reason.severity is RiskSeverity.HARD for reason in reasons):
        return RiskCheckStatus.BLOCKED
    return RiskCheckStatus.CONFIRMATION_REQUIRED


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")


def _bind_evidence(
    evidence: EvidenceSnapshot,
    object_type: str,
    object_id: str,
    revision: str | None = None,
) -> None:
    if evidence.reference.object_type != object_type:
        raise ValueError(f"evidence object_type must be {object_type}")
    if evidence.reference.object_id != object_id:
        raise ValueError("evidence object_id does not match snapshot identity")
    if revision is not None and evidence.revision != revision:
        raise ValueError("evidence revision does not match snapshot revision")
