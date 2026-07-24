from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.trade_plan_routes import create_trade_plan_routes
from finance_god.application.candidate_service import Candidate, CandidateResponse
from finance_god.application.portfolio_query import PortfolioPosition, PortfolioView
from finance_god.application.trade_plan_service import TradePlanService
from finance_god.execution import DraftMode

# Importing the ORM module registers the trade-plan tables on ``Base`` before
# ``create_all`` runs; without it the versions/draft-link tables are missing.
from finance_god.infrastructure.persistence import trade_plan_models  # noqa: F401
from finance_god.infrastructure.persistence.models import Base
from finance_god.market_data.service import MarketQuote, QuoteBatch

FIXED_NOW = datetime(2026, 7, 24, 2, 31, tzinfo=UTC)


async def _resolve_owner(_request) -> str:
    return "server-user"


class _Clock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        # Advance monotonically so successive versions get strictly increasing
        # audit timestamps, mirroring a real wall clock.
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


class _Portfolio:
    def __init__(self, view: PortfolioView) -> None:
        self._view = view

    async def positions(self, *, owner_id: str) -> PortfolioView:
        return self._view


class _Candidates:
    def __init__(self, response: CandidateResponse) -> None:
        self._response = response

    async def candidates(
        self, *, owner_id: str, now: datetime, ignored: dict[str, str] | None = None
    ) -> CandidateResponse:
        return self._response


class _Drafts:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_order_draft(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        index = len(self.calls)
        return SimpleNamespace(
            draft=SimpleNamespace(draft_id=f"draft-{index}", revision=1)
        )


def _quote(symbol: str, *, freshness: str = "fresh") -> MarketQuote:
    return MarketQuote(
        symbol=symbol,
        name=f"{symbol} name",
        asset_type="stock",
        market="CN",
        currency="CNY",
        last=Decimal("10.00"),
        open=Decimal("10.00"),
        high=Decimal("10.10"),
        low=Decimal("9.95"),
        previous_close=Decimal("10.00"),
        change=Decimal("0"),
        change_percent=Decimal("0"),
        volume=Decimal("1000000"),
        amount=Decimal("2000000000"),
        provider="PandaData",
        provider_time="2026-07-24T10:31:00+08:00",
        retrieved_at=FIXED_NOW,
        frequency="realtime",
        freshness=freshness,
        market_status="open",
        source_endpoint="quotes",
        capability_version="v1",
        instrument_master_identity="im",
        instrument_master_version="1",
    )


def _quote_batch(symbols: list[str], *, freshness: str = "fresh") -> QuoteBatch:
    return QuoteBatch(
        requested_at=FIXED_NOW,
        cache_hit=False,
        quotes=tuple(_quote(symbol, freshness=freshness) for symbol in symbols),
        errors={},
    )


def _candidate(instrument_id: str, *, tradable: bool = True) -> Candidate:
    return Candidate(
        instrument_id=instrument_id,
        symbol=instrument_id,
        name=f"{instrument_id} name",
        asset_type="stock",
        market="CN",
        currency="CNY",
        direction="equities",
        direction_label="权益股票",
        purpose="补充权益方向的核心持仓。",
        dimensions=(),
        tradable=tradable,
    )


def _position(instrument_id: str, *, cost: Decimal, quantity: Decimal) -> PortfolioPosition:
    return PortfolioPosition(
        instrument_id=instrument_id,
        currency="CNY",
        quantity=quantity,
        settled_quantity=quantity,
        frozen_quantity=Decimal("0"),
        available_quantity=quantity,
        cost_basis_rmb=cost,
        average_cost_rmb=(cost / quantity) if quantity > 0 else None,
        realized_pnl_rmb=Decimal("0"),
        revision=1,
    )


def _portfolio_view(positions: tuple[PortfolioPosition, ...]) -> PortfolioView:
    return PortfolioView(
        account_id="sim-account-1",
        owner_id="server-user",
        as_of=FIXED_NOW,
        rule_version="sim-rules-v1",
        positions=positions,
        realized_pnl_rmb=Decimal("0"),
    )


class _Harness:
    def __init__(self, tmp_path, *, portfolio, candidates, quotes_freshness="fresh"):
        self.clock = _Clock(FIXED_NOW)
        self.ids = _Ids()
        self.drafts = _Drafts()
        self._freshness = quotes_freshness
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'trade-plan-api.db'}"
        self.engine = create_async_engine(database_url)
        session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )
        asyncio.run(self._create_schema())

        async def quotes(symbols: list[str]) -> QuoteBatch:
            return _quote_batch(symbols, freshness=self._freshness)

        def provider() -> TradePlanService:
            return TradePlanService(
                session_factory=session_factory,
                clock=self.clock,
                ids=self.ids,
                candidates=_Candidates(candidates),
                portfolio=_Portfolio(portfolio),
                quotes_provider=quotes,
                drafts=self.drafts,
            )

        self.app = Starlette(
            routes=[
                Mount(
                    "/trade-plans",
                    routes=create_trade_plan_routes(
                        service_provider=provider,
                        owner_resolver=_resolve_owner,
                    ),
                )
            ]
        )

    async def _create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    def dispose(self) -> None:
        asyncio.run(self.engine.dispose())


