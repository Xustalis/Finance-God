from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from finance_god.domain import (
    AuditReference,
    DomainInvariantViolation,
    ExchangeOrder,
    ExchangeOrderStatus,
    FundOrder,
    FundOrderStatus,
    FUND_ORDER_TRANSITIONS,
    InvalidStateTransition,
    OrderDraft,
    OrderDraftStatus,
    ORDER_DRAFT_TRANSITIONS,
    OrderSide,
    OrderType,
    RiskCheckResult,
    RiskCheckStatus,
    RISK_CHECK_TRANSITIONS,
    RiskReason,
    RiskSeverity,
    TradePlan,
    TradePlanStatus,
    TRADE_PLAN_TRANSITIONS,
    TimeInForce,
    VersionReference,
    WorkflowBlockReason,
    WorkflowCancellationReason,
    WorkflowDependencySnapshot,
    WorkflowRun,
    WorkflowRunStatus,
    WORKFLOW_RUN_TRANSITIONS,
    derive_exchange_fill_status,
    EXCHANGE_ORDER_TRANSITIONS,
)

NOW = datetime(2026, 7, 23, tzinfo=timezone.utc)
V1 = VersionReference(
    object_type="market_snapshot", object_id="600519.SSE", version="1"
)
V2 = VersionReference(
    object_type="market_snapshot", object_id="600519.SSE", version="2"
)
AUDIT = AuditReference(audit_id="audit-1", actor_id="user-1", recorded_at=NOW)
ARTIFACT = VersionReference(
    object_type="workflow_artifact", object_id="artifact-1", version="1"
)
ARTIFACT_2 = VersionReference(
    object_type="workflow_artifact", object_id="artifact-2", version="1"
)
ARTIFACT_3 = VersionReference(
    object_type="workflow_artifact", object_id="artifact-3", version="1"
)
EVIDENCE = VersionReference(object_type="evidence", object_id="evidence-1", version="1")
CONTRIBUTION = VersionReference(
    object_type="node_contribution", object_id="node-1", version="1"
)


