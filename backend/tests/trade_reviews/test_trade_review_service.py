from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base as AppBase
from finance_god.infrastructure.persistence import Base as TradingBase
from finance_god.trade_review import EpisodeStatus, TradeReviewService


class OrderFact:
    def __init__(
        self, *, order_id: str, fill_id: str, side: str, quantity: str, price: str, at: datetime
    ) -> None:
        self._payload = {
            "order_id": order_id,
            "instrument_id": "600519.SH",
            "side": side,
            "fills": [
                {
                    "fill_id": fill_id,
                    "quantity": quantity,
                    "price": price,
                    "fee": "1",
                    "occurred_at": at.isoformat(),
                }
            ],
        }

    def model_dump(self, **_: object) -> dict[str, object]:
        return self._payload


@pytest.mark.asyncio
async def test_position_cycle_reuses_episode_and_closes_once() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(AppBase.metadata.create_all)
        await connection.run_sync(TradingBase.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = TradeReviewService(sessions)
    now = datetime.now(UTC)
    evidence = {
        "object_type": "market_bar",
        "object_id": "600519.SH",
        "version": "2026-07-25T01:00:00Z",
    }

    opened = await service.record_filled_order(
        owner_id="user-1",
        account_id="account-1",
        order=OrderFact(
            order_id="order-1", fill_id="fill-1", side="buy",
            quantity="100", price="10", at=now,
        ),
        market_evidence=evidence,
        position_quantity_after=Decimal("100"),
        profile_version=None,
    )
    reduced = await service.record_filled_order(
        owner_id="user-1",
        account_id="account-1",
        order=OrderFact(
            order_id="order-2", fill_id="fill-2", side="sell",
            quantity="40", price="11", at=now + timedelta(days=1),
        ),
        market_evidence=evidence,
        position_quantity_after=Decimal("60"),
        profile_version=None,
    )
    closed = await service.record_filled_order(
        owner_id="user-1",
        account_id="account-1",
        order=OrderFact(
            order_id="order-3", fill_id="fill-3", side="sell",
            quantity="60", price="12", at=now + timedelta(days=2),
        ),
        market_evidence=evidence,
        position_quantity_after=Decimal("0"),
        profile_version=None,
    )

    assert opened["episode_id"] == reduced["episode_id"] == closed["episode_id"]
    assert opened["review_triggered"] is False
    assert reduced["review_triggered"] is False
    assert closed["review_triggered"] is True
    episode = await service.get_episode(
        owner_id="user-1", episode_id=str(closed["episode_id"])
    )
    assert episode.status is EpisodeStatus.REVIEW_COMPLETED
    assert len(await service.decisions(owner_id="user-1", episode_id=episode.episode_id)) == 3
    review = await service.get_review(owner_id="user-1", episode_id=episode.episode_id)
    assert review.actual_return_rmb == Decimal("157")
    await engine.dispose()