def _candidate_response(*candidates: Candidate) -> CandidateResponse:
    return CandidateResponse(
        generated_at=FIXED_NOW,
        rule_version="candidate-rules-v1",
        purpose_summary="方向候选池。",
        candidates=candidates,
    )


def test_create_from_candidate_produces_pending_review_plan(tmp_path) -> None:
    harness = _Harness(
        tmp_path,
        portfolio=_portfolio_view(()),
        candidates=_candidate_response(_candidate("000001.SZ")),
    )
    try:
        with TestClient(harness.app) as client:
            created = client.post(
                "/trade-plans/from-candidate",
                json={"instrument_id": "000001.SZ"},
                headers={"idempotency-key": "cand-1"},
            )
            assert created.status_code == 201
            body = created.json()
            assert body["object"]["status"] == "pending_review"
            assert body["object"]["revision"] == 1
            assert body["source_type"] == "candidate"
            assert body["source_id"] == "000001.SZ"
            assert body["data_status"]["provider_time"] is not None
            actions = {c["action"]: c for c in body["capabilities"]}
            assert set(actions) == {"save_version", "confirm_and_generate"}
            # The candidate action has no quantity yet, so confirm is blocked.
            assert actions["confirm_and_generate"]["enabled"] is False
            assert actions["save_version"]["enabled"] is True
    finally:
        harness.dispose()


def test_revise_appends_new_version_without_overwrite(tmp_path) -> None:
    harness = _Harness(
        tmp_path,
        portfolio=_portfolio_view(()),
        candidates=_candidate_response(_candidate("000001.SZ")),
    )
    try:
        with TestClient(harness.app) as client:
            created = client.post(
                "/trade-plans/from-candidate",
                json={"instrument_id": "000001.SZ"},
                headers={"idempotency-key": "cand-1"},
            )
            plan = created.json()["object"]
            plan_id = plan["plan_id"]
            action_id = plan["actions"][0]["action_id"]

            revised = client.post(
                f"/trade-plans/{plan_id}/versions",
                json={
                    "expected_revision": 1,
                    "actions": [
                        {"action_id": action_id, "quantity": "100", "included": True}
                    ],
                },
            )
            assert revised.status_code == 200
            body = revised.json()
            assert body["object"]["revision"] == 2
            assert body["object"]["actions"][0]["quantity"] == "100"
            # Append-only history keeps the prior revision intact.
            assert len(body["history"]) == 2
            assert {item["revision"] for item in body["history"]} == {1, 2}

            # The original revision remains readable/unchanged (no in-place overwrite).
            latest = client.get(f"/trade-plans/{plan_id}")
            assert latest.json()["object"]["revision"] == 2
    finally:
        harness.dispose()


def test_revise_with_stale_expected_revision_conflicts(tmp_path) -> None:
    harness = _Harness(
        tmp_path,
        portfolio=_portfolio_view(()),
        candidates=_candidate_response(_candidate("000001.SZ")),
    )
    try:
        with TestClient(harness.app) as client:
            created = client.post(
                "/trade-plans/from-candidate",
                json={"instrument_id": "000001.SZ"},
                headers={"idempotency-key": "cand-1"},
            )
            plan = created.json()["object"]
            action_id = plan["actions"][0]["action_id"]
            conflict = client.post(
                f"/trade-plans/{plan['plan_id']}/versions",
                json={
                    "expected_revision": 5,
                    "actions": [
                        {"action_id": action_id, "quantity": "100", "included": True}
                    ],
                },
            )
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "REVISION_CONFLICT"
    finally:
        harness.dispose()


