from __future__ import annotations

import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier, Lock

from pydantic import ValidationError

from finance_god.domain.models import (
    AuditReference,
    OrderSide,
    OrderType,
    RiskCheckResult,
    RiskCheckStatus,
    RiskSeverity,
    TimeInForce,
    VersionReference,
    WorkflowRunStatus,
)
from finance_god.trading.access import (
    AccessResolver,
    AuthenticatedPrincipal,
    AuthorizationLimits,
    AuthorizationSnapshot,
    AuthorizationStatus,
    AutonomyLevel,
    Clock,
    CooldownSnapshot,
    RuntimeEnvironment,
)
from finance_god.trading.risk import (
    AccountRiskSnapshot,
    AgentControlSnapshot,
    AssetKind,
    BorrowSnapshot,
    CalendarSnapshot,
    DataFrequency,
    DraftOrigin,
    DraftRiskSnapshot,
    EvidenceSnapshot,
    FeeSnapshot,
    FundConversionSnapshot,
    FundRuleSnapshot,
    FxSnapshot,
    HardHaltSnapshot,
    IndustryExposure,
    InstrumentSnapshot,
    MarketDataSnapshot,
    MarketSessionSnapshot,
    MarketSessionStatus,
    PositionBookSnapshot,
    PositionLine,
    PreSubmitRiskService,
    RiskEvaluationConflict,
    RiskInputSnapshot,
    RiskStoreConflict,
    RiskWorkflowDependency,
    SlippageSnapshot,
    StoredRiskReview,
    risk_reducing,
)
from finance_god.trading.rules_v1 import RISK_RULE_REFERENCE

NOW = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class MutableClock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class MemoryStore:
    def __init__(self) -> None:
        self.histories: dict[str, list[StoredRiskReview]] = {}
        self.saves = 0
        self._lock = Lock()

    def get(self, review_id: str) -> StoredRiskReview | None:
        history = self.histories.get(review_id, [])
        return history[-1] if history else None

    def append(
        self,
        review_id: str,
        *,
        expected_revision: int,
        review: StoredRiskReview,
    ) -> StoredRiskReview:
        with self._lock:
            history = self.histories.setdefault(review_id, [])
            current_revision = history[-1].result.revision if history else 0
            if current_revision != expected_revision:
                raise RiskStoreConflict("compare-and-append revision mismatch")
            if review.result.revision != expected_revision + 1:
                raise RiskStoreConflict("appended revision is not consecutive")
            history.append(review)
            self.saves += 1
            return review


def ref(kind: str, object_id: str, version: str = "1") -> VersionReference:
    return VersionReference(object_type=kind, object_id=object_id, version=version)


def evidence(
    kind: str,
    object_id: str,
    *,
    captured_at: datetime = NOW - timedelta(seconds=1),
    valid_until: datetime = NOW + timedelta(minutes=30),
    version: str = "1",
) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        reference=ref(kind, object_id, version),
        revision=version,
        captured_at=captured_at,
        valid_until=valid_until,
    )


def workflow_dependency() -> RiskWorkflowDependency:
    return RiskWorkflowDependency(
        evidence=evidence("workflow_dependency", "order-review-1"),
        owner_user_id="user-1",
        run_id="order-review-1",
        run_reference=ref("workflow_run", "order-review-1", "3"),
        workflow_key="order_review",
        status=WorkflowRunStatus.COMPLETED,
        trade_eligible=True,
        artifact_type="OrderReviewMemo",
        artifact_reference=ref("workflow_artifact", "order-review-memo-1", "2"),
    )


def authorization_limits(**changes: Decimal) -> AuthorizationLimits:
    values: dict[str, Decimal] = {
        "max_single_order_amount": Decimal("50000"),
        "max_daily_turnover_amount": Decimal("250000"),
        "max_single_asset_ratio": Decimal("0.20"),
        "max_broad_etf_ratio": Decimal("0.35"),
        "max_otc_fund_ratio": Decimal("0.30"),
        "max_industry_ratio": Decimal("0.35"),
        "max_gross_ratio": Decimal("1.00"),
        "max_short_gross_ratio": Decimal("0.30"),
        "max_single_short_ratio": Decimal("0.10"),
        "max_price_deviation_ratio": Decimal("0.10"),
        "max_slippage_bps": Decimal("100"),
        "max_all_in_cost_ratio": Decimal("0.02"),
    }
    values.update(changes)
    return AuthorizationLimits(**values)


def principal(**changes: object) -> AuthenticatedPrincipal:
    base = AuthenticatedPrincipal(
        principal_id="principal-1",
        user_id="user-1",
        session_id="session-1",
        authenticated_at=NOW - timedelta(seconds=2),
        captured_at=NOW - timedelta(seconds=1),
        valid_until=NOW + timedelta(minutes=30),
        source_version=ref("identity_session", "session-1"),
        source_revision="1",
        is_fixture=False,
    )
    return AuthenticatedPrincipal.model_validate({**base.model_dump(), **changes})


def authorization(**changes: object) -> AuthorizationSnapshot:
    base = AuthorizationSnapshot(
        authorization_id="mandate-1",
        user_id="user-1",
        status=AuthorizationStatus.ACTIVE,
        autonomy_level=AutonomyLevel.L2,
        allowed_markets=("CN", "HK", "US"),
        allowed_assets=("stock", "etf", "lof", "otc_fund"),
        allowed_sides=(
            "buy",
            "sell",
            "short",
            "subscribe",
            "redeem",
            "convert",
            "recurring_invest",
        ),
        allowed_order_types=("market", "limit", "fund"),
        short_markets=("HK", "US"),
        limits=authorization_limits(),
        valid_from=NOW - timedelta(days=1),
        captured_at=NOW - timedelta(seconds=1),
        valid_until=NOW + timedelta(days=1),
        source_version=ref("investment_mandate", "mandate-1"),
        source_revision="1",
        is_fixture=False,
    )
    return AuthorizationSnapshot.model_validate({**base.model_dump(), **changes})


def cooldown(**changes: object) -> CooldownSnapshot:
    base = CooldownSnapshot(
        cooldown_id="cooldown-1",
        user_id="user-1",
        active=False,
        captured_at=NOW - timedelta(seconds=1),
        valid_until=NOW + timedelta(minutes=30),
        source_version=ref("cooldown", "cooldown-1"),
        source_revision="1",
        is_fixture=False,
    )
    return CooldownSnapshot.model_validate({**base.model_dump(), **changes})


def position(
    *,
    asset_kind: AssetKind = AssetKind.STOCK,
    long_quantity: Decimal = Decimal("100"),
    short_quantity: Decimal = Decimal("0"),
    settled_quantity: Decimal = Decimal("100"),
    sellable_quantity: Decimal = Decimal("100"),
    fund_shares: Decimal = Decimal("0"),
    long_value: Decimal = Decimal("1000"),
    short_value: Decimal = Decimal("0"),
) -> PositionLine:
    return PositionLine(
        instrument_id="000001.SZ",
        asset_kind=asset_kind,
        industry="financials",
        long_quantity=long_quantity,
        short_quantity=short_quantity,
        settled_quantity=settled_quantity,
        sellable_quantity=sellable_quantity,
        fund_shares=fund_shares,
        long_market_value=long_value,
        short_market_value=short_value,
    )