class TransitionContractTest(unittest.TestCase):
    def test_trade_plan_legal_path_is_immutable(self) -> None:
        original = trade_plan()
        reviewed = original.transition(
            TradePlanStatus.PENDING_REVIEW, audit_reference=audit(2)
        )
        confirmed = reviewed.transition(
            TradePlanStatus.CONFIRMED, audit_reference=audit(3)
        )
        executing = confirmed.transition(
            TradePlanStatus.EXECUTING, audit_reference=audit(4)
        )
        partial = executing.transition(
            TradePlanStatus.PARTIALLY_COMPLETED, audit_reference=audit(5)
        )
        completed = partial.transition(
            TradePlanStatus.COMPLETED, audit_reference=audit(6)
        )

        self.assertEqual(original.status, TradePlanStatus.DRAFT)
        self.assertEqual(completed.status, TradePlanStatus.COMPLETED)
        self.assertEqual(completed.revision, 6)
        self.assertIsNot(original, reviewed)

    def test_order_draft_can_return_to_edit_but_confirmed_is_frozen(self) -> None:
        reviewed = order_draft().transition(
            OrderDraftStatus.PENDING_REVIEW, audit_reference=audit(2)
        )
        edited = reviewed.transition(OrderDraftStatus.DRAFT, audit_reference=audit(3))
        confirmed = edited.transition(
            OrderDraftStatus.PENDING_REVIEW, audit_reference=audit(4)
        ).transition(OrderDraftStatus.CONFIRMED, audit_reference=audit(5))

        self.assertEqual(edited.status, OrderDraftStatus.DRAFT)
        with self.assertRaises(InvalidStateTransition):
            confirmed.transition(OrderDraftStatus.DRAFT, audit_reference=audit(6))

    def test_exchange_order_records_partial_and_full_fill_deterministically(
        self,
    ) -> None:
        accepted = exchange_order().transition(
            ExchangeOrderStatus.ACCEPTED, audit_reference=audit(2)
        )
        partial = accepted.record_fill(Decimal("30"), audit_reference=audit(3))
        filled = partial.record_fill(Decimal("70"), audit_reference=audit(4))

        self.assertEqual(partial.status, ExchangeOrderStatus.PARTIALLY_FILLED)
        self.assertEqual(partial.cumulative_filled, Decimal("30"))
        self.assertEqual(filled.status, ExchangeOrderStatus.FILLED)
        self.assertEqual(filled.cumulative_filled, Decimal("100"))
        self.assertEqual(accepted.cumulative_filled, Decimal("0"))

    def test_exchange_fill_cannot_exceed_order_quantity(self) -> None:
        accepted = exchange_order().transition(
            ExchangeOrderStatus.ACCEPTED, audit_reference=audit(2)
        )

        with self.assertRaises(DomainInvariantViolation):
            accepted.record_fill(Decimal("101"), audit_reference=audit(3))

    def test_fund_order_covers_full_prd_path(self) -> None:
        order = fund_order()
        path = (
            FundOrderStatus.PENDING_REVIEW,
            FundOrderStatus.SUBMITTED,
            FundOrderStatus.ACCEPTED,
            FundOrderStatus.PENDING_NAV,
            FundOrderStatus.CONFIRMING,
            FundOrderStatus.PARTIALLY_CONFIRMED,
        )

        for revision, status in enumerate(path, start=2):
            order = order.transition(status, audit_reference=audit(revision))

        self.assertEqual(order.status, FundOrderStatus.PARTIALLY_CONFIRMED)

    def test_invalid_transitions_fail_explicitly(self) -> None:
        fixtures: tuple[tuple[Any, Any], ...] = (
            (trade_plan(), TradePlanStatus.COMPLETED),
            (order_draft(), OrderDraftStatus.CONFIRMED),
            (exchange_order(), ExchangeOrderStatus.FILLED),
            (fund_order(), FundOrderStatus.CONFIRMED),
            (
                risk_check().transition(
                    RiskCheckStatus.PASSED,
                    audit_reference=audit(2),
                    reasons=(),
                ),
                RiskCheckStatus.BLOCKED,
            ),
            (workflow_run(), WorkflowRunStatus.COMPLETED),
        )

        for model, target in fixtures:
            with self.subTest(model=type(model).__name__, target=target):
                with self.assertRaises(InvalidStateTransition):
                    model.transition(target, audit_reference=audit(99))

    def test_transition_tables_cover_every_state_without_unknown_targets(self) -> None:
        tables: tuple[tuple[Any, Any], ...] = (
            (TradePlanStatus, TRADE_PLAN_TRANSITIONS),
            (OrderDraftStatus, ORDER_DRAFT_TRANSITIONS),
            (ExchangeOrderStatus, EXCHANGE_ORDER_TRANSITIONS),
            (FundOrderStatus, FUND_ORDER_TRANSITIONS),
            (RiskCheckStatus, RISK_CHECK_TRANSITIONS),
            (WorkflowRunStatus, WORKFLOW_RUN_TRANSITIONS),
        )

        for enum_type, transitions in tables:
            with self.subTest(state_machine=enum_type.__name__):
                self.assertEqual(set(transitions), set(enum_type))
                self.assertTrue(
                    set()
                    .union(*map(set, transitions.values()))
                    .issubset(set(enum_type))
                )
                self.assertTrue(
                    all(state not in targets for state, targets in transitions.items())
                )

    def test_every_legal_and_illegal_transition_edge_is_explicit(self) -> None:
        machines: tuple[tuple[Any, Any, Any], ...] = (
            (
                TradePlanStatus,
                TRADE_PLAN_TRANSITIONS,
                lambda status: trade_plan()._replace(status=status),
            ),
            (
                OrderDraftStatus,
                ORDER_DRAFT_TRANSITIONS,
                lambda status: order_draft()._replace(status=status),
            ),
            (
                ExchangeOrderStatus,
                EXCHANGE_ORDER_TRANSITIONS,
                exchange_order_in_status,
            ),
            (
                FundOrderStatus,
                FUND_ORDER_TRANSITIONS,
                lambda status: fund_order()._replace(status=status),
            ),
            (
                RiskCheckStatus,
                RISK_CHECK_TRANSITIONS,
                risk_check_in_status,
            ),
            (
                WorkflowRunStatus,
                WORKFLOW_RUN_TRANSITIONS,
                workflow_run_in_status,
            ),
        )

        for enum_type, transitions, factory in machines:
            for source in enum_type:
                model = factory(source)
                for target in enum_type:
                    with self.subTest(
                        state_machine=enum_type.__name__,
                        source=source,
                        target=target,
                    ):
                        if target in transitions[source]:
                            model._ensure_transition(target)
                        else:
                            with self.assertRaises(InvalidStateTransition):
                                model._ensure_transition(target)


