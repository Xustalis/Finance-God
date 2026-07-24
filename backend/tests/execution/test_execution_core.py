from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from finance_god.domain import (
    AuditReference,
    ExchangeOrderStatus,
    OrderDraft,
    OrderDraftStatus,
    OrderSide,
    OrderType,
    RiskCheckResult,
    RiskCheckStatus,
    TimeInForce,
    VersionReference,
)
from finance_god.execution import (
    DeterministicMatcher,
    DraftMode,
    ExecutionFailure,
    ExecutionFailureCode,
    ManualReviewResult,
    SimulationBar,
    SimulationExecutionService,
    SimulationRuleSet,
    StoredDraft,
    StoredOrder,
    SubmissionOutcome,
    SubmissionStatus,
)

NOW = datetime(2026, 7, 24, 2, tzinfo=UTC)
MARKET = VersionReference(
    object_type="pandadata_daily_bar",
    object_id="600519.SSE:2026-07-25",
    version="bar-v1",
)
INPUT = VersionReference(
    object_type="market_snapshot",
    object_id="600519.SSE",
    version="snapshot-v1",
)
HASH = hashlib.sha256(b"request").hexdigest()


def draft(
    *,
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    instrument_id: str = "600519.SSE",
    quantity: Decimal | None = Decimal("100"),
    amount: Decimal | None = None,
    fund_rule_version: VersionReference | None = None,
) -> OrderDraft:
    return OrderDraft(
        draft_id=f"draft-{side.value}",
        revision=1,
        status=OrderDraftStatus.DRAFT,
        account_id="account-1",
        instrument_id=instrument_id,
        side=side,
        order_type=order_type,
        quantity=quantity,
        amount=amount,
        limit_price=limit_price,
        time_in_force=(
            None if order_type is OrderType.FUND else TimeInForce.DAY
        ),
        fund_rule_version=fund_rule_version,
        valid_until=NOW + timedelta(days=2),
        input_versions=(INPUT,),
        audit_reference=AuditReference(
            audit_id="audit-1",
            actor_id="owner-1",
            recorded_at=NOW,
        ),
    )


def bar(*, stale: bool = False, conflict: bool = False) -> SimulationBar:
    return SimulationBar(
        instrument_id="600519.SSE",
        market="CN",
        trading_day="2026-07-25",
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("200"),
        upstream_timestamp=NOW + timedelta(days=1),
        ingested_at=NOW + timedelta(days=1, seconds=1),
        frequency="1d",
        evidence=MARKET,
        stale=stale,
        conflict=conflict,
    )


class MatcherTest(unittest.TestCase):
    def test_market_order_uses_open_slippage_and_participation_cap(self) -> None:
        result = DeterministicMatcher(
            SimulationRuleSet(
                slippage_bps=Decimal("10"),
                volume_participation=Decimal("0.25"),
                fee_bps=Decimal("2"),
            )
        ).match(draft(), bar(), remaining_quantity=Decimal("100"))

        self.assertEqual(result.fill_quantity, Decimal("50"))
        self.assertEqual(result.fill_price, Decimal("100.10000000"))
        self.assertEqual(result.fee, Decimal("1.00100000"))
        self.assertTrue(result.triggered)

    def test_cover_is_a_buy_direction_but_remains_a_distinct_side(self) -> None:
        order = draft(side=OrderSide.COVER)
        result = DeterministicMatcher().match(
            order,
            bar(),
            remaining_quantity=Decimal("10"),
        )

        self.assertEqual(order.side, OrderSide.COVER)
        self.assertGreater(result.fill_price or Decimal("0"), bar().open)

    def test_limit_requires_daily_range_touch(self) -> None:
        missed = DeterministicMatcher().match(
            draft(order_type=OrderType.LIMIT, limit_price=Decimal("80")),
            bar(),
            remaining_quantity=Decimal("100"),
        )
        touched = DeterministicMatcher().match(
            draft(order_type=OrderType.LIMIT, limit_price=Decimal("95")),
            bar(),
            remaining_quantity=Decimal("100"),
        )

        self.assertFalse(missed.triggered)
        self.assertEqual(missed.fill_quantity, Decimal("0"))
        self.assertEqual(touched.fill_price, Decimal("95"))

    def test_stale_and_conflicted_bars_fail_explicitly(self) -> None:
        for value, code in (
            (bar(stale=True), ExecutionFailureCode.MARKET_DATA_STALE),
            (bar(conflict=True), ExecutionFailureCode.MARKET_DATA_CONFLICT),
        ):
            with self.subTest(code=code), self.assertRaises(ExecutionFailure) as caught:
                DeterministicMatcher().match(
                    draft(),
                    value,
                    remaining_quantity=Decimal("1"),
                )
            self.assertEqual(caught.exception.code, code)


