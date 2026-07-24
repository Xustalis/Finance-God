"""Deterministic quality gate and idempotent data-quality workflow trigger."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from threading import Lock
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    DataDiagnostic,
    DataEnvelope,
    DiagnosticCode,
    FreshnessStatus,
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

    @model_validator(mode="after")
    def enforce_eligibility_invariant(self) -> QualityDecision:
        if self.frozen and self.trade_eligible:
            raise ValueError("frozen quality scope cannot be trade eligible")
        if self.trade_eligible and not self.capability_trade_eligible:
            raise ValueError("capability-ineligible data cannot become trade eligible")
        return self


class ScopeFreezeStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"


class ScopeFreezeRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    affected_scope: str = Field(min_length=1, max_length=160)
    quality_fingerprint: str = Field(min_length=64, max_length=64)
    data_version: str = Field(min_length=64, max_length=64)
    freeze_version: int = Field(ge=1)
    status: ScopeFreezeStatus
    policy_version: str = QUALITY_POLICY_VERSION
    resolution_reason: str | None = Field(default=None, min_length=1, max_length=240)
    resolved_data_version: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def enforce_resolution_state(self) -> ScopeFreezeRecord:
        resolved = self.status is ScopeFreezeStatus.RESOLVED
        if resolved != (
            self.resolution_reason is not None
            and self.resolved_data_version is not None
        ):
            raise ValueError("resolved freeze requires reason and resolved data version")
        return self


class ScopeFreezePort(Protocol):
    def freeze(
        self,
        *,
        affected_scope: str,
        quality_fingerprint: str,
        data_version: str,
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
        affected_scope: str,
        quality_fingerprint: str,
        data_version: str,
    ) -> ScopeFreezeRecord:
        with self._lock:
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
                raise ValueError(
                    "quality freeze requires a new validated data version"
                )
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
        affected_scope: str,
    ) -> QualityDecision:
        diagnostics = list(envelope.diagnostics)
        diagnostics.extend(
            _envelope_contract_diagnostics(envelope, affected_scope)
        )
        diagnostics.extend(_freshness_diagnostics(envelope.items, affected_scope))
        current_blocking = tuple(
            item for item in diagnostics if item.code in _BLOCKING_CODES
        )
        active = self._scope_freezer.active(affected_scope)
        if active is not None:
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
        blocking = tuple(
            item for item in diagnostics if item.code in _BLOCKING_CODES
        )
        material = "|".join(
            (
                QUALITY_POLICY_VERSION,
                affected_scope,
                *(sorted(item.fingerprint for item in blocking)),
            )
        )
        data_version = _data_version(envelope)
        if current_blocking:
            active = self._scope_freezer.freeze(
                affected_scope=affected_scope,
                quality_fingerprint=sha256(
                    "|".join(
                        sorted(item.fingerprint for item in current_blocking)
                    ).encode()
                ).hexdigest(),
                data_version=data_version,
            )
        decision = QualityDecision(
            affected_scope=affected_scope,
            frozen=bool(blocking),
            trade_eligible=(
                not bool(blocking) and self._capability_trade_eligible
            ),
            capability_trade_eligible=self._capability_trade_eligible,
            diagnostics=tuple(diagnostics),
            fingerprint=sha256(material.encode()).hexdigest(),
            active_freeze_version=(
                active.freeze_version if active is not None else None
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
        diagnostics = [
            *envelope.diagnostics,
            *_envelope_contract_diagnostics(envelope, affected_scope),
            *_freshness_diagnostics(envelope.items, affected_scope),
        ]
        blocking = tuple(
            item for item in diagnostics if item.code in _BLOCKING_CODES
        )
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
    trade_eligible: Literal[False] = False
    recursive_trigger_allowed: Literal[False] = False


class DQTriggerRepository(Protocol):
    def claim(self, idempotency_key: str) -> bool: ...

    def release(self, idempotency_key: str) -> None: ...


class DQWorkflowPort(Protocol):
    def start(self, request: DQTriggerRequest) -> str: ...


class AuditedDQWorkflowPort:
    """Thread-safe in-process workflow request audit for server composition."""

    def __init__(self) -> None:
        self._requests: dict[str, DQTriggerRequest] = {}
        self._lock = Lock()

    def start(self, request: DQTriggerRequest) -> str:
        with self._lock:
            existing = self._requests.get(request.idempotency_key)
            if existing is not None and existing != request:
                raise ValueError("DQ workflow idempotency payload conflict")
            self._requests[request.idempotency_key] = request
        return f"dq-{request.idempotency_key[:24]}"

    def list_requests(self) -> tuple[DQTriggerRequest, ...]:
        with self._lock:
            return tuple(self._requests[key] for key in sorted(self._requests))


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

    def trigger(
        self,
        decision: QualityDecision,
        *,
        source_workflow: str | None,
    ) -> DQTriggerResult:
        if not decision.frozen:
            return DQTriggerResult(False, None, None, "quality gate did not freeze scope")
        if source_workflow == "data_quality_review":
            return DQTriggerResult(
                False, None, None, "recursive data-quality trigger is prohibited"
            )
        key = _trigger_key(decision)
        if not self._repository.claim(key):
            return DQTriggerResult(False, key, None, "duplicate trigger suppressed")
        request = DQTriggerRequest(
            workflow_key="data_quality_review",
            idempotency_key=key,
            affected_scope=decision.affected_scope,
            diagnostic_fingerprints=tuple(
                sorted(item.fingerprint for item in decision.diagnostics)
            ),
        )
        try:
            run_id = self._workflow.start(request)
        except Exception:
            self._repository.release(key)
            raise
        if not run_id.strip():
            self._repository.release(key)
            raise ValueError("DQ workflow port returned a blank run id")
        return DQTriggerResult(True, key, run_id, "data-quality workflow started")


def _trigger_key(decision: QualityDecision) -> str:
    material = "|".join(
        (
            decision.affected_scope,
            decision.policy_version,
            *(sorted(item.fingerprint for item in decision.diagnostics)),
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
        messages.append(
            "unexpected-missing envelope lacks a matching diagnostic"
        )
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
    items = [
        (
            item.model_dump(mode="json")
            if hasattr(item, "model_dump")
            else repr(item)
        )
        for item in envelope.items
    ]
    diagnostics = [
        item.model_dump(mode="json")
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
