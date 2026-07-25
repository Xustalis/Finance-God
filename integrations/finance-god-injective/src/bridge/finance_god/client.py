from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


class FinanceGodError(RuntimeError):
    """A Finance-God read failed; callers must not treat it as a successful sync."""


@dataclass(frozen=True, slots=True)
class SourceSnapshotProjection:
    plan_id: str
    plan_version: int
    plan_status: str
    expires_at: datetime | None
    audit_reference: str | None
    draft_id: str | None
    draft_status: str | None
    draft_confirmed: bool | None
    normalized_hash: str
    projection: dict[str, Any]
    usage: str = "context_only"
    asset_domain: str = "non_executable_asset_domain"


def _pick(data: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinanceGodError("Finance-God returned an invalid expiry timestamp") from exc
    if parsed.tzinfo is None:
        raise FinanceGodError("Finance-God expiry timestamp must include a timezone")
    return parsed.astimezone(UTC)


def project_snapshot(
    plan_id: str,
    plan: Mapping[str, Any],
    draft: Mapping[str, Any] | None,
) -> SourceSnapshotProjection:
    """Construct the deliberately small auditable projection; no response is retained."""
    version = _pick(plan, "version", "revision")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise FinanceGodError("Finance-God plan is missing a positive version")
    status = _pick(plan, "status")
    if not isinstance(status, str) or not status.strip():
        raise FinanceGodError("Finance-God plan is missing a status")
    returned_plan_id = _pick(plan, "plan_id", "planId")
    if returned_plan_id != plan_id:
        raise FinanceGodError("Finance-God returned a different plan id")
    draft_id = _pick(plan, "draft_id", "draftId")
    if draft_id is not None and not isinstance(draft_id, str):
        raise FinanceGodError("Finance-God plan draft id is invalid")
    audit_reference = _pick(plan, "audit_reference", "auditReference", "id")
    if isinstance(audit_reference, Mapping):
        audit_reference = _pick(audit_reference, "audit_id", "auditId")
    if audit_reference is not None and not isinstance(audit_reference, str):
        audit_reference = None
    confirmed = None
    draft_status = None
    if draft is not None:
        draft_object = _pick(draft, "draft")
        if not isinstance(draft_object, Mapping):
            draft_object = draft
        draft_status = _pick(draft_object, "status")
        if draft_status is not None and not isinstance(draft_status, str):
            draft_status = None
        confirmed_at = _pick(draft, "confirmed_at", "confirmedAt")
        confirmed = confirmed_at is not None and draft_status == "confirmed"
    projection = {
        "plan_id": plan_id,
        "plan_version": version,
        "plan_status": status.strip(),
        "expires_at": _pick(plan, "expires_at", "expiresAt"),
        "audit_reference": audit_reference,
        "draft_id": draft_id,
        "draft_status": draft_status,
        "draft_confirmed": confirmed,
        "classification": "context_only",
        "asset_domain": "non_executable_asset_domain",
    }
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return SourceSnapshotProjection(
        plan_id=plan_id,
        plan_version=version,
        plan_status=status.strip(),
        expires_at=_parse_time(projection["expires_at"]),
        audit_reference=audit_reference,
        draft_id=draft_id,
        draft_status=draft_status,
        draft_confirmed=confirmed,
        normalized_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        projection=projection,
    )


class FinanceGodClient:
    """The only permitted Finance-God calls are the two documented GET endpoints."""

    def __init__(
        self, base_url: str, read_token: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = read_token
        self._client = client

    async def fetch_snapshot(self, plan_id: str) -> SourceSnapshotProjection:
        if not plan_id.strip():
            raise FinanceGodError("plan_id is required")
        headers = {"Authorization": f"Bearer {self._token}"}
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=10.0)
        try:
            page = await self._get_json(
                client,
                f"/api/finance/trade-plans/{plan_id}",
                headers,
            )
            plan = _pick(page, "object")
            if not isinstance(plan, Mapping):
                raise FinanceGodError("Finance-God plan response is missing object")
            draft_links = _pick(page, "draft_links", "draftLinks") or []
            if not isinstance(draft_links, list):
                raise FinanceGodError("Finance-God draft_links must be an array")
            if len(draft_links) > 1:
                raise FinanceGodError("v1 source snapshots support one linked Finance-God draft")
            draft_id = None
            if draft_links:
                link = draft_links[0]
                if not isinstance(link, Mapping):
                    raise FinanceGodError("Finance-God draft link is invalid")
                draft_id = _pick(link, "draft_id", "draftId")
                if not isinstance(draft_id, str) or not draft_id:
                    raise FinanceGodError("Finance-God draft link has no draft id")
                plan = {**plan, "draft_id": draft_id}
            draft = None
            if isinstance(draft_id, str) and draft_id:
                draft = await self._get_json(
                    client,
                    f"/api/finance/simulation/drafts/{draft_id}",
                    headers,
                )
            return project_snapshot(plan_id, plan, draft)
        finally:
            if own_client:
                await client.aclose()

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        headers: dict[str, str],
    ) -> Mapping[str, Any]:
        try:
            response = await client.get(f"{self._base_url}{path}", headers=headers)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FinanceGodError(f"Finance-God read failed for {path}: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise FinanceGodError(f"Finance-God returned a non-object payload for {path}")
        return payload
