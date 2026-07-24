from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.evidence_routes import create_evidence_routes
from finance_god.application.evidence_service import EvidenceService

# Importing the ORM module registers the evidence table on ``Base`` before
# ``create_all`` runs; without it the evidence_bundles table is missing.
from finance_god.infrastructure.persistence import evidence_models  # noqa: F401
from finance_god.infrastructure.persistence.models import Base

OWNER = "server-user"
FIXED_NOW = datetime(2026, 7, 24, 2, 31, tzinfo=UTC)


async def _resolve_owner(_request) -> str:
    return OWNER


class _Clock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        current = self._now
        self._now = self._now + timedelta(seconds=1)
        return current


class _Ids:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def new_id(self, prefix: str) -> str:
        count = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = count
        return f"{prefix}-{count}"


def _fake_run(run_id: str = "fg-run-1") -> SimpleNamespace:
    """A duck-typed AgentRun exposing exactly the attributes we read."""
    claim_fact = SimpleNamespace(
        kind=SimpleNamespace(value="fact"),
        statement="600519 closed at 1680 on 2026-07-23.",
        author_agent_id="analyst-1",
        evidence_ids=["e1"],
        unknowns=[],
        invalidation_conditions=[],
    )
    claim_inference = SimpleNamespace(
        kind="inference",
        statement="Valuation appears stretched versus 5y median.",
        author_agent_id="analyst-2",
        evidence_ids=["e1"],
        unknowns=["forward earnings guidance unavailable"],
        invalidation_conditions=["a guidance revision above consensus"],
    )
    result = SimpleNamespace(
        agent_id="analyst-1",
        summary="Mixed signal: strong brand, rich valuation.",
        claims=[claim_fact, claim_inference],
        evidence=[
            SimpleNamespace(
                identifier="e1",
                source="PandaData market_bars 2026-07-23",
                excerpt="close=1680.0",
            )
        ],
    )
    plan = SimpleNamespace(
        assignments=[SimpleNamespace(agent_id="analyst-1", reason="equity coverage")],
        notices=[
            SimpleNamespace(
                agent_id="derivatives-1",
                reason="options data not authorized",
                missing_resources=["option_iv"],
                missing_authorizations=["derivatives"],
            )
        ],
    )
    return SimpleNamespace(run_id=run_id, plan=plan, results=[result])