class InputInvalidationTest(unittest.TestCase):
    def test_changed_input_expires_plan_draft_and_passed_risk(self) -> None:
        plan = trade_plan()
        draft = order_draft()
        passed = risk_check().transition(
            RiskCheckStatus.PASSED, audit_reference=audit(2), reasons=()
        )

        expired_plan = plan.expire_if_inputs_changed((V2,), audit_reference=audit(3))
        expired_draft = draft.expire_if_inputs_changed((V2,), audit_reference=audit(4))
        expired_risk = passed.expire_if_inputs_changed((V2,), audit_reference=audit(5))

        self.assertEqual(expired_plan.status, TradePlanStatus.EXPIRED)
        self.assertEqual(expired_draft.status, OrderDraftStatus.EXPIRED)
        self.assertEqual(expired_risk.status, RiskCheckStatus.EXPIRED)
        self.assertEqual(expired_plan.input_versions, (V1,))
        self.assertEqual(expired_plan.invalidated_by_versions, (V2,))

    def test_unchanged_inputs_do_not_create_a_new_version(self) -> None:
        plan = trade_plan()
        self.assertIs(
            plan.expire_if_inputs_changed((V1,), audit_reference=audit(2)), plan
        )

    def test_repeated_expiration_is_idempotent(self) -> None:
        expired = trade_plan().expire_if_inputs_changed((V2,), audit_reference=audit(2))

        repeated = expired.expire_if_inputs_changed(
            (
                VersionReference(
                    object_type="market_snapshot",
                    object_id="600519.SSE",
                    version="3",
                ),
            ),
            audit_reference=audit(3),
        )

        self.assertIs(repeated, expired)


