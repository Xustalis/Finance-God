"""Deterministic quality gate and idempotent data-quality workflow trigger."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from threading import Lock
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    DataCategory,
    DataDiagnostic,
    DataEnvelope,
    DataFrequency,
    DiagnosticCode,
    FreshnessStatus,
    NormalizedBar,
    NormalizedCalendarDay,
    NormalizedFact,
    NormalizedIndexWeight,
    NormalizedMasterRecord,
    NormalizedSnapshot,
    SourceStamp,
)
from .instruments import (
    DEFAULT_INSTRUMENT_MASTER_IDENTITY,
    DEFAULT_INSTRUMENT_MASTER_VERSION,
)
from .normalization import diagnostic

QUALITY_POLICY_VERSION = "data-quality-gate-v1"
T = TypeVar("T")

_BLOCKING_CODES = frozenset(
    {
        DiagnosticCode.CAPABILITY_DISABLED,
        DiagnosticCode.AUTHENTICATION_FAILED,
        DiagnosticCode.PERMISSION_DENIED,
        DiagnosticCode.SCHEMA_DRIFT,
        DiagnosticCode.UNEXPECTED_MISSING,
        DiagnosticCode.CONFLICT,
        DiagnosticCode.REFRESH_FAILED,
        DiagnosticCode.TRANSIENT_UPSTREAM,
        DiagnosticCode.DATA_NOT_RELEASED,
        DiagnosticCode.ENVELOPE_CONTRACT,
        DiagnosticCode.UNRESOLVED_QUALITY_FREEZE,
        DiagnosticCode.UNEXPECTED_INTERNAL,
        DiagnosticCode.UNSUPPORTED_CATEGORY,
        DiagnosticCode.INVALID_PARAMETER,
    }
)


class QualityDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str = QUALITY_POLICY_VERSION
    affected_scope: str = Field(min_length=1, max_length=160)
    frozen: bool
    trade_eligible: bool = False
    capability_trade_eligible: bool = False
    diagnostics: tuple[DataDiagnostic, ...]
    fingerprint: str = Field(min_length=64, max_length=64)
    active_freeze_version: int | None = Field(default=None, ge=1)
    defect_detected_at: datetime | None = None

    @model_validator(mode="after")
    def enforce_eligibility_invariant(self) -> QualityDecision:
        if self.frozen and self.trade_eligible:
            raise ValueError("frozen quality scope cannot be trade eligible")
        if self.trade_eligible and not self.capability_trade_eligible:
            raise ValueError("capability-ineligible data cannot become trade eligible")
        if (
            self.defect_detected_at is not None
            and self.defect_detected_at.tzinfo is None
        ):
            raise ValueError("defect_detected_at must be timezone-aware")
        return self


class ScopeFreezeStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"


class QualityContext(BaseModel):
    """Immutable request identity bound to a quality freeze."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    affected_scope: str = Field(min_length=1, max_length=160)
    category: DataCategory
    frequency: DataFrequency
    instrument_master_identity: str = Field(min_length=1, max_length=96)
    instrument_master_version: str = Field(min_length=64, max_length=64)
    source_provider: Literal["PandaData"] = "PandaData"
    source_endpoint: str | None = Field(
        default=None,
        min_length=5,
        max_length=96,
        pattern=r"^get_[a-z0-9_]+$",
    )


class ScopeFreezeRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    affected_scope: str = Field(min_length=1, max_length=160)
    quality_fingerprint: str = Field(min_length=64, max_length=64)
    data_version: str = Field(min_length=64, max_length=64)
    freeze_version: int = Field(ge=1)
    status: ScopeFreezeStatus
    policy_version: str = QUALITY_POLICY_VERSION
    context: QualityContext
    first_detected_at: datetime
    resolution_reason: str | None = Field(default=None, min_length=1, max_length=240)
    resolved_data_version: str | None = Field(
        default=None, min_length=64, max_length=64
    )

    @model_validator(mode="after")
    def enforce_resolution_state(self) -> ScopeFreezeRecord:
        if self.first_detected_at.tzinfo is None:
            raise ValueError("first_detected_at must be timezone-aware")
        resolved = self.status is ScopeFreezeStatus.RESOLVED
        if resolved != (
            self.resolution_reason is not None
            and self.resolved_data_version is not None
        ):
            raise ValueError(
                "resolved freeze requires reason and resolved data version"
            )
        return self


