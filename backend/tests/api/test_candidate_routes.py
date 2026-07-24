from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.workspace_routes import create_workspace_routes
from finance_god.application.candidate_service import CandidateScoringService
from finance_god.infrastructure.persistence.models import Base
from finance_god.market_data.service import MarketQuote, QuoteBatch


async def _resolve_server_user(_request) -> str:
    return "server-user"


def _quote(symbol: str, *, amount: Decimal, high: Decimal, low: Decimal) -> MarketQuote:
    return MarketQuote(
        symbol=symbol,
        name=f"{symbol} name",
        asset_type="stock",
        market="CN",
        currency="CNY",
        last=Decimal("10.00"),
        open=Decimal("10.00"),
        high=high,
        low=low,
        previous_close=Decimal("10.00"),
        change=Decimal("0"),
        change_percent=Decimal("0"),
        volume=Decimal("1000000"),
        amount=amount,
        provider="PandaData",
        provider_time="2026-07-24T10:31:00+08:00",
        retrieved_at=datetime(2026, 7, 24, 2, 31, tzinfo=UTC),
        frequency="realtime",
        freshness="fresh",
        market_status="open",
        source_endpoint="quotes",
        capability_version="v1",
        instrument_master_identity="im",
        instrument_master_version="1",
    )


class _FakePortfolio:
    def __init__(self, positions: tuple[object, ...]) -> None:
        self._positions = positions

    async def positions(self, *, owner_id: str) -> object:
        class _View:
            positions = self._positions

        return _View()


class _Position:
    def __init__(self, instrument_id: str, cost_basis_rmb: Decimal) -> None:
        self.instrument_id = instrument_id
        self.cost_basis_rmb = cost_basis_rmb


def test_candidate_dimensions_are_independent_with_no_total_score() -> None:
    async def quotes(symbols: list[str]) -> QuoteBatch:
        return QuoteBatch(
            requested_at=datetime(2026, 7, 24, 2, 31, tzinfo=UTC),
            cache_hit=False,
            quotes=(
                _quote(
                    "000001.SZ",
                    amount=Decimal("2000000000"),
                    high=Decimal("10.10"),
                    low=Decimal("9.95"),
                ),
            ),
            errors={"600519.SH": "PROVIDER_TIMEOUT"},
        )

    service = CandidateScoringService(
        portfolio=_FakePortfolio(()),
        quotes_provider=quotes,
    )
    response = asyncio.run(
        service.candidates(owner_id="user-1", now=datetime.now(UTC))
    )
    assert response.candidates
    # No mystery aggregate: the model exposes only per-dimension bands.
    assert not hasattr(response.candidates[0], "score")
    for candidate in response.candidates:
        dims = {d.dimension for d in candidate.dimensions}
        assert dims == {"portfolio_fit", "risk", "cost", "liquidity", "evidence"}

    scored = {c.symbol: c for c in response.candidates}
    # A symbol with a real quote is tradable; a quote-less symbol is not.
    assert scored["000001.SZ"].tradable is True
    missing = scored["600519.SH"]
    assert missing.tradable is False
    evidence = next(d for d in missing.dimensions if d.dimension == "evidence")
    assert evidence.rating == "missing"


def test_market_data_failure_degrades_explicitly() -> None:
    async def failing_quotes(symbols: list[str]) -> QuoteBatch:
        raise RuntimeError("market data down")

    service = CandidateScoringService(
        portfolio=_FakePortfolio(()),
        quotes_provider=failing_quotes,
    )
    response = asyncio.run(
        service.candidates(owner_id="user-1", now=datetime.now(UTC))
    )
    assert response.unavailable_reason == "MARKET_DATA_UNAVAILABLE"
    assert all(not c.tradable for c in response.candidates)


def test_concentration_hard_limit_excludes_candidate() -> None:
    async def quotes(symbols: list[str]) -> QuoteBatch:
        return QuoteBatch(
            requested_at=datetime(2026, 7, 24, 2, 31, tzinfo=UTC),
            cache_hit=False,
            quotes=(
                _quote(
                    "000001.SZ",
                    amount=Decimal("2000000000"),
                    high=Decimal("10.10"),
                    low=Decimal("9.95"),
                ),
            ),
            errors={},
        )

    # 000001.SZ is 90% of the portfolio cost basis -> above hard single-asset limit.
    portfolio = _FakePortfolio(
        (
            _Position("000001.SZ", Decimal("9000")),
            _Position("999999.SZ", Decimal("1000")),
        )
    )
    service = CandidateScoringService(portfolio=portfolio, quotes_provider=quotes)
    response = asyncio.run(
        service.candidates(owner_id="user-1", now=datetime.now(UTC))
    )
    concentrated = next(c for c in response.candidates if c.symbol == "000001.SZ")
    assert concentrated.tradable is False
    assert any(e.reason_code == "concentration_hard" for e in concentrated.exclusions)


def test_ignore_feedback_persists_without_deleting_evidence(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'candidate-api.db'}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    asyncio.run(_create_schema(engine))

    async def quotes(symbols: list[str]) -> QuoteBatch:
        return QuoteBatch(
            requested_at=datetime(2026, 7, 24, 2, 31, tzinfo=UTC),
            cache_hit=False,
            quotes=tuple(
                _quote(
                    s,
                    amount=Decimal("2000000000"),
                    high=Decimal("10.10"),
                    low=Decimal("9.95"),
                )
                for s in symbols
            ),
            errors={},
        )

    def provider() -> CandidateScoringService:
        return CandidateScoringService(
            portfolio=_FakePortfolio(()), quotes_provider=quotes
        )

    app = Starlette(
        routes=[
            Mount(
                "/api/v1",
                routes=create_workspace_routes(
                    session_factory=session_factory,
                    owner_resolver=_resolve_server_user,
                    candidate_service_provider=provider,
                ),
            )
        ]
    )
    try:
        with TestClient(app) as client:
            listed = client.get("/api/v1/candidates")
            assert listed.status_code == 200
            assert listed.json()["candidates"]

            ignored = client.post(
                "/api/v1/candidates/000001.SZ/ignore",
                json={"reason": "already_covered", "note": "已通过基金覆盖"},
            )
            assert ignored.status_code == 201
            assert ignored.json()["reason"] == "already_covered"

            after = client.get("/api/v1/candidates")
            body = {c["symbol"]: c for c in after.json()["candidates"]}
            assert body["000001.SZ"]["ignored"] is True
            assert body["000001.SZ"]["ignore_reason"] == "already_covered"

            undo = client.delete("/api/v1/candidates/000001.SZ/ignore")
            assert undo.status_code == 200
            restored = client.get("/api/v1/candidates")
            restored_body = {c["symbol"]: c for c in restored.json()["candidates"]}
            assert restored_body["000001.SZ"]["ignored"] is False
    finally:
        asyncio.run(engine.dispose())


async def _create_schema(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