class RiskAndWorkflowGovernanceTest(unittest.TestCase):
    def test_soft_risk_requires_audited_confirmation(self) -> None:
        pending = risk_check().transition(
            RiskCheckStatus.CONFIRMATION_REQUIRED,
            audit_reference=audit(2),
            reasons=(
                RiskReason(
                    code="concentration_warning",
                    severity=RiskSeverity.SOFT,
                    message="Concentration requires confirmation.",
                ),
            ),
        )

        self.assertFalse(pending.can_submit_at(NOW + timedelta(minutes=1)))
        confirmed = pending.confirm_soft_risk(audit(3))
        self.assertTrue(confirmed.can_submit_at(NOW + timedelta(minutes=1)))
        self.assertEqual(pending.revision + 1, confirmed.revision)

    def test_blocked_risk_can_never_be_overridden(self) -> None:
        blocked = risk_check().transition(
            RiskCheckStatus.BLOCKED,
            audit_reference=audit(2),
            reasons=(
                RiskReason(
                    code="authorization_revoked",
                    severity=RiskSeverity.HARD,
                    message="Authorization is revoked.",
                ),
            ),
        )

        self.assertFalse(blocked.can_submit_at(NOW + timedelta(minutes=1)))
        with self.assertRaises(InvalidStateTransition):
            blocked.transition(RiskCheckStatus.PASSED, audit_reference=audit(3))

    def test_risk_outcomes_reject_mixed_or_misclassified_reasons(self) -> None:
        soft = RiskReason(
            code="soft_warning",
            severity=RiskSeverity.SOFT,
            message="Soft warning.",
        )
        hard = RiskReason(
            code="hard_block",
            severity=RiskSeverity.HARD,
            message="Hard block.",
        )
        invalid_results = (
            (RiskCheckStatus.PASSED, (soft,)),
            (RiskCheckStatus.CONFIRMATION_REQUIRED, (hard,)),
            (RiskCheckStatus.CONFIRMATION_REQUIRED, (soft, hard)),
            (RiskCheckStatus.CHECKING, (hard,)),
        )

        for status, reasons in invalid_results:
            with self.subTest(status=status, reasons=reasons):
                with self.assertRaises(DomainInvariantViolation):
                    risk_check()._replace(status=status, reasons=reasons)

    def test_risk_submission_is_explicitly_time_bounded(self) -> None:
        passed = risk_check().transition(
            RiskCheckStatus.PASSED,
            audit_reference=audit(2),
            reasons=(),
        )
        soft = (
            risk_check()
            .transition(
                RiskCheckStatus.CONFIRMATION_REQUIRED,
                audit_reference=audit(2),
                reasons=(
                    RiskReason(
                        code="soft_warning",
                        severity=RiskSeverity.SOFT,
                        message="Soft warning.",
                    ),
                ),
            )
            .confirm_soft_risk(audit(3))
        )

        for result in (passed, soft):
            with self.subTest(status=result.status):
                self.assertTrue(result.can_submit_at(NOW + timedelta(minutes=4)))
                self.assertFalse(result.can_submit_at(NOW + timedelta(minutes=5)))
                with self.assertRaises(DomainInvariantViolation):
                    result.can_submit_at(datetime(2026, 7, 23))

        with self.assertRaises(DomainInvariantViolation):
            risk_check()._replace(expires_at=NOW)

    def test_blocked_risk_expires_on_input_change_without_becoming_tradeable(
        self,
    ) -> None:
        blocked = risk_check().transition(
            RiskCheckStatus.BLOCKED,
            audit_reference=audit(2),
            reasons=(
                RiskReason(
                    code="hard_block",
                    severity=RiskSeverity.HARD,
                    message="Hard block.",
                ),
            ),
        )
        expired = blocked.expire_if_inputs_changed((V2,), audit_reference=audit(3))

        self.assertEqual(expired.status, RiskCheckStatus.EXPIRED)
        self.assertEqual(expired.reasons, blocked.reasons)
        self.assertFalse(expired.can_submit_at(NOW + timedelta(minutes=1)))
        with self.assertRaises(InvalidStateTransition):
            expired.transition(
                RiskCheckStatus.PASSED,
                audit_reference=audit(4),
                reasons=(),
            )

    def test_completed_and_trade_eligible_are_independent(self) -> None:
        read_only = (
            workflow_run("company_research")
            .transition(WorkflowRunStatus.RUNNING, audit_reference=audit(2))
            .transition(
                WorkflowRunStatus.COMPLETED,
                audit_reference=audit(3),
                trade_eligible=False,
                final_artifact=ARTIFACT,
            )
        )
        actionable = (
            workflow_run("company_research")
            .transition(WorkflowRunStatus.RUNNING, audit_reference=audit(4))
            .record_evidence(EVIDENCE, audit_reference=audit(5))
            .record_node_contribution(CONTRIBUTION, audit_reference=audit(6))
            .transition(
                WorkflowRunStatus.COMPLETED,
                audit_reference=audit(7),
                trade_eligible=True,
                final_artifact=ARTIFACT,
            )
        )

        self.assertFalse(read_only.can_create_trade_plan)
        self.assertTrue(actionable.can_create_trade_plan)

    def test_input_change_expires_trade_eligible_workflow(self) -> None:
        completed = (
            workflow_run("company_research")
            .transition(WorkflowRunStatus.RUNNING, audit_reference=audit(2))
            .record_evidence(EVIDENCE, audit_reference=audit(3))
            .record_node_contribution(CONTRIBUTION, audit_reference=audit(4))
            .transition(
                WorkflowRunStatus.COMPLETED,
                audit_reference=audit(5),
                trade_eligible=True,
                final_artifact=ARTIFACT,
            )
        )

        expired = completed.expire_if_inputs_changed(
            (V2,),
            audit_reference=audit(6),
        )

        self.assertEqual(expired.status, WorkflowRunStatus.EXPIRED)
        self.assertFalse(expired.trade_eligible)
        self.assertFalse(expired.can_create_trade_plan)
        self.assertEqual(expired.invalidated_by_versions, (V2,))

    def test_review_data_quality_and_blocked_runs_are_never_tradeable(self) -> None:
        for key in ("review_only", "data_quality_review"):
            run = workflow_run(key).transition(
                WorkflowRunStatus.RUNNING, audit_reference=audit(2)
            )
            with self.subTest(workflow=key):
                with self.assertRaises(DomainInvariantViolation):
                    run.transition(
                        WorkflowRunStatus.COMPLETED,
                        audit_reference=audit(3),
                        trade_eligible=True,
                    )

        blocked = workflow_run().transition(
            WorkflowRunStatus.BLOCKED,
            audit_reference=audit(2),
            trade_eligible=False,
            block_reason=WorkflowBlockReason.USER_PAUSED,
        )
        self.assertFalse(blocked.can_create_trade_plan)
        with self.assertRaises(InvalidStateTransition):
            blocked.transition(
                WorkflowRunStatus.COMPLETED,
                audit_reference=audit(3),
                trade_eligible=True,
            )

    def test_trade_eligible_completion_requires_artifact_evidence_and_nodes(
        self,
    ) -> None:
        running = workflow_run().transition(
            WorkflowRunStatus.RUNNING, audit_reference=audit(2)
        )
        with self.assertRaises(DomainInvariantViolation):
            running.transition(
                WorkflowRunStatus.COMPLETED,
                audit_reference=audit(3),
                trade_eligible=True,
            )
        with self.assertRaises(DomainInvariantViolation):
            running.transition(
                WorkflowRunStatus.COMPLETED,
                audit_reference=audit(3),
                trade_eligible=True,
                final_artifact=ARTIFACT,
            )

        evidence_only = running.record_evidence(EVIDENCE, audit_reference=audit(3))
        with self.assertRaises(DomainInvariantViolation):
            evidence_only.transition(
                WorkflowRunStatus.COMPLETED,
                audit_reference=audit(4),
                trade_eligible=True,
                final_artifact=ARTIFACT,
            )

    def test_trade_plan_rejects_non_tradeable_or_read_only_dependencies(self) -> None:
        invalid_dependencies = (
            {
                "status": WorkflowRunStatus.ATTENTION_REQUIRED,
                "trade_eligible": False,
            },
            {"workflow_key": "review_only"},
            {"workflow_key": "data_quality_review"},
        )

        for changes in invalid_dependencies:
            with self.subTest(changes=changes):
                with self.assertRaises(DomainInvariantViolation):
                    WorkflowDependencySnapshot.model_validate(
                        {
                            **workflow_dependency().model_dump(),
                            **changes,
                        }
                    )

    def test_running_user_pause_uses_cancellation_protocol_and_preserves_work(
        self,
    ) -> None:
        running = workflow_run().transition(
            WorkflowRunStatus.RUNNING, audit_reference=audit(2)
        )
        running = running.record_completed_node_artifact(
            ARTIFACT, audit_reference=audit(3)
        )
        running = running.record_evidence(EVIDENCE, audit_reference=audit(4))
        running = running.record_node_contribution(
            CONTRIBUTION, audit_reference=audit(5)
        )

        with self.assertRaises(DomainInvariantViolation):
            running.transition(
                WorkflowRunStatus.BLOCKED,
                audit_reference=audit(6),
                block_reason=WorkflowBlockReason.USER_PAUSED,
            )

        requested = running.transition(
            WorkflowRunStatus.CANCEL_REQUESTED,
            audit_reference=audit(6),
            cancellation_reason=WorkflowCancellationReason.USER_PAUSED,
        )
        requested = requested.record_completed_node_artifact(
            ARTIFACT_2, audit_reference=audit(7)
        )
        cancelling = requested.transition(
            WorkflowRunStatus.CANCELLING, audit_reference=audit(8)
        )
        cancelling = cancelling.record_completed_node_artifact(
            ARTIFACT_3, audit_reference=audit(9)
        )
        cancelled = cancelling.transition(
            WorkflowRunStatus.CANCELLED, audit_reference=audit(10)
        )

        self.assertFalse(cancelled.trade_eligible)
        self.assertEqual(
            cancelled.completed_node_artifacts,
            (ARTIFACT, ARTIFACT_2, ARTIFACT_3),
        )
        self.assertEqual(cancelled.evidence_references, (EVIDENCE,))
        self.assertEqual(cancelled.node_contribution_references, (CONTRIBUTION,))
        with self.assertRaises(InvalidStateTransition):
            cancelled.record_evidence(EVIDENCE, audit_reference=audit(11))

    def test_queued_workflow_rejects_prepopulated_execution_outputs(self) -> None:
        queued = workflow_run()
        with self.assertRaises(InvalidStateTransition):
            queued.record_completed_node_artifact(ARTIFACT, audit_reference=audit(2))

        data = queued.model_dump()
        data["completed_node_artifacts"] = (ARTIFACT,)

        with self.assertRaises(DomainInvariantViolation):
            WorkflowRun.model_validate(data)