def risk_input(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal | None = Decimal("100"),
    amount: Decimal | None = None,
    market: str = "CN",
    kind: AssetKind = AssetKind.STOCK,
    broad: bool = False,
    nominal_price: Decimal = Decimal("10"),
    positions: tuple[PositionLine, ...] | None = None,
    borrow: BorrowSnapshot | None = None,
    fund_rule: FundRuleSnapshot | None = None,
    fund_conversion: FundConversionSnapshot | None = None,
    frequency: DataFrequency | None = None,
) -> RiskInputSnapshot:
    is_fund = kind is AssetKind.OTC_FUND
    effective_frequency = (
        DataFrequency.FUND_NAV
        if is_fund and frequency is None
        else (DataFrequency.TRUE_SNAPSHOT if frequency is None else frequency)
    )
    order_type = OrderType.FUND if is_fund else OrderType.MARKET
    tif = None if is_fund else TimeInForce.DAY
    market_evidence = evidence("market_data", "000001.SZ")
    if effective_frequency is DataFrequency.DAILY:
        market_evidence = evidence(
            "market_data",
            "000001.SZ",
            captured_at=NOW - timedelta(hours=10),
        )
    lines: tuple[PositionLine, ...]
    if positions is None and kind is AssetKind.OTC_FUND:
        lines = (
            position(
                asset_kind=AssetKind.OTC_FUND,
                long_quantity=Decimal("0"),
                fund_shares=Decimal("100"),
            ),
        )
    elif positions is None:
        lines = (position(asset_kind=kind),)
    else:
        lines = positions
    draft_nominal = (
        amount
        if amount is not None
        else (Decimal("0") if quantity is None else quantity * nominal_price)
    )
    return RiskInputSnapshot(
        agent_control=AgentControlSnapshot(
            evidence=evidence("agent_control", "user-1"),
            user_id="user-1",
            new_workflows_paused=False,
        ),
        hard_halt=HardHaltSnapshot(
            evidence=evidence("hard_halt", "global"),
            active=False,
        ),
        draft=DraftRiskSnapshot(
            evidence=evidence("order_draft", "draft-1"),
            draft_id="draft-1",
            draft_hash="a" * 64,
            draft_revision=1,
            account_id="account-1",
            owner_user_id="user-1",
            instrument_id="000001.SZ",
            origin=DraftOrigin.MANUAL,
            side=side,
            order_type=order_type,
            quantity=quantity,
            amount=amount,
            limit_price=None,
            time_in_force=tif,
        ),
        account=AccountRiskSnapshot(
            evidence=evidence("account", "account-1", version="3"),
            account_id="account-1",
            owner_user_id="user-1",
            account_currency="CNY",
            revision=3,
            available_cash=Decimal("100000"),
            net_asset_value=Decimal("100000"),
            daily_turnover=Decimal("1000"),
            gross_long_value=Decimal("1000"),
            gross_short_value=Decimal("0"),
            similar_open_order_count=0,
            industry_exposures=(
                IndustryExposure(industry="financials", market_value=Decimal("1000")),
            ),
        ),
        positions=PositionBookSnapshot(
            evidence=evidence("position_book", "account-1", version="4"),
            account_id="account-1",
            revision=4,
            positions=lines,
        ),
        instrument=InstrumentSnapshot(
            evidence=evidence("instrument_master", "000001.SZ"),
            instrument_id="000001.SZ",
            market=market,
            asset_kind=kind,
            industry="financials",
            currency="CNY",
            supported=True,
            master_current=True,
            broad_master_confirmed=broad,
            quantity_step=None if is_fund else Decimal("1"),
            minimum_quantity=None if is_fund else Decimal("1"),
            maximum_quantity=None if is_fund else Decimal("1000000"),
            price_tick=None if is_fund else Decimal("0.01"),
            allowed_time_in_force=(
                ()
                if is_fund
                else (
                    TimeInForce.DAY,
                    TimeInForce.GOOD_TIL_CANCELLED,
                    TimeInForce.IMMEDIATE_OR_CANCEL,
                )
            ),
        ),
        calendar=CalendarSnapshot(
            evidence=evidence("trading_calendar", market),
            market=market,
            trading_date=date(2026, 7, 24),
            latest_completed_trading_date=date(2026, 7, 23),
            is_trading_day=True,
            session_start=NOW - timedelta(hours=1),
            session_end=NOW + timedelta(hours=6),
        ),
        session=MarketSessionSnapshot(
            evidence=evidence("market_session", market),
            market=market,
            status=(
                MarketSessionStatus.OPEN
                if not is_fund
                else MarketSessionStatus.NAV_PROCESSING
            ),
        ),
        market_data=MarketDataSnapshot(
            evidence=market_evidence,
            instrument_id="000001.SZ",
            market=market,
            currency="CNY",
            available=True,
            reference_price=nominal_price,
            frequency=effective_frequency,
            data_date=(
                date(2026, 7, 23)
                if effective_frequency
                in {
                    DataFrequency.DAILY,
                    DataFrequency.FUND_NAV,
                }
                else date(2026, 7, 24)
            ),
            execution_mode=(
                "next_daily_bar"
                if effective_frequency is DataFrequency.DAILY
                else ("fund_nav" if is_fund else "current_session")
            ),
        ),
        fx=FxSnapshot(
            evidence=evidence("fx_snapshot", "CNY/CNY"),
            available=True,
            base_currency="CNY",
            quote_currency="CNY",
            rate=Decimal("1"),
        ),
        fee=FeeSnapshot(
            evidence=evidence("fee_quote", "draft-1"),
            draft_id="draft-1",
            available=True,
            currency="CNY",
            estimated_fee=Decimal("1"),
            maximum_fee=Decimal("2"),
        ),
        slippage=SlippageSnapshot(
            evidence=evidence("slippage_quote", "draft-1"),
            draft_id="draft-1",
            available=True,
            currency="CNY",
            estimated_amount=draft_nominal * Decimal("10") / Decimal("10000"),
            bps=Decimal("10"),
        ),
        borrow=borrow,
        fund_rule=fund_rule,
        fund_conversion=fund_conversion,
        rule=evidence(
            RISK_RULE_REFERENCE.object_type,
            RISK_RULE_REFERENCE.object_id,
            version=RISK_RULE_REFERENCE.version,
        ),
        plan_workflows=(workflow_dependency(),),
    )


def with_exposure(
    snapshot: RiskInputSnapshot,
    *,
    long_value: Decimal,
    short_value: Decimal = Decimal("0"),
    industry_value: Decimal | None = None,
) -> RiskInputSnapshot:
    first = snapshot.positions.positions[0].model_copy(
        update={
            "long_market_value": long_value,
            "short_market_value": short_value,
        }
    )
    industry = long_value + short_value if industry_value is None else industry_value
    return snapshot.model_copy(
        update={
            "positions": snapshot.positions.model_copy(update={"positions": (first,)}),
            "account": snapshot.account.model_copy(
                update={
                    "gross_long_value": long_value,
                    "gross_short_value": short_value,
                    "industry_exposures": (
                        IndustryExposure(
                            industry="financials",
                            market_value=industry,
                        ),
                    ),
                }
            ),
        }
    )


def borrow_snapshot(
    *,
    market: str = "US",
    available_quantity: Decimal = Decimal("500"),
    annual_fee_ratio: Decimal = Decimal("0.05"),
    initial_margin_ratio: Decimal = Decimal("1.50"),
    maintenance_margin_ratio: Decimal = Decimal("1.35"),
    shortable: bool = True,
) -> BorrowSnapshot:
    return BorrowSnapshot(
        evidence=evidence(
            "borrow_snapshot",
            "000001.SZ",
            captured_at=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(minutes=59),
        ),
        instrument_id="000001.SZ",
        market=market,
        shortable=shortable,
        available_quantity=available_quantity,
        annual_fee_ratio=annual_fee_ratio,
        initial_margin_ratio=initial_margin_ratio,
        maintenance_margin_ratio=maintenance_margin_ratio,
        recall_active=False,
        short_sale_restricted=False,
        liquidation_margin_ratio=Decimal("1.20"),
        margin_rule_reference=ref("margin_rule", market, "risk-rules-v1"),
    )


def fund_snapshot(
    *,
    minimum_amount: Decimal = Decimal("10"),
    cutoff_at: datetime = NOW + timedelta(hours=7),
    expected_nav_publication_at: datetime = NOW + timedelta(days=1),
    final_nav: Decimal | None = None,
) -> FundRuleSnapshot:
    return FundRuleSnapshot(
        evidence=evidence("fund_rule", "000001.SZ"),
        instrument_id="000001.SZ",
        minimum_amount=minimum_amount,
        minimum_redeem_shares=Decimal("1"),
        effective_cutoff_at=cutoff_at,
        application_date=date(2026, 7, 24),
        expected_application_date=date(2026, 7, 24),
        expected_confirmation_date=date(2026, 7, 28),
        latest_official_nav_date=date(2026, 7, 23),
        expected_nav_date=date(2026, 7, 24),
        expected_nav_publication_at=expected_nav_publication_at,
        final_nav=final_nav,
        final_nav_date=date(2026, 7, 24) if final_nav is not None else None,
    )


def conversion_snapshot() -> FundConversionSnapshot:
    return FundConversionSnapshot(
        evidence=evidence("fund_conversion_target", "FUND2.OF"),
        source_instrument_id="000001.SZ",
        target_instrument_id="FUND2.OF",
        target_market="CN",
        target_asset_kind=AssetKind.OTC_FUND,
        target_industry="balanced_fund",
        target_currency="CNY",
        target_supported=True,
        target_master_current=True,
    )


class StaticAccessProvider:
    def __init__(
        self,
        *,
        authenticated: AuthenticatedPrincipal,
        mandate: AuthorizationSnapshot,
        cooldown_snapshot: CooldownSnapshot,
    ) -> None:
        self.authenticated = authenticated
        self.mandate = mandate
        self.cooldown_snapshot = cooldown_snapshot

    def current_principal(self) -> AuthenticatedPrincipal:
        return self.authenticated

    def authorization_for(
        self,
        authenticated: AuthenticatedPrincipal,
    ) -> AuthorizationSnapshot:
        del authenticated
        return self.mandate

    def cooldown_for(
        self,
        authenticated: AuthenticatedPrincipal,
    ) -> CooldownSnapshot:
        del authenticated
        return self.cooldown_snapshot


