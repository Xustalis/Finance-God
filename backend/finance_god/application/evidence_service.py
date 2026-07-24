"""Structured evidence persistence and the T10 process/evidence contract.

Evidence bundles capture the immutable "how we got here" behind a produced
object version (agent run, trade plan, order draft): facts, inferences,
counterpoints, unknowns, invalidation conditions, sources with timestamps
and the agent nodes that ran. Bundles are never fabricated: they only mirror
outputs that a runtime actually produced, keyed by ``(object_type,
object_id, version)`` so the process history stays auditable.

Three access tiers govern what a reader may see:
- ``normal``   read-only conclusion content (no internal error traces);
- ``advanced`` adds the agent workflow nodes and routing notices;
- ``internal`` adds the raw error trace for operators.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.domain import ConcurrentCommandConflict
from finance_god.infrastructure.persistence.evidence_repository import StoredEvidence
from finance_god.infrastructure.persistence.evidence_uow import EvidenceUnitOfWork


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self, prefix: str) -> str: ...


class EvidenceTier(str, Enum):
    NORMAL = "normal"
    ADVANCED = "advanced"
    INTERNAL = "internal"

    def allows_nodes(self) -> bool:
        return self in {EvidenceTier.ADVANCED, EvidenceTier.INTERNAL}

    def allows_internal(self) -> bool:
        return self is EvidenceTier.INTERNAL


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceClaimView(StrictModel):
    kind: str
    statement: str
    author_agent_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()


class EvidenceSourceView(StrictModel):
    identifier: str
    source: str
    excerpt: str | None = None


class EvidenceNodeView(StrictModel):
    agent_id: str
    reason: str | None = None


class EvidenceNoticeView(StrictModel):
    agent_id: str
    reason: str
    missing_resources: tuple[str, ...] = ()
    missing_authorizations: tuple[str, ...] = ()


class EvidenceView(StrictModel):
    """Ordered, tier-projected evidence bundle for the read-only drawer."""

    object_type: str
    object_id: str
    version: str
    subject: str
    conclusion: str | None
    provider: str
    generated_at: datetime
    tier: EvidenceTier
    facts: tuple[EvidenceClaimView, ...]
    inferences: tuple[EvidenceClaimView, ...]
    counterpoints: tuple[str, ...]
    unknowns: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    sources: tuple[EvidenceSourceView, ...]
    agent_nodes: tuple[EvidenceNodeView, ...] = ()
    notices: tuple[EvidenceNoticeView, ...] = ()
    error_trace: str | None = None


class EvidenceLineageInput(StrictModel):
    object_type: str
    object_id: str
    version: str


class EvidenceLineageView(StrictModel):
    object_type: str
    object_id: str
    version: str
    provider: str
    generated_at: datetime
    inputs: tuple[EvidenceLineageInput, ...]
    sources: tuple[EvidenceSourceView, ...]


class EvidenceVersionSummary(StrictModel):
    version: str
    subject: str
    conclusion: str | None
    provider: str
    generated_at: datetime


class EvidenceFieldDiff(StrictModel):
    field: str
    added: tuple[str, ...]
    removed: tuple[str, ...]


class EvidenceCompareView(StrictModel):
    object_type: str
    object_id: str
    base: EvidenceVersionSummary
    other: EvidenceVersionSummary
    diffs: tuple[EvidenceFieldDiff, ...]


class EvidenceExportView(StrictModel):
    object_type: str
    object_id: str
    exported_at: datetime
    tier: EvidenceTier
    versions: tuple[EvidenceVersionSummary, ...]
    bundle: EvidenceView


def evidence_content_from_agent_run(run: Any) -> dict[str, Any]:
    """Extract a structured evidence bundle from an ``AgentRun`` (duck-typed).

    Reads only attributes the research runtime already produced; it never
    invents claims or sources. Kept as a pure function so tests do not need
    the vendored runtime installed.
    """

    facts: list[dict[str, Any]] = []
    inferences: list[dict[str, Any]] = []
    unknowns: list[str] = []
    invalidations: list[str] = []
    sources: list[dict[str, Any]] = []
    seen_sources: set[str] = set()

    for result in getattr(run, "results", []) or []:
        for claim in getattr(result, "claims", []) or []:
            kind = _enum_value(getattr(claim, "kind", "inference"))
            entry = {
                "kind": kind,
                "statement": getattr(claim, "statement", ""),
                "author_agent_id": getattr(claim, "author_agent_id", None),
                "evidence_ids": list(getattr(claim, "evidence_ids", []) or []),
                "unknowns": list(getattr(claim, "unknowns", []) or []),
                "invalidation_conditions": list(
                    getattr(claim, "invalidation_conditions", []) or []
                ),
            }
            if kind == "fact":
                facts.append(entry)
            else:
                inferences.append(entry)
            unknowns.extend(entry["unknowns"])
            invalidations.extend(entry["invalidation_conditions"])
        for record in getattr(result, "evidence", []) or []:
            identifier = getattr(record, "identifier", "")
            if identifier in seen_sources:
                continue
            seen_sources.add(identifier)
            sources.append(
                {
                    "identifier": identifier,
                    "source": getattr(record, "source", ""),
                    "excerpt": getattr(record, "excerpt", None),
                }
            )

    plan = getattr(run, "plan", None)
    agent_nodes = [
        {"agent_id": getattr(a, "agent_id", ""), "reason": getattr(a, "reason", None)}
        for a in getattr(plan, "assignments", []) or []
    ]
    notices = [
        {
            "agent_id": getattr(n, "agent_id", ""),
            "reason": getattr(n, "reason", ""),
            "missing_resources": list(getattr(n, "missing_resources", []) or []),
            "missing_authorizations": list(
                getattr(n, "missing_authorizations", []) or []
            ),
        }
        for n in getattr(plan, "notices", []) or []
    ]
    counterpoints = [notice["reason"] for notice in notices if notice["reason"]]

    return {
        "facts": facts,
        "inferences": inferences,
        "unknowns": _dedupe(unknowns),
        "counterpoints": _dedupe(counterpoints),
        "invalidation_conditions": _dedupe(invalidations),
        "sources": sources,
        "agent_nodes": agent_nodes,
        "notices": notices,
    }


def _agent_run_conclusion(run: Any) -> str | None:
    for result in getattr(run, "results", []) or []:
        summary = getattr(result, "summary", None)
        if summary:
            return str(summary)[:2000]
    return None


class EvidenceService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession],
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._ids = ids

    async def record(
        self,
        *,
        owner_id: str,
        object_type: str,
        object_id: str,
        version: str,
        subject: str,
        conclusion: str | None,
        content: dict[str, Any],
        lineage: dict[str, Any] | None = None,
        error_trace: str | None = None,
        provider: str = "multi-agent-runtime",
        generated_at: datetime | None = None,
    ) -> StoredEvidence:
        """Persist an immutable evidence bundle; idempotent per object version."""
        now = self._clock.now()
        stored = StoredEvidence(
            evidence_id=self._ids.new_id("evidence"),
            owner_user_id=owner_id,
            object_type=object_type,
            object_id=object_id,
            version=version,
            subject=subject[:500],
            conclusion=conclusion,
            content=content,
            lineage=lineage or {"inputs": [], "sources": content.get("sources", [])},
            error_trace=error_trace,
            provider=provider,
            generated_at=generated_at or now,
            created_at=now,
        )
        async with EvidenceUnitOfWork(self._session_factory) as uow:
            existing = await uow.evidence.get_exact(
                owner_id, object_type, object_id, version
            )
            if existing is not None:
                return existing
            try:
                await uow.evidence.insert(stored)
            except ConcurrentCommandConflict:
                pass
            await uow.commit()
        async with EvidenceUnitOfWork(self._session_factory) as uow:
            persisted = await uow.evidence.get_exact(
                owner_id, object_type, object_id, version
            )
        return persisted if persisted is not None else stored

    async def record_agent_run(
        self,
        *,
        owner_id: str,
        run: Any,
        subject: str,
        object_type: str = "agent_run",
        object_id: str | None = None,
        version: str = "1",
    ) -> StoredEvidence:
        content = evidence_content_from_agent_run(run)
        lineage = {"inputs": [], "sources": content["sources"]}
        return await self.record(
            owner_id=owner_id,
            object_type=object_type,
            object_id=object_id or getattr(run, "run_id", "unknown"),
            version=version,
            subject=subject,
            conclusion=_agent_run_conclusion(run),
            content=content,
            lineage=lineage,
        )

    async def get(
        self,
        *,
        owner_id: str,
        object_type: str,
        object_id: str,
        version: str | None = None,
        tier: EvidenceTier = EvidenceTier.NORMAL,
    ) -> EvidenceView:
        stored = await self._load(owner_id, object_type, object_id, version)
        return _view(stored, tier)

    async def lineage(
        self,
        *,
        owner_id: str,
        object_type: str,
        object_id: str,
        version: str | None = None,
    ) -> EvidenceLineageView:
        stored = await self._load(owner_id, object_type, object_id, version)
        raw_inputs = stored.lineage.get("inputs", []) if stored.lineage else []
        raw_sources = stored.lineage.get("sources", []) if stored.lineage else []
        return EvidenceLineageView(
            object_type=stored.object_type,
            object_id=stored.object_id,
            version=stored.version,
            provider=stored.provider,
            generated_at=stored.generated_at,
            inputs=tuple(
                EvidenceLineageInput(
                    object_type=item.get("object_type", ""),
                    object_id=item.get("object_id", ""),
                    version=str(item.get("version", "")),
                )
                for item in raw_inputs
            ),
            sources=tuple(
                EvidenceSourceView(
                    identifier=item.get("identifier", ""),
                    source=item.get("source", ""),
                    excerpt=item.get("excerpt"),
                )
                for item in raw_sources
            ),
        )

    async def compare(
        self,
        *,
        owner_id: str,
        object_type: str,
        object_id: str,
        version_a: str,
        version_b: str,
    ) -> EvidenceCompareView:
        base = await self._load(owner_id, object_type, object_id, version_a)
        other = await self._load(owner_id, object_type, object_id, version_b)
        return EvidenceCompareView(
            object_type=object_type,
            object_id=object_id,
            base=_summary(base),
            other=_summary(other),
            diffs=_diffs(base, other),
        )

    async def export(
        self,
        *,
        owner_id: str,
        object_type: str,
        object_id: str,
        version: str | None = None,
        tier: EvidenceTier = EvidenceTier.NORMAL,
    ) -> EvidenceExportView:
        async with EvidenceUnitOfWork(self._session_factory) as uow:
            history = await uow.evidence.versions(owner_id, object_type, object_id)
            if not history:
                raise LookupError("no evidence exists for this object")
            if version is None:
                target = history[-1]
            else:
                target = next(
                    (item for item in history if item.version == version), None
                )
                if target is None:
                    raise LookupError("the requested evidence version does not exist")
        return EvidenceExportView(
            object_type=object_type,
            object_id=object_id,
            exported_at=self._clock.now(),
            tier=tier,
            versions=tuple(_summary(item) for item in history),
            bundle=_view(target, tier),
        )

    async def _load(
        self, owner_id: str, object_type: str, object_id: str, version: str | None
    ) -> StoredEvidence:
        async with EvidenceUnitOfWork(self._session_factory) as uow:
            if version is None:
                stored = await uow.evidence.get_latest(owner_id, object_type, object_id)
            else:
                stored = await uow.evidence.get_exact(
                    owner_id, object_type, object_id, version
                )
        if stored is None:
            raise LookupError("the requested evidence bundle does not exist")
        return stored


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _claims(raw: list[dict[str, Any]]) -> tuple[EvidenceClaimView, ...]:
    return tuple(
        EvidenceClaimView(
            kind=item.get("kind", "inference"),
            statement=item.get("statement", ""),
            author_agent_id=item.get("author_agent_id"),
            evidence_ids=tuple(item.get("evidence_ids", []) or []),
            unknowns=tuple(item.get("unknowns", []) or []),
            invalidation_conditions=tuple(
                item.get("invalidation_conditions", []) or []
            ),
        )
        for item in raw
    )


def _view(stored: StoredEvidence, tier: EvidenceTier) -> EvidenceView:
    content = stored.content or {}
    nodes: tuple[EvidenceNodeView, ...] = ()
    notices: tuple[EvidenceNoticeView, ...] = ()
    if tier.allows_nodes():
        nodes = tuple(
            EvidenceNodeView(
                agent_id=item.get("agent_id", ""), reason=item.get("reason")
            )
            for item in content.get("agent_nodes", [])
        )
        notices = tuple(
            EvidenceNoticeView(
                agent_id=item.get("agent_id", ""),
                reason=item.get("reason", ""),
                missing_resources=tuple(item.get("missing_resources", []) or []),
                missing_authorizations=tuple(
                    item.get("missing_authorizations", []) or []
                ),
            )
            for item in content.get("notices", [])
        )
    return EvidenceView(
        object_type=stored.object_type,
        object_id=stored.object_id,
        version=stored.version,
        subject=stored.subject,
        conclusion=stored.conclusion,
        provider=stored.provider,
        generated_at=stored.generated_at,
        tier=tier,
        facts=_claims(content.get("facts", [])),
        inferences=_claims(content.get("inferences", [])),
        counterpoints=tuple(content.get("counterpoints", [])),
        unknowns=tuple(content.get("unknowns", [])),
        invalidation_conditions=tuple(content.get("invalidation_conditions", [])),
        sources=tuple(
            EvidenceSourceView(
                identifier=item.get("identifier", ""),
                source=item.get("source", ""),
                excerpt=item.get("excerpt"),
            )
            for item in content.get("sources", [])
        ),
        agent_nodes=nodes,
        notices=notices,
        error_trace=stored.error_trace if tier.allows_internal() else None,
    )


def _summary(stored: StoredEvidence) -> EvidenceVersionSummary:
    return EvidenceVersionSummary(
        version=stored.version,
        subject=stored.subject,
        conclusion=stored.conclusion,
        provider=stored.provider,
        generated_at=stored.generated_at,
    )


def _statements(raw: list[dict[str, Any]]) -> set[str]:
    return {item.get("statement", "") for item in raw if item.get("statement")}


def _diffs(base: StoredEvidence, other: StoredEvidence) -> tuple[EvidenceFieldDiff, ...]:
    diffs: list[EvidenceFieldDiff] = []
    base_content = base.content or {}
    other_content = other.content or {}
    for field, extractor in (
        ("facts", _statements),
        ("inferences", _statements),
    ):
        base_set = extractor(base_content.get(field, []))
        other_set = extractor(other_content.get(field, []))
        added = tuple(sorted(other_set - base_set))
        removed = tuple(sorted(base_set - other_set))
        if added or removed:
            diffs.append(EvidenceFieldDiff(field=field, added=added, removed=removed))
    for field in ("unknowns", "counterpoints", "invalidation_conditions"):
        base_set = set(base_content.get(field, []))
        other_set = set(other_content.get(field, []))
        added = tuple(sorted(other_set - base_set))
        removed = tuple(sorted(base_set - other_set))
        if added or removed:
            diffs.append(EvidenceFieldDiff(field=field, added=added, removed=removed))
    return tuple(diffs)
