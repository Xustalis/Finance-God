from __future__ import annotations

from finance_god.market_data import (
    DataEnvelope,
    DiagnosticCode,
    DQTrigger,
    DQTriggerRequest,
    EmptyMeaning,
    InMemoryDQTriggerRepository,
    InMemoryScopeFreezeRepository,
    QualityGate,
    FactorQuery,
)
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER
from finance_god.market_data.normalization import diagnostic, valid_no_event

from .conftest import FakeSDK, adapter


class WorkflowSpy:
    def __init__(self) -> None:
        self.requests: list[DQTriggerRequest] = []

    def start(self, request: DQTriggerRequest) -> str:
        self.requests.append(request)
        return "dq-run-1"


def test_quality_gate_freezes_missing_scope_but_not_valid_no_event() -> None:
    missing = diagnostic(
        code=DiagnosticCode.UNEXPECTED_MISSING,
        scope="AAPL.US:1d",
        message="expected daily row is missing",
        endpoint="get_us_daily",
        empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
    )
    freezer = InMemoryScopeFreezeRepository()
    gate = QualityGate(freezer)
    blocked = gate.evaluate(
        DataEnvelope((), (missing,), EmptyMeaning.UNEXPECTED_MISSING),
        affected_scope="AAPL.US:1d",
    )
    no_event = gate.evaluate(
        valid_no_event(
            scope="000001.SZ:events",
            endpoint="get_fina_reports",
            message="no event in requested period",
        ),
        affected_scope="000001.SZ:events",
    )

    assert blocked.frozen is True
    assert blocked.trade_eligible is False
    assert no_event.frozen is False
    assert no_event.trade_eligible is False
    assert no_event.capability_trade_eligible is False
    assert freezer.get("AAPL.US:1d") is not None
    assert freezer.get("000001.SZ:events") is None


def test_dq_trigger_is_idempotent_non_recursive_and_non_tradeable() -> None:
    issue = diagnostic(
        code=DiagnosticCode.SCHEMA_DRIFT,
        scope="000001.SZ:1m",
        message="missing close",
        endpoint="get_stock_rt_min",
        empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
    )
    decision = QualityGate(InMemoryScopeFreezeRepository()).evaluate(
        DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING),
        affected_scope="000001.SZ:1m",
    )
    workflow = WorkflowSpy()
    trigger = DQTrigger(InMemoryDQTriggerRepository(), workflow)

    first = trigger.trigger(decision, source_workflow="market_context")
    duplicate = trigger.trigger(decision, source_workflow="market_context")
    recursive = trigger.trigger(
        decision, source_workflow="data_quality_review"
    )

    assert first.started is True
    assert duplicate.started is False
    assert recursive.started is False
    assert len(workflow.requests) == 1
    request = workflow.requests[0]
    assert request.workflow_key == "data_quality_review"
    assert request.trade_eligible is False
    assert request.recursive_trigger_allowed is False
    assert request.affected_scope == "000001.SZ:1m"


def test_failed_dq_start_releases_idempotency_claim_for_explicit_retry() -> None:
    issue = diagnostic(
        code=DiagnosticCode.SCHEMA_DRIFT,
        scope="000001.SZ:1m",
        message="missing close",
        endpoint="get_stock_rt_min",
        empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
    )
    decision = QualityGate(InMemoryScopeFreezeRepository()).evaluate(
        DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING),
        affected_scope="000001.SZ:1m",
    )

    class FailingThenPassingWorkflow:
        def __init__(self) -> None:
            self.attempts = 0

        def start(self, request: DQTriggerRequest) -> str:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("workflow unavailable")
            return "dq-run-2"

    workflow = FailingThenPassingWorkflow()
    trigger = DQTrigger(InMemoryDQTriggerRepository(), workflow)

    try:
        trigger.trigger(decision, source_workflow="market_context")
    except RuntimeError:
        pass
    retried = trigger.trigger(decision, source_workflow="market_context")

    assert retried.started is True
    assert workflow.attempts == 2