def access_resolver(
    *,
    authenticated: AuthenticatedPrincipal | None = None,
    mandate: AuthorizationSnapshot | None = None,
    cooldown_snapshot: CooldownSnapshot | None = None,
    environment: RuntimeEnvironment = RuntimeEnvironment.PRODUCTION,
    clock: Clock | None = None,
) -> AccessResolver:
    provider = StaticAccessProvider(
        authenticated=principal() if authenticated is None else authenticated,
        mandate=authorization() if mandate is None else mandate,
        cooldown_snapshot=(
            cooldown() if cooldown_snapshot is None else cooldown_snapshot
        ),
    )
    return AccessResolver(
        environment=environment,
        identity_provider=provider,
        authorization_provider=provider,
        clock=FixedClock() if clock is None else clock,
    )


def evaluate(
    snapshot: RiskInputSnapshot,
    review: str = "review-1",
    *,
    authenticated: AuthenticatedPrincipal | None = None,
    mandate: AuthorizationSnapshot | None = None,
    cooldown_snapshot: CooldownSnapshot | None = None,
) -> RiskCheckResult:
    return PreSubmitRiskService(
        access_resolver=access_resolver(
            authenticated=authenticated,
            mandate=mandate,
            cooldown_snapshot=cooldown_snapshot,
        ),
        clock=FixedClock(),
        store=MemoryStore(),
    ).evaluate(
        review_id=review,
        snapshot=snapshot,
    )


def codes(result: RiskCheckResult) -> set[str]:
    return {reason.code for reason in result.reasons}


class RiskReducingTest(unittest.TestCase):
    def test_only_non_crossing_sell_or_redeem_can_reduce_risk(self) -> None:
        stock = position()
        self.assertTrue(
            risk_reducing(
                side=OrderSide.SELL,
                quantity=Decimal("50"),
                position=stock,
            )
        )
        self.assertFalse(
            risk_reducing(
                side=OrderSide.SELL,
                quantity=Decimal("101"),
                position=stock,
            )
        )
        self.assertFalse(
            risk_reducing(
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                position=stock,
            )
        )
        fund = position(
            asset_kind=AssetKind.OTC_FUND,
            long_quantity=Decimal("0"),
            settled_quantity=Decimal("80"),
            sellable_quantity=Decimal("80"),
            fund_shares=Decimal("80"),
            long_value=Decimal("800"),
        )
        self.assertTrue(
            risk_reducing(
                side=OrderSide.REDEEM,
                quantity=Decimal("20"),
                position=fund,
            )
        )
        self.assertFalse(
            risk_reducing(
                side=OrderSide.CONVERT,
                quantity=Decimal("20"),
                position=fund,
            )
        )


class RiskContractTest(unittest.TestCase):
    def test_snapshot_identity_revision_and_quote_contracts_are_enforced(self) -> None:
        snapshot = risk_input()
        with self.assertRaises(ValidationError):
            EvidenceSnapshot(
                reference=ref("account", "account-1", "2"),
                revision="1",
                captured_at=NOW - timedelta(seconds=1),
                valid_until=NOW + timedelta(minutes=1),
            )
        with self.assertRaises(ValidationError):
            AccountRiskSnapshot.model_validate(
                {
                    **snapshot.account.model_dump(),
                    "evidence": evidence("account", "another-account", version="3"),
                }
            )
        with self.assertRaises(ValidationError):
            DraftRiskSnapshot.model_validate(
                {
                    **snapshot.draft.model_dump(),
                    "evidence": evidence("order_draft", "draft-1", version="2"),
                }
            )
        with self.assertRaises(ValidationError):
            MarketDataSnapshot.model_validate(
                {
                    **snapshot.market_data.model_dump(),
                    "evidence": evidence("market_data", "another-instrument"),
                }
            )
        with self.assertRaises(ValidationError):
            FxSnapshot.model_validate(
                {
                    **snapshot.fx.model_dump(),
                    "rate": Decimal("1.01"),
                }
            )
        with self.assertRaises(ValidationError):
            FeeSnapshot.model_validate(
                {
                    **snapshot.fee.model_dump(),
                    "estimated_fee": Decimal("2"),
                    "maximum_fee": Decimal("1"),
                }
            )

    def test_borrow_and_workflow_contracts_fail_before_evaluation(self) -> None:
        base_borrow = borrow_snapshot()
        borrow_changes: tuple[dict[str, object], ...] = (
            {"maintenance_margin_ratio": Decimal("1.51")},
            {"liquidation_margin_ratio": Decimal("1.35")},
            {"margin_rule_reference": ref("margin_rule", "US", "old-rules")},
        )
        for changes in borrow_changes:
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    BorrowSnapshot.model_validate(
                        {**base_borrow.model_dump(), **changes}
                    )

        dependency = workflow_dependency()
        workflow_changes: tuple[dict[str, object], ...] = (
            {"status": WorkflowRunStatus.FAILED},
            {"trade_eligible": False},
            {"run_reference": ref("workflow_run", "another-run", "3")},
        )
        for changes in workflow_changes:
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    RiskWorkflowDependency.model_validate(
                        {**dependency.model_dump(), **changes}
                    )

    def test_formal_entry_rejects_fixture_access_in_production(self) -> None:
        fixture_principal = principal(
            is_fixture=True,
            source_version=ref("fixture_identity", "session-1"),
        )
        fixture_authorization = authorization(
            is_fixture=True,
            source_version=ref("fixture_authorization", "mandate-1"),
        )
        fixture_cooldown = cooldown(
            is_fixture=True,
            source_version=ref("fixture_cooldown", "cooldown-1"),
        )
        store = MemoryStore()
        service = PreSubmitRiskService(
            access_resolver=access_resolver(
                authenticated=fixture_principal,
                mandate=fixture_authorization,
                cooldown_snapshot=fixture_cooldown,
                environment=RuntimeEnvironment.PRODUCTION,
            ),
            clock=FixedClock(),
            store=store,
        )

        result = service.evaluate(
            review_id="fixture-review",
            snapshot=risk_input(),
        )

        self.assertEqual(result.status, RiskCheckStatus.BLOCKED)
        self.assertIn("access_fixture_forbidden", codes(result))
        stored = store.get("fixture-review")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertIsNone(stored.owner_user_id)