class ScopeFreezePort(Protocol):
    def freeze(
        self,
        *,
        context: QualityContext,
        quality_fingerprint: str,
        data_version: str,
        observed_at: datetime,
    ) -> ScopeFreezeRecord: ...

    def active(self, affected_scope: str) -> ScopeFreezeRecord | None: ...

    def resolve(
        self,
        *,
        affected_scope: str,
        expected_freeze_version: int,
        resolved_data_version: str,
        reason: str,
    ) -> ScopeFreezeRecord: ...


class InMemoryScopeFreezeRepository:
    def __init__(self) -> None:
        self._records: dict[str, list[ScopeFreezeRecord]] = {}
        self._lock = Lock()

    def freeze(
        self,
        *,
        context: QualityContext,
        quality_fingerprint: str,
        data_version: str,
        observed_at: datetime,
    ) -> ScopeFreezeRecord:
        with self._lock:
            affected_scope = context.affected_scope
            records = self._records.setdefault(affected_scope, [])
            if (
                records
                and records[-1].status is ScopeFreezeStatus.ACTIVE
                and records[-1].quality_fingerprint == quality_fingerprint
            ):
                return records[-1]
            if records and records[-1].status is ScopeFreezeStatus.ACTIVE:
                version = records[-1].freeze_version + 1
            else:
                version = records[-1].freeze_version + 1 if records else 1
            record = ScopeFreezeRecord(
                affected_scope=affected_scope,
                quality_fingerprint=quality_fingerprint,
                data_version=data_version,
                freeze_version=version,
                status=ScopeFreezeStatus.ACTIVE,
                context=context,
                first_detected_at=observed_at,
            )
            records.append(record)
            return record

    def get(self, affected_scope: str) -> ScopeFreezeRecord | None:
        with self._lock:
            records = self._records.get(affected_scope, [])
            return records[-1] if records else None

    def active(self, affected_scope: str) -> ScopeFreezeRecord | None:
        record = self.get(affected_scope)
        if record is None or record.status is ScopeFreezeStatus.RESOLVED:
            return None
        return record

    def resolve(
        self,
        *,
        affected_scope: str,
        expected_freeze_version: int,
        resolved_data_version: str,
        reason: str,
    ) -> ScopeFreezeRecord:
        if not reason.strip():
            raise ValueError("freeze resolution requires a reason")
        with self._lock:
            records = self._records.get(affected_scope, [])
            if not records or records[-1].status is not ScopeFreezeStatus.ACTIVE:
                raise ValueError("scope has no active quality freeze")
            active = records[-1]
            if active.freeze_version != expected_freeze_version:
                raise ValueError("quality freeze version mismatch")
            if active.data_version == resolved_data_version:
                raise ValueError("quality freeze requires a new validated data version")
            resolved = active.model_copy(
                update={
                    "status": ScopeFreezeStatus.RESOLVED,
                    "resolution_reason": reason.strip(),
                    "resolved_data_version": resolved_data_version,
                }
            )
            records.append(resolved)
            return resolved