def test_quality_freeze_requires_versioned_resolution_and_new_data() -> None:
    issue = diagnostic(
        code=DiagnosticCode.SCHEMA_DRIFT,
        scope="000001.SZ:1m",
        message="wrong symbol",
        endpoint="get_stock_rt_min",
        empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
    )
    freezer = InMemoryScopeFreezeRepository()
    gate = QualityGate(freezer)
    blocked = gate.evaluate(
        DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING),
        affected_scope="000001.SZ:1m",
    )
    still_blocked = gate.evaluate(
        valid_no_event(
            scope="000001.SZ:1m",
            endpoint="get_fina_reports",
            message="new request is valid but prior freeze is unresolved",
        ),
        affected_scope="000001.SZ:1m",
    )
    active = freezer.active("000001.SZ:1m")

    assert blocked.active_freeze_version == 1
    assert still_blocked.frozen is True
    assert active is not None
    clean = valid_no_event(
        scope="000001.SZ:1m",
        endpoint="get_fina_reports",
        message="validated result",
    )
    try:
        gate.resolve_clean_envelope(
            envelope=clean,
            affected_scope="000001.SZ:1m",
            expected_freeze_version=2,
            reason="reviewed",
        )
    except ValueError as error:
        assert "version mismatch" in str(error)
    else:
        raise AssertionError("wrong freeze version must not resolve a freeze")

    resolved = gate.resolve_clean_envelope(
        envelope=clean,
        affected_scope="000001.SZ:1m",
        expected_freeze_version=1,
        reason="schema corrected and independently validated",
    )
    cleared = gate.evaluate(
        clean,
        affected_scope="000001.SZ:1m",
    )
    assert resolved.resolved_data_version != active.data_version
    assert cleared.frozen is False


def test_quality_gate_rejects_resolution_with_blocking_envelope() -> None:
    issue = diagnostic(
        code=DiagnosticCode.INVALID_PARAMETER,
        scope="000001.SZ:1m",
        message="invalid parameter",
        endpoint="get_stock_min",
        empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
    )
    gate = QualityGate(InMemoryScopeFreezeRepository())
    envelope = DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING)
    decision = gate.evaluate(envelope, affected_scope="000001.SZ:1m")

    try:
        gate.resolve_clean_envelope(
            envelope=envelope,
            affected_scope="000001.SZ:1m",
            expected_freeze_version=decision.active_freeze_version or 0,
            reason="not actually fixed",
        )
    except ValueError as error:
        assert "clean envelope" in str(error)
    else:
        raise AssertionError("blocking data cannot resolve a quality freeze")


def test_fact_master_and_calendar_freshness_are_evaluated_by_quality_gate() -> None:
    sdk = FakeSDK()
    sdk.responses["get_factor"] = [
        {"symbol": "000001.SZ", "date": "20260723", "alpha": 1.0},
    ]
    sdk.responses["get_stock_detail"] = [
        {"symbol": "000001.SZ", "name": "平安银行"},
    ]
    sdk.responses["get_trade_cal"] = [
        {"trade_date": "20260723", "is_trading_day": 1},
    ]
    subject = adapter(sdk)
    envelopes = (
        subject.fetch_factors(
            FactorQuery.from_master(
                DEFAULT_INSTRUMENT_MASTER,
                symbol="000001.SZ",
                start_date="20260723",
                end_date="20260723",
                factors=("alpha",),
            )
        ),
        subject.fetch_master(
            [DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")]
        ),
        subject.fetch_calendar(
            market=DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ").market,
            start_date="20260723",
            end_date="20260723",
        ),
    )

    decisions = [
        QualityGate(InMemoryScopeFreezeRepository()).evaluate(
            envelope,
            affected_scope=f"scope-{index}",
        )
        for index, envelope in enumerate(envelopes)
    ]

    assert all(decision.frozen for decision in decisions)
    assert all(
        any(
            diagnostic_item.details == (("freshness", "unknown"),)
            for diagnostic_item in decision.diagnostics
        )
        for decision in decisions
    )


def test_unsupported_and_invalid_parameter_diagnostics_freeze_scope() -> None:
    for code in (
        DiagnosticCode.UNSUPPORTED_CATEGORY,
        DiagnosticCode.INVALID_PARAMETER,
    ):
        issue = diagnostic(
            code=code,
            scope="research:test",
            message="request cannot be served",
            endpoint=None,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        )
        decision = QualityGate(
            InMemoryScopeFreezeRepository()
        ).evaluate(
            DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING),
            affected_scope=f"research:{code.value}",
        )
        assert decision.frozen is True