class RiskGateTest(unittest.TestCase):
    def test_identity_owner_authorization_status_level_and_scope_block(self) -> None:
        self.assertIn(
            "access_owner_mismatch",
            codes(
                evaluate(
                    risk_input(),
                    authenticated=principal(user_id="attacker"),
                )
            ),
        )

        for changed, expected in (
            (
                authorization(status=AuthorizationStatus.PAUSED),
                "authorization_inactive",
            ),
            (authorization(autonomy_level=AutonomyLevel.L1), "l2_required"),
            (authorization(valid_until=NOW), "access_expired"),
            (authorization(allowed_markets=("HK", "US")), "market_not_authorized"),
        ):
            self.assertIn(
                expected,
                codes(evaluate(risk_input(), mandate=changed)),
            )

    def test_futures_options_and_a_share_short_are_hard_blocked(self) -> None:
        for kind in (AssetKind.FUTURE, AssetKind.OPTION):
            result = evaluate(risk_input(kind=kind))
            self.assertEqual(result.status, RiskCheckStatus.BLOCKED)
            self.assertIn("asset_research_only", codes(result))

        short = evaluate(
            risk_input(
                side=OrderSide.SHORT,
                market="CN",
                borrow=borrow_snapshot(),
            )
        )
        self.assertIn("a_share_short_forbidden", codes(short))

    def test_missing_stale_and_invalid_daily_market_data_block(self) -> None:
        missing_workflow = risk_input().model_copy(update={"plan_workflows": ()})
        self.assertIn(
            "workflow_dependency_missing",
            codes(evaluate(missing_workflow)),
        )

        missing = risk_input().model_copy(
            update={
                "market_data": risk_input().market_data.model_copy(
                    update={"available": False, "reference_price": None}
                )
            }
        )
        self.assertIn("market_data_missing", codes(evaluate(missing)))

        stale = risk_input().model_copy(
            update={
                "market_data": risk_input().market_data.model_copy(
                    update={
                        "evidence": evidence(
                            "market_data",
                            "000001.SZ",
                            captured_at=NOW - timedelta(seconds=16),
                        )
                    }
                )
            }
        )
        self.assertIn("market_data_stale", codes(evaluate(stale)))

        daily = risk_input(frequency=DataFrequency.DAILY).model_copy(
            update={
                "market_data": risk_input(
                    frequency=DataFrequency.DAILY
                ).market_data.model_copy(update={"data_date": date(2026, 7, 22)})
            }
        )
        self.assertIn("daily_bar_not_latest", codes(evaluate(daily)))

    def test_market_data_identity_date_frequency_and_halt_are_fail_closed(self) -> None:
        mismatched = risk_input()
        mismatched = mismatched.model_copy(
            update={
                "market_data": mismatched.market_data.model_copy(
                    update={"market": "HK"}
                )
            }
        )
        self.assertIn(
            "market_data_identity_mismatch",
            codes(evaluate(mismatched)),
        )

        wrong_snapshot_date = risk_input()
        wrong_snapshot_date = wrong_snapshot_date.model_copy(
            update={
                "market_data": wrong_snapshot_date.market_data.model_copy(
                    update={"data_date": date(2026, 7, 23)}
                )
            }
        )
        self.assertIn(
            "snapshot_trading_date_invalid",
            codes(evaluate(wrong_snapshot_date)),
        )

        daily_halted = risk_input(frequency=DataFrequency.DAILY)
        daily_halted = daily_halted.model_copy(
            update={
                "session": daily_halted.session.model_copy(
                    update={"status": MarketSessionStatus.HALTED}
                )
            }
        )
        self.assertIn("market_halted", codes(evaluate(daily_halted)))

        fund_halted = risk_input(
            side=OrderSide.SUBSCRIBE,
            quantity=None,
            amount=Decimal("1000"),
            kind=AssetKind.OTC_FUND,
            fund_rule=fund_snapshot(),
        )
        fund_halted = fund_halted.model_copy(
            update={
                "session": fund_halted.session.model_copy(
                    update={"status": MarketSessionStatus.HALTED}
                )
            }
        )
        self.assertIn("market_halted", codes(evaluate(fund_halted)))

    def test_fund_nav_and_slippage_conflicts_are_explicit(self) -> None:
        wrong_frequency = risk_input(
            side=OrderSide.SUBSCRIBE,
            quantity=None,
            amount=Decimal("1000"),
            kind=AssetKind.OTC_FUND,
            fund_rule=fund_snapshot(),
            frequency=DataFrequency.TRUE_SNAPSHOT,
        )
        self.assertIn(
            "fund_frequency_invalid",
            codes(evaluate(wrong_frequency)),
        )

        final_conflict = risk_input(
            side=OrderSide.SUBSCRIBE,
            quantity=None,
            amount=Decimal("1000"),
            kind=AssetKind.OTC_FUND,
            fund_rule=fund_snapshot(final_nav=Decimal("11")),
        )
        self.assertIn(
            "fund_nav_value_conflict",
            codes(evaluate(final_conflict)),
        )

        inconsistent_slippage = risk_input()
        inconsistent_slippage = inconsistent_slippage.model_copy(
            update={
                "slippage": inconsistent_slippage.slippage.model_copy(
                    update={"estimated_amount": Decimal("9")}
                )
            }
        )
        self.assertIn(
            "slippage_quote_inconsistent",
            codes(evaluate(inconsistent_slippage)),
        )

    def test_cash_settled_sellable_and_fund_share_rules(self) -> None:
        no_cash = risk_input().model_copy(
            update={
                "account": risk_input().account.model_copy(
                    update={"available_cash": Decimal("100")}
                )
            }
        )
        self.assertIn("cash_insufficient", codes(evaluate(no_cash)))

        foreign = risk_input(market="US")
        foreign = foreign.model_copy(
            update={
                "instrument": foreign.instrument.model_copy(update={"currency": "USD"}),
                "fx": foreign.fx.model_copy(
                    update={
                        "evidence": evidence("fx_snapshot", "USD/CNY"),
                        "base_currency": "USD",
                        "rate": Decimal("7"),
                    }
                ),
                "account": foreign.account.model_copy(
                    update={"available_cash": Decimal("7000")}
                ),
            }
        )
        self.assertIn("cash_insufficient", codes(evaluate(foreign)))

        unavailable = risk_input(
            side=OrderSide.SELL,
            quantity=Decimal("20"),
            positions=(
                position(
                    settled_quantity=Decimal("10"),
                    sellable_quantity=Decimal("10"),
                ),
            ),
        )
        self.assertIn("sellable_quantity_insufficient", codes(evaluate(unavailable)))

        redeem = risk_input(
            side=OrderSide.REDEEM,
            quantity=Decimal("20"),
            amount=None,
            kind=AssetKind.OTC_FUND,
            positions=(
                position(
                    asset_kind=AssetKind.OTC_FUND,
                    long_quantity=Decimal("0"),
                    settled_quantity=Decimal("10"),
                    sellable_quantity=Decimal("10"),
                    fund_shares=Decimal("10"),
                    long_value=Decimal("100"),
                ),
            ),
            fund_rule=fund_snapshot(),
        )
        self.assertIn("fund_shares_insufficient", codes(evaluate(redeem)))

    def test_quantity_price_and_tif_follow_instrument_rules(self) -> None:
        invalid_quantity = risk_input(quantity=Decimal("101"))
        invalid_quantity = invalid_quantity.model_copy(
            update={
                "instrument": invalid_quantity.instrument.model_copy(
                    update={"quantity_step": Decimal("100")}
                )
            }
        )
        self.assertIn("quantity_step_invalid", codes(evaluate(invalid_quantity)))

        invalid_price = risk_input()
        invalid_price = invalid_price.model_copy(
            update={
                "draft": invalid_price.draft.model_copy(
                    update={
                        "order_type": OrderType.LIMIT,
                        "limit_price": Decimal("10.005"),
                    }
                )
            }
        )
        self.assertIn("price_tick_invalid", codes(evaluate(invalid_price)))

        invalid_tif = risk_input()
        invalid_tif = invalid_tif.model_copy(
            update={
                "instrument": invalid_tif.instrument.model_copy(
                    update={"allowed_time_in_force": (TimeInForce.IMMEDIATE_OR_CANCEL,)}
                )
            }
        )
        self.assertIn("time_in_force_unsupported", codes(evaluate(invalid_tif)))

    def test_cooldown_blocks_all_but_strict_reducing_sell_and_redeem(self) -> None:
        active = cooldown(active=True)
        self.assertIn(
            "cooldown_new_risk_blocked",
            codes(evaluate(risk_input(), cooldown_snapshot=active)),
        )
        reducing_sell = evaluate(
            risk_input(
                side=OrderSide.SELL,
                quantity=Decimal("10"),
            ),
            cooldown_snapshot=active,
        )
        self.assertNotIn("cooldown_new_risk_blocked", codes(reducing_sell))
        crossing_sell = evaluate(
            risk_input(
                side=OrderSide.SELL,
                quantity=Decimal("101"),
            ),
            cooldown_snapshot=active,
        )
        self.assertIn("cooldown_new_risk_blocked", codes(crossing_sell))
        reducing_redeem = evaluate(
            risk_input(
                side=OrderSide.REDEEM,
                quantity=Decimal("10"),
                amount=None,
                kind=AssetKind.OTC_FUND,
                fund_rule=fund_snapshot(),
            ),
            cooldown_snapshot=active,
        )
        self.assertNotIn(
            "cooldown_new_risk_blocked",
            codes(reducing_redeem),
        )
        convert = evaluate(
            risk_input(
                side=OrderSide.CONVERT,
                quantity=Decimal("10"),
                amount=None,
                kind=AssetKind.OTC_FUND,
                fund_rule=fund_snapshot(),
            ),
            cooldown_snapshot=active,
        )
        self.assertIn("cooldown_new_risk_blocked", codes(convert))

        reviewed_convert = evaluate(
            risk_input(
                side=OrderSide.CONVERT,
                quantity=Decimal("10"),
                amount=None,
                kind=AssetKind.OTC_FUND,
                fund_rule=fund_snapshot(),
                fund_conversion=conversion_snapshot(),
            )
        )
        self.assertNotEqual(reviewed_convert.status, RiskCheckStatus.BLOCKED)
        self.assertNotIn(
            "fund_conversion_evidence_missing",
            codes(reviewed_convert),
        )

    def test_cooldown_reductions_are_not_blocked_by_preexisting_overlimits(
        self,
    ) -> None:
        active = cooldown(active=True)
        over_limit_stock = with_exposure(
            risk_input(side=OrderSide.SELL, quantity=Decimal("10")),
            long_value=Decimal("120000"),
        )
        stock_result = evaluate(
            over_limit_stock,
            cooldown_snapshot=active,
        )
        self.assertNotEqual(stock_result.status, RiskCheckStatus.BLOCKED)
        self.assertFalse(
            {
                "cooldown_new_risk_blocked",
                "concentration_hard_limit",
                "industry_hard_limit",
                "gross_hard_limit",
                "authorization_concentration_limit",
                "authorization_industry_limit",
                "authorization_gross_limit",
            }
            & codes(stock_result)
        )

        over_limit_fund = with_exposure(
            risk_input(
                side=OrderSide.REDEEM,
                quantity=Decimal("10"),
                amount=None,
                kind=AssetKind.OTC_FUND,
                fund_rule=fund_snapshot(),
            ),
            long_value=Decimal("40000"),
        )
        fund_result = evaluate(
            over_limit_fund,
            cooldown_snapshot=active,
        )
        self.assertNotEqual(fund_result.status, RiskCheckStatus.BLOCKED)
        self.assertFalse(
            {
                "cooldown_new_risk_blocked",
                "concentration_hard_limit",
                "industry_hard_limit",
                "gross_hard_limit",
                "authorization_concentration_limit",
                "authorization_industry_limit",
                "authorization_gross_limit",
            }
            & codes(fund_result)
        )

    def test_hk_us_borrow_and_margin_requirements(self) -> None:
        hk = evaluate(
            risk_input(
                side=OrderSide.SHORT,
                market="HK",
                borrow=borrow_snapshot(
                    market="HK",
                    initial_margin_ratio=Decimal("1.49"),
                ),
            )
        )
        self.assertIn("initial_margin_insufficient", codes(hk))

        us = evaluate(
            risk_input(
                side=OrderSide.SHORT,
                market="US",
                borrow=borrow_snapshot(maintenance_margin_ratio=Decimal("1.34")),
            )
        )
        self.assertIn("maintenance_margin_insufficient", codes(us))

        no_borrow = evaluate(risk_input(side=OrderSide.SHORT, market="US", borrow=None))
        self.assertIn("borrow_evidence_missing", codes(no_borrow))

        stale_borrow = borrow_snapshot().model_copy(
            update={
                "evidence": evidence(
                    "borrow_snapshot",
                    "000001.SZ",
                    captured_at=NOW - timedelta(minutes=61),
                    valid_until=NOW + timedelta(minutes=1),
                )
            }
        )
        stale = evaluate(
            risk_input(
                side=OrderSide.SHORT,
                market="US",
                borrow=stale_borrow,
            )
        )
        self.assertIn("borrow_stale", codes(stale))