class AuditAndOrderInvariantTest(unittest.TestCase):
    def test_every_new_version_requires_and_stores_a_new_audit(self) -> None:
        plan = trade_plan()
        with self.assertRaises(DomainInvariantViolation):
            plan.transition(TradePlanStatus.PENDING_REVIEW, audit_reference=AUDIT)

        reviewed = plan.transition(
            TradePlanStatus.PENDING_REVIEW, audit_reference=audit(2)
        )
        self.assertEqual(reviewed.audit_reference, audit(2))
        self.assertEqual(plan.audit_reference, AUDIT)

        accepted = exchange_order().transition(
            ExchangeOrderStatus.ACCEPTED, audit_reference=audit(2)
        )
        with self.assertRaises(DomainInvariantViolation):
            accepted.record_fill(Decimal("1"), audit_reference=audit(2))

    def test_audit_time_must_advance_strictly(self) -> None:
        plan = trade_plan()
        non_advancing = (
            AuditReference(
                audit_id="audit-same-time",
                actor_id="user-1",
                recorded_at=NOW,
            ),
            AuditReference(
                audit_id="audit-backwards",
                actor_id="user-1",
                recorded_at=NOW - timedelta(seconds=1),
            ),
        )

        for reference in non_advancing:
            with self.subTest(audit=reference.audit_id):
                with self.assertRaises(DomainInvariantViolation):
                    plan.transition(
                        TradePlanStatus.PENDING_REVIEW,
                        audit_reference=reference,
                    )

    def test_plan_and_draft_use_explicit_time_based_expiration(self) -> None:
        with self.assertRaises(DomainInvariantViolation):
            TradePlan.model_validate({**trade_plan().model_dump(), "expires_at": NOW})
        with self.assertRaises(DomainInvariantViolation):
            OrderDraft.model_validate(
                {
                    **order_draft().model_dump(),
                    "valid_until": NOW - timedelta(days=1),
                }
            )

        plan = trade_plan().expire_at(
            NOW + timedelta(hours=1),
            audit_reference=audit(3601),
        )
        draft = order_draft().expire_at(
            NOW + timedelta(hours=1),
            audit_reference=audit(3601),
        )

        self.assertEqual(plan.status, TradePlanStatus.EXPIRED)
        self.assertEqual(draft.status, OrderDraftStatus.EXPIRED)
        self.assertGreater(draft.audit_reference.recorded_at, draft.valid_until)
        with self.assertRaises(DomainInvariantViolation):
            trade_plan().expire_at(
                NOW + timedelta(minutes=30),
                audit_reference=audit(1801),
            )

    def test_expired_pre_execution_plan_rejects_normal_transitions(self) -> None:
        draft = trade_plan()
        pending = draft.transition(
            TradePlanStatus.PENDING_REVIEW,
            audit_reference=audit(2),
        )
        confirmed = pending.transition(
            TradePlanStatus.CONFIRMED,
            audit_reference=audit(3),
        )
        attempts = (
            (draft, TradePlanStatus.PENDING_REVIEW),
            (pending, TradePlanStatus.CONFIRMED),
            (confirmed, TradePlanStatus.EXECUTING),
        )

        for plan, target in attempts:
            with self.subTest(status=plan.status, target=target):
                with self.assertRaises(DomainInvariantViolation):
                    plan.transition(
                        target,
                        audit_reference=audit(3601),
                    )

    def test_started_plan_can_finish_after_plan_expiry(self) -> None:
        executing = (
            trade_plan()
            .transition(
                TradePlanStatus.PENDING_REVIEW,
                audit_reference=audit(2),
            )
            .transition(
                TradePlanStatus.CONFIRMED,
                audit_reference=audit(3),
            )
            .transition(
                TradePlanStatus.EXECUTING,
                audit_reference=audit(4),
            )
        )

        partial = executing.transition(
            TradePlanStatus.PARTIALLY_COMPLETED,
            audit_reference=audit(3601),
        )
        completed = partial.transition(
            TradePlanStatus.COMPLETED,
            audit_reference=audit(3602),
        )

        self.assertEqual(partial.status, TradePlanStatus.PARTIALLY_COMPLETED)
        self.assertEqual(completed.status, TradePlanStatus.COMPLETED)

    def test_exchange_status_rejects_inconsistent_cumulative_fills(self) -> None:
        with self.assertRaises(DomainInvariantViolation):
            derive_exchange_fill_status(Decimal("0"), Decimal("0"))

        invalid_states = (
            (ExchangeOrderStatus.SUBMITTING, Decimal("1")),
            (ExchangeOrderStatus.UNKNOWN, Decimal("1")),
            (ExchangeOrderStatus.ACCEPTED, Decimal("1")),
            (ExchangeOrderStatus.REJECTED, Decimal("1")),
            (ExchangeOrderStatus.PARTIALLY_FILLED, Decimal("0")),
            (ExchangeOrderStatus.PARTIALLY_FILLED, Decimal("100")),
            (ExchangeOrderStatus.FILLED, Decimal("99")),
            (ExchangeOrderStatus.CANCELLING, Decimal("100")),
            (ExchangeOrderStatus.CANCELLED, Decimal("100")),
            (ExchangeOrderStatus.EXPIRED, Decimal("100")),
        )

        for status, cumulative in invalid_states:
            with self.subTest(status=status, cumulative=cumulative):
                with self.assertRaises(DomainInvariantViolation):
                    exchange_order()._replace(
                        status=status,
                        cumulative_filled=cumulative,
                    )

        cancelled_partial = exchange_order()._replace(
            status=ExchangeOrderStatus.CANCELLED,
            cumulative_filled=Decimal("20"),
        )
        self.assertEqual(cancelled_partial.cumulative_filled, Decimal("20"))

    def test_order_draft_separates_exchange_and_fund_semantics(self) -> None:
        invalid_exchange: tuple[dict[str, Any], ...] = (
            {"amount": Decimal("100"), "quantity": Decimal("1")},
            {"time_in_force": None},
            {"side": OrderSide.SUBSCRIBE},
            {"order_type": OrderType.MARKET, "limit_price": Decimal("10")},
        )
        for changes in invalid_exchange:
            with self.subTest(exchange_changes=changes):
                with self.assertRaises(DomainInvariantViolation):
                    OrderDraft.model_validate({**order_draft().model_dump(), **changes})

        fund = fund_order_draft()
        invalid_fund: tuple[dict[str, Any], ...] = (
            {"fund_rule_version": None},
            {"time_in_force": TimeInForce.DAY},
            {"side": OrderSide.BUY},
            {"quantity": Decimal("1"), "amount": Decimal("100")},
        )
        for changes in invalid_fund:
            with self.subTest(fund_changes=changes):
                with self.assertRaises(DomainInvariantViolation):
                    OrderDraft.model_validate({**fund.model_dump(), **changes})