class _Harness:
    def __init__(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
        asyncio.run(self._create_schema())
        self.clock = _Clock(FIXED_NOW)
        self.ids = _Ids()
        self.service = EvidenceService(
            session_factory=self.sessionmaker,
            clock=self.clock,
            ids=self.ids,
        )
        app = Starlette(
            routes=[
                Mount(
                    "/evidence",
                    routes=create_evidence_routes(
                        service_provider=lambda: self.service,
                        owner_resolver=_resolve_owner,
                    ),
                )
            ]
        )
        self.client = TestClient(app)

    async def _create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    def record_run(self, run) -> None:
        asyncio.run(
            self.service.record_agent_run(
                owner_id=OWNER, run=run, subject="600519 research"
            )
        )

    def record(self, **kwargs) -> None:
        asyncio.run(self.service.record(owner_id=OWNER, **kwargs))


def test_get_returns_normal_content_without_internal_or_nodes() -> None:
    harness = _Harness()
    harness.record_run(_fake_run())

    response = harness.client.get("/evidence/agent_run/fg-run-1")

    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == "normal"
    assert body["subject"] == "600519 research"
    assert [fact["statement"] for fact in body["facts"]] == [
        "600519 closed at 1680 on 2026-07-23."
    ]
    assert [inf["statement"] for inf in body["inferences"]] == [
        "Valuation appears stretched versus 5y median."
    ]
    assert body["unknowns"] == ["forward earnings guidance unavailable"]
    assert body["invalidation_conditions"] == ["a guidance revision above consensus"]
    assert body["sources"][0]["identifier"] == "e1"
    # Normal tier never exposes agent workflow nodes or internal traces.
    assert body["agent_nodes"] == []
    assert body["notices"] == []
    assert body["error_trace"] is None


def test_get_advanced_tier_includes_agent_nodes_and_notices() -> None:
    harness = _Harness()
    harness.record_run(_fake_run())

    response = harness.client.get("/evidence/agent_run/fg-run-1?tier=advanced")

    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == "advanced"
    assert body["agent_nodes"][0]["agent_id"] == "analyst-1"
    assert body["notices"][0]["missing_authorizations"] == ["derivatives"]
    # Counterpoints surface routing gaps as an explicit "other side".
    assert "options data not authorized" in body["counterpoints"]


def test_internal_tier_is_never_served_over_http() -> None:
    harness = _Harness()
    harness.record_run(_fake_run())

    response = harness.client.get("/evidence/agent_run/fg-run-1?tier=internal")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_TIER"


def test_get_missing_bundle_returns_explicit_404() -> None:
    harness = _Harness()

    response = harness.client.get("/evidence/agent_run/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_invalid_tier_is_rejected() -> None:
    harness = _Harness()
    harness.record_run(_fake_run())

    response = harness.client.get("/evidence/agent_run/fg-run-1?tier=mystery")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_lineage_returns_inputs_and_sources() -> None:
    harness = _Harness()
    harness.record(
        object_type="trade_plan",
        object_id="plan-1",
        version="2",
        subject="Rebalance plan",
        conclusion="Trim the single-asset concentration.",
        content={"facts": [], "inferences": [], "sources": []},
        lineage={
            "inputs": [
                {"object_type": "agent_run", "object_id": "fg-run-1", "version": "1"}
            ],
            "sources": [{"identifier": "e1", "source": "PandaData market_bars"}],
        },
    )

    response = harness.client.get("/evidence/trade_plan/plan-1/lineage?version=2")

    assert response.status_code == 200
    body = response.json()
    assert body["inputs"][0]["object_id"] == "fg-run-1"
    assert body["sources"][0]["identifier"] == "e1"


def test_versions_compare_reports_added_and_removed() -> None:
    harness = _Harness()
    common = {
        "object_type": "trade_plan",
        "object_id": "plan-1",
        "subject": "Rebalance plan",
    }
    harness.record(
        version="1",
        conclusion="v1",
        content={
            "facts": [{"kind": "fact", "statement": "cash is 12%"}],
            "inferences": [],
            "unknowns": ["fee schedule pending"],
        },
        **common,
    )
    harness.record(
        version="2",
        conclusion="v2",
        content={
            "facts": [{"kind": "fact", "statement": "cash is 8%"}],
            "inferences": [],
            "unknowns": [],
        },
        **common,
    )

    response = harness.client.get(
        "/evidence/trade_plan/plan-1/versions/compare?a=1&b=2"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["base"]["version"] == "1"
    assert body["other"]["version"] == "2"
    diffs = {diff["field"]: diff for diff in body["diffs"]}
    assert "cash is 8%" in diffs["facts"]["added"]
    assert "cash is 12%" in diffs["facts"]["removed"]
    assert "fee schedule pending" in diffs["unknowns"]["removed"]


def test_compare_missing_query_parameter_is_rejected() -> None:
    harness = _Harness()
    harness.record_run(_fake_run())

    response = harness.client.get("/evidence/agent_run/fg-run-1/versions/compare?a=1")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_export_returns_version_catalog_and_bundle() -> None:
    harness = _Harness()
    harness.record_run(_fake_run())

    response = harness.client.post(
        "/evidence/agent_run/fg-run-1/export", json={"tier": "advanced"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object_id"] == "fg-run-1"
    assert body["tier"] == "advanced"
    assert body["exported_at"] is not None
    assert [item["version"] for item in body["versions"]] == ["1"]
    assert body["bundle"]["agent_nodes"][0]["agent_id"] == "analyst-1"


def test_record_agent_run_is_idempotent_per_version() -> None:
    harness = _Harness()
    run = _fake_run()
    harness.record_run(run)
    # Recording the same run again must not create a second bundle.
    harness.record_run(run)

    response = harness.client.post(
        "/evidence/agent_run/fg-run-1/export", json={"tier": "normal"}
    )

    assert response.status_code == 200
    assert len(response.json()["versions"]) == 1