def test_confirm_and_generate_creates_drafts_and_marks_confirmed(tmp_path) -> None:
    harness = _Harness(
        tmp_path,
        portfolio=_portfolio_view(()),
        candidates=_candidate_response(_candidate("000001.SZ")),
    )
    try:
        with TestClient(harness.app) as client:
            created = client.post(
                "/trade-plans/from-candidate",
                json={"instrument_id": "000001.SZ"},
                headers={"idempotency-key": "cand-1"},
            )
            plan = created.json()["object"]
            plan_id = plan["plan_id"]
            action_id = plan["actions"][0]["action_id"]
            client.post(
                f"/trade-plans/{plan_id}/versions",
                json={
                    "expected_revision": 1,
                    "actions": [
                        {"action_id": action_id, "quantity": "100", "included": True}
                    ],
                },
            )
            confirmed = client.post(
                f"/trade-plans/{plan_id}/confirm-and-generate",
                json={"expected_revision": 2},
                headers={"idempotency-key": "confirm-1"},
            )
            assert confirmed.status_code == 200
            body = confirmed.json()
            assert body["object"]["status"] == "confirmed"
            assert len(body["draft_links"]) == 1
            assert body["draft_links"][0]["action_id"] == action_id
            # The generated draft used the PLANNED path with a plan reference.
            assert len(harness.drafts.calls) == 1
            call = harness.drafts.calls[0]
            assert call["mode"] is DraftMode.PLANNED
            assert call["plan_reference"] is not None
    finally:
        harness.dispose()


def test_confirm_blocked_when_action_quantity_missing(tmp_path) -> None:
    harness = _Harness(
        tmp_path,
        portfolio=_portfolio_view(()),
        candidates=_candidate_response(_candidate("000001.SZ")),
    )
    try:
        with TestClient(harness.app) as client:
            created = client.post(
                "/trade-plans/from-candidate",
                json={"instrument_id": "000001.SZ"},
                headers={"idempotency-key": "cand-1"},
            )
            plan_id = created.json()["object"]["plan_id"]
            blocked = client.post(
                f"/trade-plans/{plan_id}/confirm-and-generate",
                json={"expected_revision": 1},
                headers={"idempotency-key": "confirm-1"},
            )
            assert blocked.status_code == 409
            assert blocked.json()["error"]["code"] == "PLAN_BLOCKED"
            # A hard block must not produce any submittable draft.
            assert harness.drafts.calls == []
    finally:
        harness.dispose()


def test_portfolio_deviation_respects_hard_single_asset_ratio(tmp_path) -> None:
    positions = (
        _position("000001.SZ", cost=Decimal("9000"), quantity=Decimal("1000")),
        _position("600519.SH", cost=Decimal("1000"), quantity=Decimal("100")),
    )
    harness = _Harness(
        tmp_path,
        portfolio=_portfolio_view(positions),
        candidates=_candidate_response(),
    )
    try:
        with TestClient(harness.app) as client:
            created = client.post(
                "/trade-plans/from-portfolio-deviation",
                json={},
                headers={"idempotency-key": "dev-1"},
            )
            assert created.status_code == 201
            body = created.json()
            assert body["source_type"] == "portfolio_deviation"
            actions = body["object"]["actions"]
            # Only the concentrated (>20%) position produces a trim action.
            assert len(actions) == 1
            assert actions[0]["instrument_id"] == "000001.SZ"
            assert actions[0]["side"] == "sell"
            assert Decimal(actions[0]["quantity"]) > 0
    finally:
        harness.dispose()


def test_confirm_blocked_when_market_data_stale(tmp_path) -> None:
    positions = (
        _position("000001.SZ", cost=Decimal("9000"), quantity=Decimal("1000")),
        _position("600519.SH", cost=Decimal("1000"), quantity=Decimal("100")),
    )
    harness = _Harness(
        tmp_path,
        portfolio=_portfolio_view(positions),
        candidates=_candidate_response(),
        quotes_freshness="stale",
    )
    try:
        with TestClient(harness.app) as client:
            created = client.post(
                "/trade-plans/from-portfolio-deviation",
                json={},
                headers={"idempotency-key": "dev-1"},
            )
            plan_id = created.json()["object"]["plan_id"]
            blocked = client.post(
                f"/trade-plans/{plan_id}/confirm-and-generate",
                json={"expected_revision": 1},
                headers={"idempotency-key": "confirm-1"},
            )
            assert blocked.status_code == 409
            assert blocked.json()["error"]["code"] == "PLAN_BLOCKED"
            assert harness.drafts.calls == []
    finally:
        harness.dispose()