def trade_plan() -> TradePlan:
    return TradePlan(
        plan_id="plan-1",
        revision=1,
        status=TradePlanStatus.DRAFT,
        purpose="Reduce concentration risk.",
        actions=("Sell 100 shares",),
        input_versions=(V1,),
        estimated_fee_rmb=Decimal("8.50"),
        portfolio_impact="Cash increases.",
        disagreements=(),
        workflow_dependencies=(workflow_dependency(),),
        expires_at=NOW + timedelta(hours=1),
        audit_reference=AUDIT,
    )


def order_draft() -> OrderDraft:
    return OrderDraft(
        draft_id="draft-1",
        revision=1,
        status=OrderDraftStatus.DRAFT,
        account_id="account-1",
        instrument_id="600519.SSE",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("100"),
        limit_price=Decimal("1500"),
        time_in_force=TimeInForce.DAY,
        valid_until=NOW + timedelta(hours=1),
        input_versions=(V1,),
        audit_reference=AUDIT,
    )


def fund_order_draft() -> OrderDraft:
    return OrderDraft(
        draft_id="fund-draft-1",
        revision=1,
        status=OrderDraftStatus.DRAFT,
        account_id="account-1",
        instrument_id="000001.OF",
        side=OrderSide.SUBSCRIBE,
        order_type=OrderType.FUND,
        quantity=None,
        amount=Decimal("1000"),
        limit_price=None,
        time_in_force=None,
        fund_rule_version=VersionReference(
            object_type="fund_rules", object_id="000001.OF", version="1"
        ),
        valid_until=NOW + timedelta(days=1),
        input_versions=(V1,),
        audit_reference=AUDIT,
    )