class MemoryRepository:
    def __init__(self) -> None:
        self.drafts: dict[str, StoredDraft] = {}
        self.orders: dict[str, StoredOrder] = {}
        self.fills = []
        self.draft_keys: dict[tuple[str, str], tuple[str, str]] = {}
        self.order_keys: dict[tuple[str, str], tuple[str, str]] = {}

    async def create_draft(
        self,
        value: StoredDraft,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> StoredDraft:
        key = (value.owner_id, idempotency_key)
        prior = self.draft_keys.get(key)
        if prior is not None:
            prior_id, prior_hash = prior
            if prior_hash != request_hash:
                raise ValueError("idempotency conflict")
            return self.drafts[prior_id]
        self.drafts[value.draft.draft_id] = value
        self.draft_keys[key] = (value.draft.draft_id, request_hash)
        return value

    async def get_draft(self, draft_id: str) -> StoredDraft | None:
        return self.drafts.get(draft_id)

    async def save_draft(
        self,
        value: StoredDraft,
        *,
        expected_revision: int,
    ) -> None:
        current = self.drafts[value.draft.draft_id]
        if current.record_revision != expected_revision:
            raise ValueError("revision conflict")
        self.drafts[value.draft.draft_id] = value

    async def create_order(
        self,
        value: StoredOrder,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> StoredOrder:
        key = (value.owner_id, idempotency_key)
        prior = self.order_keys.get(key)
        if prior is not None:
            prior_id, prior_hash = prior
            if prior_hash != request_hash:
                raise ValueError("idempotency conflict")
            return self.orders[prior_id]
        self.orders[value.order_id] = value
        self.order_keys[key] = (value.order_id, request_hash)
        return value

    async def get_order(self, order_id: str) -> StoredOrder | None:
        return self.orders.get(order_id)

    async def get_order_for_draft(self, draft_id: str) -> StoredOrder | None:
        return next(
            (
                value
                for value in self.orders.values()
                if value.draft_reference.object_id == draft_id
            ),
            None,
        )

    async def save_order(
        self,
        value: StoredOrder,
        *,
        expected_revision: int,
    ) -> None:
        current = self.orders[value.order_id]
        domain = current.exchange_order or current.fund_order
        assert domain is not None
        if domain.revision != expected_revision:
            raise ValueError("revision conflict")
        self.orders[value.order_id] = value

    async def append_fill(self, value: object) -> None:
        self.fills.append(value)

    async def list_fills(self, order_id: str | None = None) -> tuple:
        return tuple(
            value
            for value in self.fills
            if order_id is None or value.order_id == order_id
        )

    async def list_orders(self, owner_id: str) -> tuple[StoredOrder, ...]:
        return tuple(
            value for value in self.orders.values() if value.owner_id == owner_id
        )


class Clock:
    def now(self) -> datetime:
        return NOW + timedelta(minutes=1)


class IDs:
    def __init__(self) -> None:
        self.counter = 0

    def new_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter}"


class Accounts:
    async def require_current_account(self, owner_id: str, account_id: str) -> None:
        if (owner_id, account_id) != ("owner-1", "account-1"):
            raise PermissionError("account not found")


class Plans:
    async def require_executable(self, reference: VersionReference) -> None:
        if reference.object_type != "trade_plan":
            raise ValueError("not a plan")


class Review:
    async def review(self, value: StoredDraft) -> ManualReviewResult:
        del value
        return ManualReviewResult(succeeded=False, error="agent unavailable")


class Risk:
    async def evaluate(self, value: StoredDraft) -> RiskCheckResult:
        now = NOW + timedelta(minutes=1)
        return RiskCheckResult(
            risk_check_id="risk-1",
            revision=1,
            status=RiskCheckStatus.PASSED,
            order_version=VersionReference(
                object_type="order_draft",
                object_id=value.draft.draft_id,
                version=str(value.draft.revision),
            ),
            rule_version=VersionReference(
                object_type="risk_rules",
                object_id="rules",
                version="1",
            ),
            reasons=(),
            checked_at=now,
            expires_at=now + timedelta(minutes=5),
            input_versions=value.draft.input_versions,
            audit_reference=AuditReference(
                audit_id="risk-audit",
                actor_id="risk-service",
                recorded_at=now,
            ),
        )

    async def confirm_soft(
        self,
        *,
        owner_id: str,
        result: RiskCheckResult,
        seen_reason_hash: str,
    ) -> RiskCheckResult:
        del owner_id, seen_reason_hash
        return result


class Transport:
    def __init__(self, status: SubmissionStatus = SubmissionStatus.ACCEPTED) -> None:
        self.status = status
        self.submit_calls = 0

    async def submit(self, order: StoredOrder) -> SubmissionOutcome:
        del order
        self.submit_calls += 1
        return SubmissionOutcome(status=self.status)

    async def query(self, order: StoredOrder) -> SubmissionOutcome:
        del order
        return SubmissionOutcome(status=SubmissionStatus.ACCEPTED)

    async def cancel(self, order: StoredOrder) -> SubmissionOutcome:
        del order
        return SubmissionOutcome(status=SubmissionStatus.ACCEPTED)


class Bars:
    async def next_bar(self, value: OrderDraft) -> SimulationBar | None:
        del value
        return bar()


class Ledger:
    def __init__(self) -> None:
        self.calls: list[OrderSide] = []

    async def record_exchange_fill(self, **values: object) -> str:
        value = values["draft"]
        assert isinstance(value, OrderDraft)
        self.calls.append(value.side)
        return f"ledger-{len(self.calls)}"


class ExecutionServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repository = MemoryRepository()
        self.transport = Transport()
        self.ledger = Ledger()
        self.service = SimulationExecutionService(
            repository=self.repository,
            accounts=Accounts(),
            plans=Plans(),
            manual_review=Review(),
            risk=Risk(),
            transport=self.transport,
            bars=Bars(),
            ledger=self.ledger,
            matcher=DeterministicMatcher(),
            clock=Clock(),
            ids=IDs(),
        )

    async def _confirmed(self, value: OrderDraft | None = None) -> StoredDraft:
        created = await self.service.create_draft(
            owner_id="owner-1",
            mode=DraftMode.MANUAL,
            draft=value or draft(),
            plan_reference=None,
            idempotency_key="draft-key",
            request_hash=HASH,
        )
        reviewed = await self.service.review(
            owner_id="owner-1",
            draft_id=created.draft.draft_id,
            expected_revision=1,
        )
        self.assertFalse(reviewed.review.succeeded if reviewed.review else True)
        assert reviewed.immutable_summary_hash is not None
        return await self.service.confirm(
            owner_id="owner-1",
            draft_id=created.draft.draft_id,
            expected_revision=reviewed.record_revision,
            seen_summary_hash=reviewed.immutable_summary_hash,
        )

    async def test_manual_review_failure_does_not_bypass_formal_risk(self) -> None:
        confirmed = await self._confirmed()
        self.assertEqual(confirmed.draft.status, OrderDraftStatus.CONFIRMED)
        self.assertEqual(confirmed.risk_result.status, RiskCheckStatus.PASSED)

    async def test_submit_is_idempotent_and_reconcile_records_partial_fill(self) -> None:
        confirmed = await self._confirmed()
        first = await self.service.submit(
            owner_id="owner-1",
            draft_id=confirmed.draft.draft_id,
            idempotency_key="order-key",
            request_hash=HASH,
        )
        second = await self.service.submit(
            owner_id="owner-1",
            draft_id=confirmed.draft.draft_id,
            idempotency_key="order-key",
            request_hash=HASH,
        )
        reconciled = await self.service.reconcile(
            owner_id="owner-1",
            order_id=first.order_id,
        )

        self.assertEqual(first.order_id, second.order_id)
        self.assertEqual(self.transport.submit_calls, 1)
        assert reconciled.exchange_order is not None
        self.assertEqual(
            reconciled.exchange_order.status,
            ExchangeOrderStatus.PARTIALLY_FILLED,
        )
        self.assertEqual(len(self.repository.fills), 1)
        self.assertEqual(self.ledger.calls, [OrderSide.BUY])

    async def test_unknown_submission_is_queried_not_resubmitted(self) -> None:
        self.transport.status = SubmissionStatus.UNKNOWN
        confirmed = await self._confirmed()
        unknown = await self.service.submit(
            owner_id="owner-1",
            draft_id=confirmed.draft.draft_id,
            idempotency_key="order-key",
            request_hash=HASH,
        )
        assert unknown.exchange_order is not None
        self.assertEqual(unknown.exchange_order.status, ExchangeOrderStatus.UNKNOWN)

        await self.service.reconcile(owner_id="owner-1", order_id=unknown.order_id)
        self.assertEqual(self.transport.submit_calls, 1)

    async def test_unavailable_fund_capability_creates_no_order(self) -> None:
        fund = draft(
            side=OrderSide.SUBSCRIBE,
            order_type=OrderType.FUND,
            instrument_id="000001.OF",
            quantity=None,
            amount=Decimal("1000"),
            fund_rule_version=VersionReference(
                object_type="fund_rules",
                object_id="000001.OF",
                version="1",
            ),
        )
        confirmed = await self._confirmed(fund)

        with self.assertRaises(ExecutionFailure) as caught:
            await self.service.submit(
                owner_id="owner-1",
                draft_id=confirmed.draft.draft_id,
                idempotency_key="fund-order-key",
                request_hash=HASH,
            )

        self.assertEqual(
            caught.exception.code,
            ExecutionFailureCode.PANDADATA_CAPABILITY_UNAVAILABLE,
        )
        self.assertEqual(self.repository.orders, {})