class QualityGate:
    def __init__(
        self,
        scope_freezer: ScopeFreezePort,
        *,
        capability_trade_eligible: bool = False,
    ) -> None:
        self._scope_freezer = scope_freezer
        self._capability_trade_eligible = capability_trade_eligible

    def evaluate(
        self,
        envelope: DataEnvelope[T],
        *,
        context: QualityContext,
        observed_at: datetime,
    ) -> QualityDecision:
        if observed_at.tzinfo is None:
            raise ValueError("quality evaluation time must be timezone-aware")
        _validate_evaluation_envelope(envelope, context)
        affected_scope = context.affected_scope
        diagnostics = list(envelope.diagnostics)
        diagnostics.extend(_envelope_contract_diagnostics(envelope, affected_scope))
        diagnostics.extend(_freshness_diagnostics(envelope.items, affected_scope))
        current_blocking = tuple(
            item for item in diagnostics if item.code in _BLOCKING_CODES
        )
        active = self._scope_freezer.active(affected_scope)
        if active is not None:
            if active.context != context:
                raise ValueError(
                    "quality request context does not match the active freeze"
                )
            diagnostics.append(
                diagnostic(
                    code=DiagnosticCode.UNRESOLVED_QUALITY_FREEZE,
                    scope=affected_scope,
                    message=(
                        f"quality freeze v{active.freeze_version} requires "
                        "explicit versioned resolution"
                    ),
                    endpoint=None,
                    details={"freeze_version": str(active.freeze_version)},
                )
            )
        blocking = tuple(item for item in diagnostics if item.code in _BLOCKING_CODES)
        defect_fingerprint = _diagnostic_fingerprint(_defect_diagnostics(diagnostics))
        data_version = _data_version(envelope)
        if current_blocking:
            active = self._scope_freezer.freeze(
                context=context,
                quality_fingerprint=defect_fingerprint,
                data_version=data_version,
                observed_at=observed_at,
            )
        material = "|".join(
            (
                QUALITY_POLICY_VERSION,
                affected_scope,
                active.quality_fingerprint
                if active is not None
                else defect_fingerprint,
            )
        )
        decision = QualityDecision(
            affected_scope=affected_scope,
            frozen=bool(blocking),
            trade_eligible=(not bool(blocking) and self._capability_trade_eligible),
            capability_trade_eligible=self._capability_trade_eligible,
            diagnostics=tuple(diagnostics),
            fingerprint=sha256(material.encode()).hexdigest(),
            active_freeze_version=(
                active.freeze_version if active is not None else None
            ),
            defect_detected_at=(
                active.first_detected_at if active is not None else None
            ),
        )
        return decision

    def resolve_clean_envelope(
        self,
        *,
        envelope: DataEnvelope[T],
        affected_scope: str,
        expected_freeze_version: int,
        reason: str,
    ) -> ScopeFreezeRecord:
        active = self._scope_freezer.active(affected_scope)
        if active is None:
            raise ValueError("scope has no active quality freeze")
        if active.context.affected_scope != affected_scope:
            raise ValueError("quality freeze scope binding mismatch")
        _validate_clean_envelope(envelope, active.context)
        diagnostics = [
            *envelope.diagnostics,
            *_envelope_contract_diagnostics(envelope, affected_scope),
            *_freshness_diagnostics(envelope.items, affected_scope),
        ]
        blocking = tuple(item for item in diagnostics if item.code in _BLOCKING_CODES)
        if blocking:
            raise ValueError(
                "quality freeze resolution requires a newly evaluated clean envelope"
            )
        return self._scope_freezer.resolve(
            affected_scope=affected_scope,
            expected_freeze_version=expected_freeze_version,
            resolved_data_version=_data_version(envelope),
            reason=reason,
        )


class DQTriggerRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_key: Literal["data_quality_review"]
    idempotency_key: str = Field(min_length=64, max_length=64)
    affected_scope: str = Field(min_length=1, max_length=160)
    policy_version: str = QUALITY_POLICY_VERSION
    diagnostic_fingerprints: tuple[str, ...]
    requested_at: datetime
    trade_eligible: Literal[False] = False
    recursive_trigger_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_requested_at(self) -> DQTriggerRequest:
        if self.requested_at.tzinfo is None:
            raise ValueError("requested_at must be timezone-aware")
        return self


class DQTriggerRepository(Protocol):
    def claim(self, idempotency_key: str) -> bool: ...

    def release(self, idempotency_key: str) -> None: ...


class DQWorkflowPort(Protocol):
    async def start(self, request: DQTriggerRequest) -> DQWorkflowReceipt: ...


class DQWorkflowReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_run_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=64, max_length=64)