def exchange_order() -> ExchangeOrder:
    return ExchangeOrder(
        order_id="order-1",
        revision=1,
        status=ExchangeOrderStatus.SUBMITTING,
        idempotency_key="idempotency-1",
        draft_reference=VersionReference(
            object_type="order_draft", object_id="draft-1", version="1"
        ),
        quantity=Decimal("100"),
        cumulative_filled=Decimal("0"),
        audit_reference=AUDIT,
    )


def fund_order() -> FundOrder:
    return FundOrder(
        order_id="fund-order-1",
        revision=1,
        status=FundOrderStatus.DRAFT,
        idempotency_key="fund-idempotency-1",
        draft_reference=VersionReference(
            object_type="order_draft", object_id="fund-draft-1", version="1"
        ),
        requested_amount=Decimal("1000"),
        requested_units=None,
        audit_reference=AUDIT,
    )


def risk_check() -> RiskCheckResult:
    return RiskCheckResult(
        risk_check_id="risk-1",
        revision=1,
        status=RiskCheckStatus.CHECKING,
        order_version=VersionReference(
            object_type="order_draft", object_id="draft-1", version="1"
        ),
        rule_version=VersionReference(
            object_type="risk_rules", object_id="simulation-rules", version="1"
        ),
        input_versions=(V1,),
        reasons=(),
        checked_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        audit_reference=AUDIT,
    )


