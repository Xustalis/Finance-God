from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from finance_god.market_data import (
    DataCategory,
    DataEnvelope,
    DataFrequency,
    DiagnosticCode,
    DQTrigger,
    DQTriggerRequest,
    DQWorkflowReceipt,
    EmptyMeaning,
    InMemoryDQTriggerRepository,
    InMemoryScopeFreezeRepository,
    QualityContext,
    QualityGate,
    FactorQuery,
    ReleaseState,
)
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER
from finance_god.market_data.normalization import diagnostic, valid_no_event
from finance_god.market_data.quality import _data_version

from .conftest import NOW, FakeSDK, adapter, bar


def quality_context(
    scope: str,
    *,
    category: DataCategory = DataCategory.BAR,
    frequency: DataFrequency = DataFrequency.MINUTE_1,
    endpoint: str | None = "get_stock_rt_min",
) -> QualityContext:
    return QualityContext(
        affected_scope=scope,
        category=category,
        frequency=frequency,
        instrument_master_identity=DEFAULT_INSTRUMENT_MASTER.identity,
        instrument_master_version=DEFAULT_INSTRUMENT_MASTER.version,
        source_endpoint=endpoint,
    )


class WorkflowSpy:
    def __init__(self) -> None:
        self.requests: list[DQTriggerRequest] = []

    async def start(self, request: DQTriggerRequest) -> DQWorkflowReceipt:
        self.requests.append(request)
        return DQWorkflowReceipt(
            workflow_run_id="dq-run-1",
            idempotency_key=request.idempotency_key,
        )


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
        context=quality_context(
            "AAPL.US:1d",
            frequency=DataFrequency.DAILY,
            endpoint="get_us_daily",
        ),
        observed_at=NOW,
    )
    no_event = gate.evaluate(
        valid_no_event(
            scope="000001.SZ:events",
            endpoint="get_fina_reports",
            message="no event in requested period",
        ),
        context=quality_context(
            "000001.SZ:events",
            category=DataCategory.FINANCIAL,
            frequency=DataFrequency.EVENT,
            endpoint="get_fina_reports",
        ),
        observed_at=NOW,
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
        context=quality_context("000001.SZ:1m"),
        observed_at=NOW,
    )
    workflow = WorkflowSpy()
    trigger = DQTrigger(InMemoryDQTriggerRepository(), workflow)

    first = asyncio.run(trigger.trigger(decision, source_workflow="market_context"))
    duplicate = asyncio.run(trigger.trigger(decision, source_workflow="market_context"))
    recursive = asyncio.run(
        trigger.trigger(decision, source_workflow="data_quality_review")
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
        context=quality_context("000001.SZ:1m"),
        observed_at=NOW,
    )

    class FailingThenPassingWorkflow:
        def __init__(self) -> None:
            self.attempts = 0

        async def start(self, request: DQTriggerRequest) -> DQWorkflowReceipt:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("workflow unavailable")
            return DQWorkflowReceipt(
                workflow_run_id="dq-run-2",
                idempotency_key=request.idempotency_key,
            )

    workflow = FailingThenPassingWorkflow()
    trigger = DQTrigger(InMemoryDQTriggerRepository(), workflow)

    try:
        asyncio.run(trigger.trigger(decision, source_workflow="market_context"))
    except RuntimeError:
        pass
    retried = asyncio.run(trigger.trigger(decision, source_workflow="market_context"))

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
        context=quality_context("000001.SZ:1m"),
        observed_at=NOW,
    )
    still_blocked = gate.evaluate(
        valid_no_event(
            scope="000001.SZ:1m",
            endpoint="get_stock_rt_min",
            message="new request is valid but prior freeze is unresolved",
        ),
        context=quality_context("000001.SZ:1m"),
        observed_at=NOW,
    )
    active = freezer.active("000001.SZ:1m")

    assert blocked.active_freeze_version == 1
    assert still_blocked.frozen is True
    assert active is not None
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00")]
    clean = adapter(sdk).fetch_bars(
        DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ"),
        frequency=DataFrequency.MINUTE_1,
        start_date="20260723",
        end_date="20260723",
        limit=1,
        release_state=ReleaseState.RELEASED,
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
        context=quality_context("000001.SZ:1m"),
        observed_at=NOW,
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
    envelope: DataEnvelope[Any] = DataEnvelope(
        (), (issue,), EmptyMeaning.UNEXPECTED_MISSING
    )
    decision = gate.evaluate(
        envelope,
        context=quality_context("000001.SZ:1m", endpoint="get_stock_min"),
        observed_at=NOW,
    )

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
    envelopes: tuple[DataEnvelope[Any], ...] = (
        subject.fetch_factors(
            FactorQuery.from_master(
                DEFAULT_INSTRUMENT_MASTER,
                symbol="000001.SZ",
                start_date="20260723",
                end_date="20260723",
                factors=("alpha",),
            )
        ),
        subject.fetch_master([DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")]),
        subject.fetch_calendar(
            market=DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ").market,
            start_date="20260723",
            end_date="20260723",
        ),
    )

    contexts = (
        quality_context(
            envelopes[0].items[0].scope,
            category=DataCategory.FACTOR,
            frequency=DataFrequency.DAILY,
            endpoint="get_factor",
        ),
        quality_context(
            "000001.SZ",
            category=DataCategory.MASTER,
            frequency=DataFrequency.STATIC,
            endpoint="get_stock_detail",
        ),
        quality_context(
            "CN:20260723",
            category=DataCategory.CALENDAR,
            frequency=DataFrequency.DAILY,
            endpoint="get_trade_cal",
        ),
    )
    decisions = [
        QualityGate(InMemoryScopeFreezeRepository()).evaluate(
            envelope,
            context=context,
            observed_at=NOW,
        )
        for envelope, context in zip(envelopes, contexts, strict=True)
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
        scope = f"research:{code.value}"
        issue = diagnostic(
            code=code,
            scope=scope,
            message="request cannot be served",
            endpoint=None,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        )
        decision = QualityGate(InMemoryScopeFreezeRepository()).evaluate(
            DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING),
            context=quality_context(
                scope,
                category=DataCategory.FACTOR,
                frequency=DataFrequency.EVENT,
                endpoint=None,
            ),
            observed_at=NOW,
        )
        assert decision.frozen is True


def test_unresolved_freeze_diagnostic_does_not_change_dq_idempotency() -> None:
    issue = diagnostic(
        code=DiagnosticCode.SCHEMA_DRIFT,
        scope="000001.SZ:1m",
        message="missing close",
        endpoint="get_stock_rt_min",
        empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
    )
    envelope: DataEnvelope[Any] = DataEnvelope(
        (), (issue,), EmptyMeaning.UNEXPECTED_MISSING
    )
    gate = QualityGate(InMemoryScopeFreezeRepository())
    context = quality_context("000001.SZ:1m")
    first_decision = gate.evaluate(
        envelope,
        context=context,
        observed_at=NOW,
    )
    repeated_decision = gate.evaluate(
        envelope,
        context=context,
        observed_at=NOW + timedelta(seconds=5),
    )
    workflow = WorkflowSpy()
    trigger = DQTrigger(InMemoryDQTriggerRepository(), workflow)

    first = asyncio.run(trigger.trigger(first_decision, source_workflow="market_data"))
    repeated = asyncio.run(
        trigger.trigger(repeated_decision, source_workflow="market_data")
    )

    assert first.started is True
    assert repeated.started is False
    assert first.idempotency_key == repeated.idempotency_key
    assert first_decision.fingerprint == repeated_decision.fingerprint
    assert first_decision.defect_detected_at == NOW
    assert repeated_decision.defect_detected_at == NOW
    assert len(workflow.requests) == 1


def test_resolution_rejects_arbitrary_object_and_different_scope() -> None:
    issue = diagnostic(
        code=DiagnosticCode.SCHEMA_DRIFT,
        scope="000001.SZ:1m",
        message="invalid row",
        endpoint="get_stock_rt_min",
        empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
    )
    gate = QualityGate(InMemoryScopeFreezeRepository())
    decision = gate.evaluate(
        DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING),
        context=quality_context("000001.SZ:1m"),
        observed_at=NOW,
    )
    version = decision.active_freeze_version or 0

    with pytest.raises(ValueError, match="canonical normalized"):
        gate.resolve_clean_envelope(
            envelope=DataEnvelope((object(),), (), EmptyMeaning.NOT_EMPTY),
            affected_scope="000001.SZ:1m",
            expected_freeze_version=version,
            reason="invalid object",
        )

    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00", symbol="600519.SH")]
    wrong_scope = adapter(sdk).fetch_bars(
        DEFAULT_INSTRUMENT_MASTER.resolve("600519.SH"),
        frequency=DataFrequency.MINUTE_1,
        start_date="20260723",
        end_date="20260723",
        limit=1,
        release_state=ReleaseState.RELEASED,
    )
    with pytest.raises(ValueError, match="scope"):
        gate.resolve_clean_envelope(
            envelope=wrong_scope,
            affected_scope="000001.SZ:1m",
            expected_freeze_version=version,
            reason="wrong scope",
        )


def test_data_version_excludes_ingestion_and_freshness_evaluation_clocks() -> None:
    first_sdk = FakeSDK()
    second_sdk = FakeSDK()
    response = [bar("20260723 10:31:00")]
    first_sdk.responses["get_stock_rt_min"] = response
    second_sdk.responses["get_stock_rt_min"] = response
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")
    first = adapter(first_sdk).fetch_bars(
        instrument,
        frequency=DataFrequency.MINUTE_1,
        start_date="20260723",
        end_date="20260723",
        limit=1,
        release_state=ReleaseState.RELEASED,
    )
    second = adapter(
        second_sdk,
        now=NOW + timedelta(seconds=5),
    ).fetch_bars(
        instrument,
        frequency=DataFrequency.MINUTE_1,
        start_date="20260723",
        end_date="20260723",
        limit=1,
        release_state=ReleaseState.RELEASED,
    )

    assert first.items[0].source.ingested_at != second.items[0].source.ingested_at
    assert (
        first.items[0].freshness.evaluated_at != second.items[0].freshness.evaluated_at
    )
    assert _data_version(first) == _data_version(second)