class InMemoryDQTriggerRepository:
    """Thread-safe test/dev repository; production can inject a durable port."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = Lock()

    def claim(self, idempotency_key: str) -> bool:
        with self._lock:
            if idempotency_key in self._claimed:
                return False
            self._claimed.add(idempotency_key)
            return True

    def release(self, idempotency_key: str) -> None:
        with self._lock:
            self._claimed.discard(idempotency_key)


@dataclass(frozen=True)
class DQTriggerResult:
    started: bool
    idempotency_key: str | None
    workflow_run_id: str | None
    reason: str


class DQTrigger:
    def __init__(
        self,
        repository: DQTriggerRepository,
        workflow: DQWorkflowPort,
    ) -> None:
        self._repository = repository
        self._workflow = workflow

    async def trigger(
        self,
        decision: QualityDecision,
        *,
        source_workflow: str | None,
    ) -> DQTriggerResult:
        if not decision.frozen:
            return DQTriggerResult(
                False, None, None, "quality gate did not freeze scope"
            )
        if source_workflow == "data_quality_review":
            return DQTriggerResult(
                False, None, None, "recursive data-quality trigger is prohibited"
            )
        if not _defect_diagnostics(decision.diagnostics):
            return DQTriggerResult(
                False,
                None,
                None,
                "no new blocking defect requires a workflow trigger",
            )
        request = build_dq_trigger_request(
            decision,
            source_workflow=source_workflow,
        )
        if request is None:
            raise AssertionError("blocking defect must produce a DQ request")
        key = request.idempotency_key
        if not self._repository.claim(key):
            return DQTriggerResult(False, key, None, "duplicate trigger suppressed")
        try:
            receipt = await self._workflow.start(request)
        except Exception:
            self._repository.release(key)
            raise
        if receipt.idempotency_key != key:
            self._repository.release(key)
            raise ValueError("DQ workflow receipt idempotency key mismatch")
        return DQTriggerResult(
            True,
            key,
            receipt.workflow_run_id,
            "data-quality workflow started",
        )


def build_dq_trigger_request(
    decision: QualityDecision,
    *,
    source_workflow: str | None,
) -> DQTriggerRequest | None:
    if not decision.frozen or source_workflow == "data_quality_review":
        return None
    defects = _defect_diagnostics(decision.diagnostics)
    if not defects:
        return None
    if decision.defect_detected_at is None:
        raise ValueError("frozen defect decision lacks its first detection time")
    key = _trigger_key(decision)
    return DQTriggerRequest(
        workflow_key="data_quality_review",
        idempotency_key=key,
        affected_scope=decision.affected_scope,
        diagnostic_fingerprints=tuple(sorted(item.fingerprint for item in defects)),
        requested_at=decision.defect_detected_at,
    )


def _trigger_key(decision: QualityDecision) -> str:
    defect_diagnostics = _defect_diagnostics(decision.diagnostics)
    material = "|".join(
        (
            decision.affected_scope,
            decision.policy_version,
            *(
                sorted(item.fingerprint for item in defect_diagnostics)
                if defect_diagnostics
                else (decision.fingerprint,)
            ),
        )
    )
    return sha256(material.encode()).hexdigest()


def _freshness_diagnostics(
    items: Iterable[object], affected_scope: str
) -> tuple[DataDiagnostic, ...]:
    result: list[DataDiagnostic] = []
    for item in items:
        freshness = getattr(item, "freshness", None)
        source = getattr(item, "source", None)
        if freshness is None or source is None:
            continue
        if freshness.status is FreshnessStatus.CURRENT:
            continue
        result.append(
            diagnostic(
                code=DiagnosticCode.UNEXPECTED_MISSING,
                scope=affected_scope,
                message=(
                    f"market data freshness is {freshness.status.value}: "
                    f"{freshness.reason}"
                ),
                endpoint=source.endpoint,
                details={"freshness": freshness.status.value},
            )
        )
    return tuple(result)


def _envelope_contract_diagnostics(
    envelope: DataEnvelope[Any], affected_scope: str
) -> tuple[DataDiagnostic, ...]:
    messages: list[str] = []
    if envelope.items and envelope.empty_meaning.value != "not_empty":
        messages.append("non-empty envelope has an empty-data meaning")
    if not envelope.items and envelope.empty_meaning.value == "not_empty":
        messages.append("empty envelope is missing an explicit empty-data meaning")
    if (
        not envelope.items
        and envelope.empty_meaning.value == "unexpected_missing"
        and not any(
            item.empty_meaning.value == "unexpected_missing"
            for item in envelope.diagnostics
        )
    ):
        messages.append("unexpected-missing envelope lacks a matching diagnostic")
    return tuple(
        diagnostic(
            code=DiagnosticCode.ENVELOPE_CONTRACT,
            scope=affected_scope,
            message=message,
            endpoint=None,
        )
        for message in messages
    )


def _data_version(envelope: DataEnvelope[Any]) -> str:
    items = [_stable_item_content(item) for item in envelope.items]
    diagnostics = [
        {
            "code": item.code.value,
            "severity": item.severity.value,
            "scope": item.scope,
            "empty_meaning": item.empty_meaning.value,
            "retryable": item.retryable,
            "endpoint": item.endpoint,
            "details": item.details,
            "fingerprint": item.fingerprint,
        }
        for item in envelope.diagnostics
    ]
    material = {
        "items": items,
        "diagnostics": diagnostics,
        "empty_meaning": envelope.empty_meaning.value,
    }
    return sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _defect_diagnostics(
    diagnostics: Iterable[DataDiagnostic],
) -> tuple[DataDiagnostic, ...]:
    return tuple(
        item
        for item in diagnostics
        if item.code in _BLOCKING_CODES
        and item.code is not DiagnosticCode.UNRESOLVED_QUALITY_FREEZE
    )


def _diagnostic_fingerprint(
    diagnostics: Iterable[DataDiagnostic],
) -> str:
    return sha256(
        "|".join(sorted(item.fingerprint for item in diagnostics)).encode()
    ).hexdigest()


def _validate_evaluation_envelope(
    envelope: DataEnvelope[Any],
    context: QualityContext,
) -> None:
    for issue in envelope.diagnostics:
        if issue.scope != context.affected_scope:
            raise ValueError("quality diagnostic scope does not match request context")
        if (
            context.source_endpoint is not None
            and issue.endpoint is not None
            and issue.endpoint != context.source_endpoint
        ):
            raise ValueError("quality diagnostic source does not match request context")
    if envelope.items:
        _validate_items_against_context(envelope.items, context)


def _validate_clean_envelope(
    envelope: DataEnvelope[Any],
    context: QualityContext,
) -> None:
    if not envelope.items:
        raise ValueError(
            "quality freeze resolution clean envelope requires non-empty "
            "canonical normalized data"
        )
    if envelope.diagnostics:
        raise ValueError(
            "quality freeze resolution requires a diagnostic-free envelope"
        )
    _validate_items_against_context(envelope.items, context)


def _validate_items_against_context(
    items: Iterable[object],
    context: QualityContext,
) -> None:
    for item in items:
        category, scope, source = _normalized_item_identity(item)
        if scope != context.affected_scope:
            raise ValueError("normalized data scope does not match quality freeze")
        if category is not context.category:
            raise ValueError("normalized data category does not match quality freeze")
        if source.frequency is not context.frequency:
            raise ValueError("normalized data frequency does not match quality freeze")
        if source.provider != context.source_provider:
            raise ValueError("normalized data provider does not match quality freeze")
        if source.endpoint != context.source_endpoint:
            raise ValueError("normalized data endpoint does not match quality freeze")
        if (
            source.instrument_master_identity != context.instrument_master_identity
            or source.instrument_master_version != context.instrument_master_version
        ):
            raise ValueError(
                "normalized data instrument-master identity does not match quality freeze"
            )


def _normalized_item_identity(
    item: object,
) -> tuple[DataCategory, str, SourceStamp]:
    if isinstance(item, NormalizedSnapshot):
        return DataCategory.SNAPSHOT, item.instrument.symbol, item.source
    if isinstance(item, NormalizedBar):
        return (
            DataCategory.BAR,
            f"{item.instrument.symbol}:{item.source.frequency.value}",
            item.source,
        )
    if isinstance(item, NormalizedFact):
        return item.category, item.scope, item.source
    if isinstance(item, NormalizedMasterRecord):
        return DataCategory.MASTER, item.instrument.symbol, item.source
    if isinstance(item, NormalizedCalendarDay):
        return (
            DataCategory.CALENDAR,
            f"{item.market.value}:{item.trade_date}",
            item.source,
        )
    if isinstance(item, NormalizedIndexWeight):
        return DataCategory.FACTOR, item.index.symbol, item.source
    raise ValueError("quality resolution accepts only canonical normalized data")


def _stable_item_content(item: object) -> dict[str, Any]:
    if not isinstance(
        item,
        (
            NormalizedSnapshot,
            NormalizedBar,
            NormalizedFact,
            NormalizedMasterRecord,
            NormalizedCalendarDay,
            NormalizedIndexWeight,
        ),
    ):
        raise ValueError("data version accepts only canonical normalized data")
    payload: dict[str, Any] = item.model_dump(mode="json")
    source = payload.get("source")
    if isinstance(source, dict):
        source.pop("ingested_at", None)
    payload.pop("freshness", None)
    return payload


def default_quality_context(
    *,
    affected_scope: str,
    category: DataCategory,
    frequency: DataFrequency,
    source_endpoint: str | None,
) -> QualityContext:
    """Build a context bound to the bundled authoritative master."""

    return QualityContext(
        affected_scope=affected_scope,
        category=category,
        frequency=frequency,
        instrument_master_identity=DEFAULT_INSTRUMENT_MASTER_IDENTITY,
        instrument_master_version=DEFAULT_INSTRUMENT_MASTER_VERSION,
        source_endpoint=source_endpoint,
    )