def workflow_run(workflow_key: str = "company_research") -> WorkflowRun:
    return WorkflowRun(
        run_id="run-1",
        revision=1,
        workflow_key=workflow_key,
        workflow_version="1",
        status=WorkflowRunStatus.QUEUED,
        trade_eligible=False,
        input_versions=(V1,),
        final_artifact=None,
        evidence_references=(),
        node_contribution_references=(),
        completed_node_artifacts=(),
        errors=(),
        permissions=("market_data:read",),
        block_reason=None,
        cancellation_reason=None,
        audit_reference=AUDIT,
    )


def exchange_order_in_status(status: ExchangeOrderStatus) -> ExchangeOrder:
    cumulative = Decimal("0")
    if status is ExchangeOrderStatus.PARTIALLY_FILLED:
        cumulative = Decimal("1")
    if status is ExchangeOrderStatus.FILLED:
        cumulative = Decimal("100")
    return exchange_order()._replace(status=status, cumulative_filled=cumulative)


def risk_check_in_status(status: RiskCheckStatus) -> RiskCheckResult:
    reasons: tuple[RiskReason, ...] = ()
    if status is RiskCheckStatus.BLOCKED:
        reasons = (
            RiskReason(
                code="hard_block",
                severity=RiskSeverity.HARD,
                message="Hard block.",
            ),
        )
    if status is RiskCheckStatus.CONFIRMATION_REQUIRED:
        reasons = (
            RiskReason(
                code="soft_warning",
                severity=RiskSeverity.SOFT,
                message="Soft warning.",
            ),
        )
    return risk_check()._replace(status=status, reasons=reasons)


def workflow_run_in_status(status: WorkflowRunStatus) -> WorkflowRun:
    queued = workflow_run()
    if status is WorkflowRunStatus.QUEUED:
        return queued
    if status is WorkflowRunStatus.BLOCKED:
        return queued.transition(
            status,
            audit_reference=audit(2),
            block_reason=WorkflowBlockReason.USER_PAUSED,
        )
    if status in {WorkflowRunStatus.FAILED, WorkflowRunStatus.TIMED_OUT}:
        return queued.transition(status, audit_reference=audit(2))

    running = queued.transition(WorkflowRunStatus.RUNNING, audit_reference=audit(2))
    if status is WorkflowRunStatus.RUNNING:
        return running
    if status is WorkflowRunStatus.COMPLETED:
        return running.transition(
            status,
            audit_reference=audit(3),
            trade_eligible=False,
            final_artifact=ARTIFACT,
        )
    if status is WorkflowRunStatus.ATTENTION_REQUIRED:
        return running.transition(status, audit_reference=audit(3))
    if status is WorkflowRunStatus.EXPIRED:
        completed = running.transition(
            WorkflowRunStatus.COMPLETED,
            audit_reference=audit(3),
            trade_eligible=False,
            final_artifact=ARTIFACT,
        )
        return completed.expire_if_inputs_changed((V2,), audit_reference=audit(4))

    requested = running.transition(
        WorkflowRunStatus.CANCEL_REQUESTED,
        audit_reference=audit(3),
        cancellation_reason=WorkflowCancellationReason.USER_PAUSED,
    )
    if status is WorkflowRunStatus.CANCEL_REQUESTED:
        return requested
    cancelling = requested.transition(
        WorkflowRunStatus.CANCELLING, audit_reference=audit(4)
    )
    if status is WorkflowRunStatus.CANCELLING:
        return cancelling
    return cancelling.transition(WorkflowRunStatus.CANCELLED, audit_reference=audit(5))


def workflow_dependency(
    workflow_key: str = "company_research",
) -> WorkflowDependencySnapshot:
    return WorkflowDependencySnapshot(
        run_reference=VersionReference(
            object_type="workflow_run", object_id="run-1", version="3"
        ),
        workflow_key=workflow_key,
        workflow_version="1",
        status=WorkflowRunStatus.COMPLETED,
        trade_eligible=True,
        final_artifact=ARTIFACT,
        evidence_references=(EVIDENCE,),
        node_contribution_references=(CONTRIBUTION,),
    )


def audit(number: int) -> AuditReference:
    return AuditReference(
        audit_id=f"audit-{number}",
        actor_id="user-1",
        recorded_at=NOW + timedelta(seconds=number),
    )


if __name__ == "__main__":
    unittest.main()