class RiskThresholdAndLifecycleTest(unittest.TestCase):
    def test_platform_threshold_boundaries_use_strict_greater_than(self) -> None:
        nav = Decimal("100000")

        def all_in_cost(ratio: Decimal) -> RiskInputSnapshot:
            snapshot = risk_input()
            total_cost = Decimal("1000") * ratio
            slippage_amount = snapshot.slippage.estimated_amount
            assert slippage_amount is not None
            fee = total_cost - slippage_amount
            assert fee >= 0
            return snapshot.model_copy(
                update={
                    "fee": snapshot.fee.model_copy(
                        update={
                            "estimated_fee": fee,
                            "maximum_fee": fee,
                        }
                    )
                }
            )

        def slippage(bps: Decimal) -> RiskInputSnapshot:
            snapshot = risk_input()
            return snapshot.model_copy(
                update={
                    "slippage": snapshot.slippage.model_copy(
                        update={
                            "bps": bps,
                            "estimated_amount": Decimal("1000")
                            * bps
                            / Decimal("10000"),
                        }
                    )
                }
            )

        def price_deviation(ratio: Decimal) -> RiskInputSnapshot:
            snapshot = risk_input()
            limit_price = Decimal("10") * (Decimal("1") + ratio)
            nominal = Decimal("100") * limit_price
            slippage_bps = snapshot.slippage.bps
            assert slippage_bps is not None
            return snapshot.model_copy(
                update={
                    "draft": snapshot.draft.model_copy(
                        update={
                            "order_type": OrderType.LIMIT,
                            "limit_price": limit_price,
                        }
                    ),
                    "instrument": snapshot.instrument.model_copy(
                        update={"price_tick": Decimal("0.001")}
                    ),
                    "slippage": snapshot.slippage.model_copy(
                        update={
                            "estimated_amount": nominal
                            * slippage_bps
                            / Decimal("10000")
                        }
                    ),
                }
            )

        def single_order(ratio: Decimal) -> RiskInputSnapshot:
            snapshot = risk_input(quantity=nav * ratio / Decimal("10"))
            return snapshot.model_copy(
                update={
                    "instrument": snapshot.instrument.model_copy(
                        update={"quantity_step": Decimal("0.1")}
                    )
                }
            )

        def turnover(ratio: Decimal) -> RiskInputSnapshot:
            snapshot = risk_input()
            return snapshot.model_copy(
                update={
                    "account": snapshot.account.model_copy(
                        update={"daily_turnover": nav * ratio - Decimal("1000")}
                    )
                }
            )

        def concentration(ratio: Decimal) -> RiskInputSnapshot:
            return with_exposure(
                risk_input(),
                long_value=nav * ratio - Decimal("1000"),
            )

        def industry(ratio: Decimal) -> RiskInputSnapshot:
            snapshot = risk_input()
            current_total = nav * ratio - Decimal("1000")
            other_value = current_total - Decimal("1000")
            other = PositionLine(
                instrument_id="INDUSTRY-OTHER",
                asset_kind=AssetKind.STOCK,
                industry="financials",
                long_quantity=other_value / Decimal("10"),
                short_quantity=Decimal("0"),
                settled_quantity=other_value / Decimal("10"),
                sellable_quantity=other_value / Decimal("10"),
                fund_shares=Decimal("0"),
                long_market_value=other_value,
                short_market_value=Decimal("0"),
            )
            return snapshot.model_copy(
                update={
                    "positions": snapshot.positions.model_copy(
                        update={
                            "positions": (
                                snapshot.positions.positions[0],
                                other,
                            )
                        }
                    ),
                    "account": snapshot.account.model_copy(
                        update={
                            "gross_long_value": current_total,
                            "industry_exposures": (
                                IndustryExposure(
                                    industry="financials",
                                    market_value=current_total,
                                ),
                            ),
                        }
                    ),
                }
            )

        def gross(ratio: Decimal) -> RiskInputSnapshot:
            snapshot = risk_input()
            current_total = nav * ratio - Decimal("1000")
            other_total = current_total - Decimal("1000")
            first_value = other_total / Decimal("2")
            second_value = other_total - first_value

            def other_position(
                instrument_id: str,
                industry_name: str,
                market_value: Decimal,
            ) -> PositionLine:
                quantity = market_value / Decimal("10")
                return PositionLine(
                    instrument_id=instrument_id,
                    asset_kind=AssetKind.STOCK,
                    industry=industry_name,
                    long_quantity=quantity,
                    short_quantity=Decimal("0"),
                    settled_quantity=quantity,
                    sellable_quantity=quantity,
                    fund_shares=Decimal("0"),
                    long_market_value=market_value,
                    short_market_value=Decimal("0"),
                )

            return snapshot.model_copy(
                update={
                    "positions": snapshot.positions.model_copy(
                        update={
                            "positions": (
                                snapshot.positions.positions[0],
                                other_position(
                                    "GROSS-TECH",
                                    "technology",
                                    first_value,
                                ),
                                other_position(
                                    "GROSS-HEALTH",
                                    "healthcare",
                                    second_value,
                                ),
                            )
                        }
                    ),
                    "account": snapshot.account.model_copy(
                        update={
                            "gross_long_value": current_total,
                            "industry_exposures": (
                                IndustryExposure(
                                    industry="financials",
                                    market_value=Decimal("1000"),
                                ),
                                IndustryExposure(
                                    industry="technology",
                                    market_value=first_value,
                                ),
                                IndustryExposure(
                                    industry="healthcare",
                                    market_value=second_value,
                                ),
                            ),
                        }
                    ),
                }
            )

        def short_gross(ratio: Decimal) -> RiskInputSnapshot:
            current_short = nav * ratio - Decimal("1000")
            snapshot = risk_input(
                side=OrderSide.SHORT,
                market="US",
                borrow=borrow_snapshot(),
                positions=(
                    position(
                        long_quantity=Decimal("0"),
                        settled_quantity=Decimal("0"),
                        sellable_quantity=Decimal("0"),
                        long_value=Decimal("0"),
                    ),
                    PositionLine(
                        instrument_id="SHORT-OTHER",
                        asset_kind=AssetKind.STOCK,
                        industry="technology",
                        long_quantity=Decimal("0"),
                        short_quantity=current_short / Decimal("10"),
                        settled_quantity=Decimal("0"),
                        sellable_quantity=Decimal("0"),
                        fund_shares=Decimal("0"),
                        long_market_value=Decimal("0"),
                        short_market_value=current_short,
                    ),
                ),
            )
            return snapshot.model_copy(
                update={
                    "account": snapshot.account.model_copy(
                        update={
                            "gross_long_value": Decimal("0"),
                            "gross_short_value": current_short,
                            "industry_exposures": (
                                IndustryExposure(
                                    industry="financials",
                                    market_value=Decimal("0"),
                                ),
                                IndustryExposure(
                                    industry="technology",
                                    market_value=current_short,
                                ),
                            ),
                        }
                    )
                }
            )

        def borrow_fee(ratio: Decimal) -> RiskInputSnapshot:
            return risk_input(
                side=OrderSide.SHORT,
                market="US",
                borrow=borrow_snapshot(annual_fee_ratio=ratio),
            )

        boundary_cases: tuple[
            tuple[
                str,
                Callable[[Decimal], RiskInputSnapshot],
                Decimal,
                Decimal,
            ],
            ...,
        ] = (
            (
                "all_in_cost_soft_limit",
                all_in_cost,
                Decimal("0.01"),
                Decimal("0.00001"),
            ),
            (
                "all_in_cost_hard_limit",
                all_in_cost,
                Decimal("0.02"),
                Decimal("0.00001"),
            ),
            (
                "slippage_soft_limit",
                slippage,
                Decimal("50"),
                Decimal("0.01"),
            ),
            (
                "slippage_hard_limit",
                slippage,
                Decimal("100"),
                Decimal("0.01"),
            ),
            (
                "price_deviation_soft_limit",
                price_deviation,
                Decimal("0.05"),
                Decimal("0.0001"),
            ),
            (
                "price_deviation_hard_limit",
                price_deviation,
                Decimal("0.10"),
                Decimal("0.0001"),
            ),
            (
                "single_order_soft_limit",
                single_order,
                Decimal("0.05"),
                Decimal("0.00001"),
            ),
            (
                "single_order_hard_limit",
                single_order,
                Decimal("0.10"),
                Decimal("0.00001"),
            ),
            (
                "daily_turnover_soft_limit",
                turnover,
                Decimal("0.15"),
                Decimal("0.00001"),
            ),
            (
                "daily_turnover_hard_limit",
                turnover,
                Decimal("0.25"),
                Decimal("0.00001"),
            ),
            (
                "concentration_soft_limit",
                concentration,
                Decimal("0.10"),
                Decimal("0.00001"),
            ),
            (
                "concentration_hard_limit",
                concentration,
                Decimal("0.20"),
                Decimal("0.00001"),
            ),
            (
                "industry_soft_limit",
                industry,
                Decimal("0.25"),
                Decimal("0.00001"),
            ),
            (
                "industry_hard_limit",
                industry,
                Decimal("0.35"),
                Decimal("0.00001"),
            ),
            (
                "gross_hard_limit",
                gross,
                Decimal("1.00"),
                Decimal("0.00001"),
            ),
            (
                "short_gross_soft_limit",
                short_gross,
                Decimal("0.15"),
                Decimal("0.00001"),
            ),
            (
                "short_gross_hard_limit",
                short_gross,
                Decimal("0.30"),
                Decimal("0.00001"),
            ),
            (
                "borrow_fee_soft_limit",
                borrow_fee,
                Decimal("0.10"),
                Decimal("0.0001"),
            ),
            (
                "borrow_fee_hard_limit",
                borrow_fee,
                Decimal("0.25"),
                Decimal("0.0001"),
            ),
        )
        for code, build, threshold, epsilon in boundary_cases:
            for label, value, expected in (
                ("below", threshold - epsilon, False),
                ("exact", threshold, False),
                ("above", threshold + epsilon, True),
            ):
                with self.subTest(code=code, boundary=label):
                    self.assertEqual(
                        code in codes(evaluate(build(value))),
                        expected,
                    )

    def test_hard_thresholds_block_and_authorization_can_be_stricter(self) -> None:
        expensive = risk_input().model_copy(
            update={
                "fee": risk_input().fee.model_copy(
                    update={
                        "estimated_fee": Decimal("25"),
                        "maximum_fee": Decimal("25"),
                    }
                )
            }
        )
        self.assertIn("all_in_cost_hard_limit", codes(evaluate(expensive)))

        strict = authorization(
            limits=authorization_limits(max_single_order_amount=Decimal("500"))
        )
        result = evaluate(risk_input(), mandate=strict)
        self.assertIn("authorization_single_order_limit", codes(result))
        self.assertTrue(
            all(reason.severity is RiskSeverity.HARD for reason in result.reasons)
        )

        strict_slippage = authorization(
            limits=authorization_limits(max_slippage_bps=Decimal("40"))
        )
        stricter = risk_input()
        stricter = stricter.model_copy(
            update={
                "slippage": stricter.slippage.model_copy(
                    update={
                        "bps": Decimal("45"),
                        "estimated_amount": Decimal("4.5"),
                    }
                )
            }
        )
        self.assertIn(
            "authorization_slippage_limit",
            codes(evaluate(stricter, mandate=strict_slippage)),
        )

    def test_every_platform_hard_threshold_is_enforced(self) -> None:
        cases: list[tuple[str, RiskInputSnapshot]] = []

        slippage = risk_input()
        slippage = slippage.model_copy(
            update={
                "slippage": slippage.slippage.model_copy(
                    update={
                        "bps": Decimal("100.01"),
                        "estimated_amount": Decimal("10.001"),
                    }
                )
            }
        )
        cases.append(("slippage_hard_limit", slippage))

        deviation = risk_input()
        deviation = deviation.model_copy(
            update={
                "draft": deviation.draft.model_copy(
                    update={
                        "order_type": OrderType.LIMIT,
                        "limit_price": Decimal("11.01"),
                    }
                )
            }
        )
        cases.append(("price_deviation_hard_limit", deviation))
        cases.append(
            (
                "single_order_hard_limit",
                risk_input(quantity=Decimal("1001")),
            )
        )

        turnover = risk_input()
        turnover = turnover.model_copy(
            update={
                "account": turnover.account.model_copy(
                    update={"daily_turnover": Decimal("24001")}
                )
            }
        )
        cases.append(("daily_turnover_hard_limit", turnover))
        cases.append(
            (
                "concentration_hard_limit",
                with_exposure(
                    risk_input(quantity=Decimal("200")),
                    long_value=Decimal("19000"),
                ),
            )
        )
        cases.append(
            (
                "concentration_hard_limit",
                with_exposure(
                    risk_input(
                        kind=AssetKind.ETF,
                        broad=False,
                        quantity=Decimal("200"),
                    ),
                    long_value=Decimal("19000"),
                ),
            )
        )
        cases.append(
            (
                "concentration_hard_limit",
                with_exposure(
                    risk_input(
                        kind=AssetKind.ETF,
                        broad=True,
                        quantity=Decimal("200"),
                    ),
                    long_value=Decimal("34000"),
                ),
            )
        )
        cases.append(
            (
                "concentration_hard_limit",
                with_exposure(
                    risk_input(
                        side=OrderSide.SUBSCRIBE,
                        quantity=None,
                        amount=Decimal("2000"),
                        kind=AssetKind.OTC_FUND,
                        fund_rule=fund_snapshot(),
                    ),
                    long_value=Decimal("29000"),
                ),
            )
        )
        cases.append(
            (
                "industry_hard_limit",
                with_exposure(
                    risk_input(quantity=Decimal("200")),
                    long_value=Decimal("34000"),
                ),
            )
        )
        cases.append(
            (
                "gross_hard_limit",
                with_exposure(
                    risk_input(quantity=Decimal("100")),
                    long_value=Decimal("100000"),
                ),
            )
        )
        cases.append(
            (
                "short_gross_hard_limit",
                with_exposure(
                    risk_input(
                        side=OrderSide.SHORT,
                        quantity=Decimal("200"),
                        market="US",
                        borrow=borrow_snapshot(),
                    ),
                    long_value=Decimal("100000"),
                    short_value=Decimal("29001"),
                ),
            )
        )
        cases.append(
            (
                "single_short_hard_limit",
                risk_input(
                    side=OrderSide.SHORT,
                    quantity=Decimal("1001"),
                    market="US",
                    borrow=borrow_snapshot(available_quantity=Decimal("2000")),
                ),
            )
        )
        cases.append(
            (
                "borrow_fee_hard_limit",
                risk_input(
                    side=OrderSide.SHORT,
                    quantity=Decimal("100"),
                    market="US",
                    borrow=borrow_snapshot(annual_fee_ratio=Decimal("0.2501")),
                ),
            )
        )

        for expected, snapshot in cases:
            with self.subTest(expected=expected):
                result = evaluate(snapshot)
                self.assertEqual(result.status, RiskCheckStatus.BLOCKED)
                self.assertIn(expected, codes(result))

    def test_every_platform_soft_threshold_requires_confirmation(self) -> None:
        cases: list[tuple[str, RiskInputSnapshot]] = []

        cost = risk_input()
        cost = cost.model_copy(
            update={
                "fee": cost.fee.model_copy(
                    update={
                        "estimated_fee": Decimal("10.01"),
                        "maximum_fee": Decimal("10.01"),
                    }
                )
            }
        )
        cases.append(("all_in_cost_soft_limit", cost))

        slippage = risk_input()
        slippage = slippage.model_copy(
            update={
                "slippage": slippage.slippage.model_copy(
                    update={
                        "bps": Decimal("50.01"),
                        "estimated_amount": Decimal("5.001"),
                    }
                )
            }
        )
        cases.append(("slippage_soft_limit", slippage))

        deviation = risk_input()
        deviation = deviation.model_copy(
            update={
                "draft": deviation.draft.model_copy(
                    update={
                        "order_type": OrderType.LIMIT,
                        "limit_price": Decimal("10.51"),
                    }
                ),
                "slippage": deviation.slippage.model_copy(
                    update={"estimated_amount": Decimal("1.051")}
                ),
            }
        )
        cases.append(("price_deviation_soft_limit", deviation))
        cases.append(("single_order_soft_limit", risk_input(quantity=Decimal("501"))))

        turnover = risk_input()
        turnover = turnover.model_copy(
            update={
                "account": turnover.account.model_copy(
                    update={"daily_turnover": Decimal("14001")}
                )
            }
        )
        cases.append(("daily_turnover_soft_limit", turnover))
        cases.append(
            (
                "concentration_soft_limit",
                with_exposure(
                    risk_input(quantity=Decimal("11")),
                    long_value=Decimal("9990"),
                ),
            )
        )
        cases.append(
            (
                "concentration_soft_limit",
                with_exposure(
                    risk_input(
                        kind=AssetKind.ETF,
                        broad=True,
                        quantity=Decimal("11"),
                    ),
                    long_value=Decimal("19990"),
                ),
            )
        )
        cases.append(
            (
                "concentration_soft_limit",
                with_exposure(
                    risk_input(
                        side=OrderSide.SUBSCRIBE,
                        quantity=None,
                        amount=Decimal("100.1"),
                        kind=AssetKind.OTC_FUND,
                        fund_rule=fund_snapshot(),
                    ),
                    long_value=Decimal("15000"),
                ),
            )
        )

        industry = risk_input(quantity=Decimal("10"))
        current = industry.positions.positions[0].model_copy(
            update={"long_market_value": Decimal("1000")}
        )
        other = PositionLine(
            instrument_id="000002.SZ",
            asset_kind=AssetKind.STOCK,
            industry="financials",
            long_quantity=Decimal("2400"),
            short_quantity=Decimal("0"),
            settled_quantity=Decimal("2400"),
            sellable_quantity=Decimal("2400"),
            fund_shares=Decimal("0"),
            long_market_value=Decimal("24000"),
            short_market_value=Decimal("0"),
        )
        industry = industry.model_copy(
            update={
                "positions": industry.positions.model_copy(
                    update={"positions": (current, other)}
                ),
                "account": industry.account.model_copy(
                    update={
                        "gross_long_value": Decimal("25000"),
                        "industry_exposures": (
                            IndustryExposure(
                                industry="financials",
                                market_value=Decimal("25000"),
                            ),
                        ),
                    }
                ),
            }
        )
        cases.append(("industry_soft_limit", industry))

        short_gross = risk_input(
            side=OrderSide.SHORT,
            quantity=Decimal("10"),
            market="US",
            borrow=borrow_snapshot(),
            positions=(
                position(
                    long_quantity=Decimal("0"),
                    settled_quantity=Decimal("0"),
                    sellable_quantity=Decimal("0"),
                    long_value=Decimal("0"),
                ),
                PositionLine(
                    instrument_id="OTHER.US",
                    asset_kind=AssetKind.STOCK,
                    industry="financials",
                    long_quantity=Decimal("0"),
                    short_quantity=Decimal("1500"),
                    settled_quantity=Decimal("0"),
                    sellable_quantity=Decimal("0"),
                    fund_shares=Decimal("0"),
                    long_market_value=Decimal("0"),
                    short_market_value=Decimal("15000"),
                ),
            ),
        )
        short_gross = short_gross.model_copy(
            update={
                "account": short_gross.account.model_copy(
                    update={
                        "gross_long_value": Decimal("0"),
                        "gross_short_value": Decimal("15000"),
                        "industry_exposures": (
                            IndustryExposure(
                                industry="financials",
                                market_value=Decimal("15000"),
                            ),
                        ),
                    }
                )
            }
        )
        cases.append(("short_gross_soft_limit", short_gross))
        cases.append(
            (
                "single_short_soft_limit",
                risk_input(
                    side=OrderSide.SHORT,
                    quantity=Decimal("501"),
                    market="US",
                    borrow=borrow_snapshot(available_quantity=Decimal("1000")),
                ),
            )
        )
        cases.append(
            (
                "borrow_fee_soft_limit",
                risk_input(
                    side=OrderSide.SHORT,
                    quantity=Decimal("100"),
                    market="US",
                    borrow=borrow_snapshot(annual_fee_ratio=Decimal("0.1001")),
                ),
            )
        )

        for expected, snapshot in cases:
            with self.subTest(expected=expected):
                result = evaluate(snapshot)
                self.assertEqual(
                    result.status,
                    RiskCheckStatus.CONFIRMATION_REQUIRED,
                    codes(result),
                )
                self.assertIn(expected, codes(result))
                self.assertTrue(
                    all(
                        reason.severity is RiskSeverity.SOFT
                        for reason in result.reasons
                    )
                )

    def test_single_short_uses_cumulative_instrument_exposure_at_boundary(self) -> None:
        def cumulative(quantity: Decimal) -> RiskInputSnapshot:
            snapshot = risk_input(
                side=OrderSide.SHORT,
                quantity=quantity,
                market="US",
                borrow=borrow_snapshot(available_quantity=Decimal("1000")),
                positions=(
                    position(
                        long_quantity=Decimal("0"),
                        short_quantity=Decimal("500"),
                        settled_quantity=Decimal("0"),
                        sellable_quantity=Decimal("0"),
                        long_value=Decimal("0"),
                        short_value=Decimal("5000"),
                    ),
                ),
            )
            return snapshot.model_copy(
                update={
                    "instrument": snapshot.instrument.model_copy(
                        update={"quantity_step": Decimal("0.1")}
                    ),
                    "account": snapshot.account.model_copy(
                        update={
                            "gross_long_value": Decimal("0"),
                            "gross_short_value": Decimal("5000"),
                            "industry_exposures": (
                                IndustryExposure(
                                    industry="financials",
                                    market_value=Decimal("5000"),
                                ),
                            ),
                        }
                    ),
                }
            )

        exact = evaluate(cumulative(Decimal("500")))
        self.assertNotIn("single_short_hard_limit", codes(exact))
        self.assertIn("single_short_soft_limit", codes(exact))
        self.assertEqual(exact.status, RiskCheckStatus.CONFIRMATION_REQUIRED)

        above = evaluate(cumulative(Decimal("500.1")))
        self.assertIn("single_short_hard_limit", codes(above))
        self.assertEqual(above.status, RiskCheckStatus.BLOCKED)

    def test_soft_threshold_requires_confirmation_without_extending_expiry(
        self,
    ) -> None:
        snapshot = risk_input(quantity=Decimal("600"))
        result = evaluate(snapshot)
        self.assertEqual(result.status, RiskCheckStatus.CONFIRMATION_REQUIRED)
        self.assertIn("single_order_soft_limit", codes(result))
        expiry = result.expires_at
        confirmed = result.confirm_soft_risk(
            AuditReference(
                audit_id="confirm-1",
                actor_id="user-1",
                recorded_at=NOW + timedelta(seconds=1),
            )
        )
        self.assertEqual(confirmed.expires_at, expiry)
        self.assertTrue(confirmed.can_submit_at(NOW + timedelta(seconds=2)))
        self.assertFalse(confirmed.can_submit_at(expiry))

    def test_clean_pass_and_exchange_ttl(self) -> None:
        result = evaluate(risk_input())
        self.assertEqual(result.status, RiskCheckStatus.PASSED)
        self.assertEqual(result.reasons, ())
        self.assertEqual(result.rule_version, RISK_RULE_REFERENCE)
        self.assertEqual(result.expires_at, NOW + timedelta(seconds=120))
        self.assertEqual(len(result.input_versions), 21)
        self.assertIn(
            "workflow_artifact",
            {item.object_type for item in result.input_versions},
        )

        session_limited = risk_input()
        session_limited = session_limited.model_copy(
            update={
                "calendar": session_limited.calendar.model_copy(
                    update={"session_end": NOW + timedelta(seconds=45)}
                )
            }
        )
        self.assertEqual(
            evaluate(session_limited).expires_at,
            NOW + timedelta(seconds=45),
        )

        input_limited = risk_input()
        input_limited = input_limited.model_copy(
            update={
                "fee": input_limited.fee.model_copy(
                    update={
                        "evidence": evidence(
                            "fee_quote",
                            "draft-1",
                            valid_until=NOW + timedelta(seconds=30),
                        )
                    }
                )
            }
        )
        self.assertEqual(
            evaluate(input_limited).expires_at,
            NOW + timedelta(seconds=30),
        )

    def test_input_version_change_expires_result(self) -> None:
        result = evaluate(risk_input())
        changed = tuple(
            ref(item.object_type, item.object_id, "2")
            if item.object_type == "market_data"
            else item
            for item in result.input_versions
        )
        expired = result.expire_if_inputs_changed(
            changed,
            audit_reference=AuditReference(
                audit_id="expire-1",
                actor_id="risk-service",
                recorded_at=NOW + timedelta(seconds=1),
            ),
        )
        self.assertEqual(expired.status, RiskCheckStatus.EXPIRED)

    def test_fund_cutoff_nav_and_fifteen_minute_ttl(self) -> None:
        clean = evaluate(
            risk_input(
                side=OrderSide.SUBSCRIBE,
                quantity=None,
                amount=Decimal("1000"),
                kind=AssetKind.OTC_FUND,
                fund_rule=fund_snapshot(),
            )
        )
        self.assertEqual(clean.expires_at, NOW + timedelta(minutes=15))

        cutoff_limited = evaluate(
            risk_input(
                side=OrderSide.SUBSCRIBE,
                quantity=None,
                amount=Decimal("1000"),
                kind=AssetKind.OTC_FUND,
                fund_rule=fund_snapshot(cutoff_at=NOW + timedelta(minutes=5)),
            )
        )
        self.assertEqual(
            cutoff_limited.expires_at,
            NOW + timedelta(minutes=5),
        )

        missing_after_publication = evaluate(
            risk_input(
                side=OrderSide.SUBSCRIBE,
                quantity=None,
                amount=Decimal("1000"),
                kind=AssetKind.OTC_FUND,
                fund_rule=fund_snapshot(
                    expected_nav_publication_at=NOW - timedelta(seconds=1)
                ),
            )
        )
        self.assertIn("published_fund_nav_missing", codes(missing_after_publication))

        wrong_date = risk_input(
            side=OrderSide.SUBSCRIBE,
            quantity=None,
            amount=Decimal("1000"),
            kind=AssetKind.OTC_FUND,
            fund_rule=fund_snapshot(),
        )
        self.assertIsNotNone(wrong_date.fund_rule)
        assert wrong_date.fund_rule is not None
        wrong_date = wrong_date.model_copy(
            update={
                "fund_rule": wrong_date.fund_rule.model_copy(
                    update={"application_date": date(2026, 7, 25)}
                )
            }
        )
        self.assertIn("fund_application_date_invalid", codes(evaluate(wrong_date)))

    def test_one_review_id_has_exactly_one_formal_result(self) -> None:
        store = MemoryStore()
        service = PreSubmitRiskService(
            access_resolver=access_resolver(),
            clock=FixedClock(),
            store=store,
        )
        snapshot = risk_input()
        first = service.evaluate(review_id="review-1", snapshot=snapshot)
        second = service.evaluate(review_id="review-1", snapshot=snapshot)
        self.assertIs(first, second)
        self.assertEqual(store.saves, 1)

        changed = snapshot.model_copy(
            update={
                "market_data": snapshot.market_data.model_copy(
                    update={
                        "evidence": evidence("market_data", "000001.SZ", version="2")
                    }
                )
            }
        )
        with self.assertRaises(RiskEvaluationConflict):
            service.evaluate(review_id="review-1", snapshot=changed)

        hash_changed = snapshot.model_copy(
            update={"draft": snapshot.draft.model_copy(update={"draft_hash": "b" * 64})}
        )
        with self.assertRaises(RiskEvaluationConflict):
            service.evaluate(review_id="review-1", snapshot=hash_changed)

    def test_confirmation_is_owner_and_revision_bound_and_keeps_ttl(self) -> None:
        clock = MutableClock()
        store = MemoryStore()
        service = PreSubmitRiskService(
            access_resolver=access_resolver(clock=clock),
            clock=clock,
            store=store,
        )
        initial = service.evaluate(
            review_id="confirm-review",
            snapshot=risk_input(quantity=Decimal("600")),
        )
        stored = store.get("confirm-review")
        self.assertIsNotNone(stored)
        assert stored is not None
        original_expiry = initial.expires_at

        with self.assertRaises(RiskStoreConflict):
            service.confirm_soft_risk(
                review_id="confirm-review",
                expected_revision=2,
                seen_rule_version=initial.rule_version,
                seen_reason_summary_hash=stored.reason_summary_hash,
            )
        with self.assertRaises(RiskEvaluationConflict):
            service.confirm_soft_risk(
                review_id="confirm-review",
                expected_revision=1,
                seen_rule_version=ref("risk_rule", "pre_submit", "old"),
                seen_reason_summary_hash=stored.reason_summary_hash,
            )
        with self.assertRaises(RiskEvaluationConflict):
            service.confirm_soft_risk(
                review_id="confirm-review",
                expected_revision=1,
                seen_rule_version=initial.rule_version,
                seen_reason_summary_hash="0" * 64,
            )

        other_user_service = PreSubmitRiskService(
            access_resolver=access_resolver(
                authenticated=principal(user_id="user-2"),
                mandate=authorization(user_id="user-2"),
                cooldown_snapshot=cooldown(user_id="user-2"),
                clock=clock,
            ),
            clock=clock,
            store=store,
        )
        with self.assertRaises(PermissionError):
            other_user_service.confirm_soft_risk(
                review_id="confirm-review",
                expected_revision=1,
                seen_rule_version=initial.rule_version,
                seen_reason_summary_hash=stored.reason_summary_hash,
            )

        clock.current = NOW + timedelta(seconds=1)
        confirmed = service.confirm_soft_risk(
            review_id="confirm-review",
            expected_revision=1,
            seen_rule_version=initial.rule_version,
            seen_reason_summary_hash=stored.reason_summary_hash,
        )
        self.assertEqual(confirmed.revision, 2)
        self.assertEqual(confirmed.expires_at, original_expiry)
        self.assertIsNotNone(confirmed.soft_confirmation)
        self.assertEqual(len(store.histories["confirm-review"]), 2)

    def test_input_change_and_ttl_expiry_are_append_only(self) -> None:
        clock = MutableClock()
        store = MemoryStore()
        service = PreSubmitRiskService(
            access_resolver=access_resolver(clock=clock),
            clock=clock,
            store=store,
        )
        snapshot = risk_input()
        service.evaluate(review_id="changed-review", snapshot=snapshot)
        changed = snapshot.model_copy(
            update={
                "market_data": snapshot.market_data.model_copy(
                    update={
                        "evidence": evidence(
                            "market_data",
                            "000001.SZ",
                            version="2",
                        )
                    }
                )
            }
        )
        clock.current = NOW + timedelta(seconds=1)
        expired_by_change = service.refresh_validity(
            review_id="changed-review",
            expected_revision=1,
            snapshot=changed,
        )
        self.assertEqual(expired_by_change.status, RiskCheckStatus.EXPIRED)
        self.assertEqual(expired_by_change.revision, 2)
        self.assertEqual(len(store.histories["changed-review"]), 2)

        ttl_clock = MutableClock()
        ttl_store = MemoryStore()
        ttl_service = PreSubmitRiskService(
            access_resolver=access_resolver(clock=ttl_clock),
            clock=ttl_clock,
            store=ttl_store,
        )
        ttl_snapshot = risk_input()
        ttl_snapshot = ttl_snapshot.model_copy(
            update={
                "fee": ttl_snapshot.fee.model_copy(
                    update={
                        "evidence": evidence(
                            "fee_quote",
                            "draft-1",
                            valid_until=NOW + timedelta(seconds=5),
                        )
                    }
                )
            }
        )
        initial = ttl_service.evaluate(
            review_id="ttl-review",
            snapshot=ttl_snapshot,
        )
        self.assertEqual(initial.expires_at, NOW + timedelta(seconds=5))
        ttl_clock.current = NOW + timedelta(seconds=6)
        expired_by_ttl = ttl_service.refresh_validity(
            review_id="ttl-review",
            expected_revision=1,
            snapshot=ttl_snapshot,
        )
        self.assertEqual(expired_by_ttl.status, RiskCheckStatus.EXPIRED)
        self.assertEqual(expired_by_ttl.revision, 2)
        self.assertEqual(len(ttl_store.histories["ttl-review"]), 2)

    def test_concurrent_evaluation_and_confirmation_use_compare_and_append(
        self,
    ) -> None:
        store = MemoryStore()
        service = PreSubmitRiskService(
            access_resolver=access_resolver(),
            clock=FixedClock(),
            store=store,
        )
        snapshot = risk_input()
        evaluation_barrier = Barrier(2)

        def evaluate_once() -> RiskCheckResult:
            evaluation_barrier.wait()
            return service.evaluate(review_id="race-review", snapshot=snapshot)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(lambda _: evaluate_once(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(store.saves, 1)
        self.assertEqual(len(store.histories["race-review"]), 1)

        confirmation_store = MemoryStore()
        clock = MutableClock()
        confirmation_service = PreSubmitRiskService(
            access_resolver=access_resolver(clock=clock),
            clock=clock,
            store=confirmation_store,
        )
        initial = confirmation_service.evaluate(
            review_id="confirm-race",
            snapshot=risk_input(quantity=Decimal("600")),
        )
        stored = confirmation_store.get("confirm-race")
        self.assertIsNotNone(stored)
        assert stored is not None
        clock.current = NOW + timedelta(seconds=1)
        confirmation_barrier = Barrier(2)

        def confirm_once() -> RiskCheckResult:
            confirmation_barrier.wait()
            return confirmation_service.confirm_soft_risk(
                review_id="confirm-race",
                expected_revision=1,
                seen_rule_version=initial.rule_version,
                seen_reason_summary_hash=stored.reason_summary_hash,
            )

        outcomes: list[RiskCheckResult | Exception] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(confirm_once) for _ in range(2)]
            for future in futures:
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    outcomes.append(exc)
        self.assertEqual(
            sum(isinstance(item, RiskCheckResult) for item in outcomes),
            1,
        )
        self.assertEqual(
            sum(isinstance(item, RiskStoreConflict) for item in outcomes),
            1,
        )
        self.assertEqual(len(confirmation_store.histories["confirm-race"]), 2)


if __name__ == "__main__":
    unittest.main()
