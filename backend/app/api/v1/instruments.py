"""资产主数据路由 - 列表查询"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.db.session import get_db
from app.models.instrument import Instrument

router = APIRouter()


@router.get("/")
async def list_instruments(
    market: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Instrument)
    if market:
        stmt = stmt.where(Instrument.market == market)
    if asset_type:
        stmt = stmt.where(Instrument.asset_type == asset_type)
    if status:
        stmt = stmt.where(Instrument.status == status)
    stmt = stmt.order_by(Instrument.symbol).limit(limit).offset(offset)
    result = await db.execute(stmt)
    instruments = result.scalars().all()
    return ApiResponse.ok(
        [_to_dict(i) for i in instruments],
        meta={"count": len(instruments)},
    )


def _to_dict(inst: Instrument) -> dict:
    return {
        "id": inst.id,
        "symbol": inst.symbol,
        "name": inst.name,
        "asset_type": inst.asset_type,
        "market": inst.market,
        "currency": inst.currency,
        "exchange": inst.exchange,
        "min_trade_unit": float(inst.min_trade_unit),
        "expense_ratio": float(inst.expense_ratio) if inst.expense_ratio else None,
        "sector": inst.sector,
        "benchmark": inst.benchmark,
        "trading_attributes": inst.trading_attributes,
        "available_regions": inst.available_regions,
        "status": inst.status,
        "data_as_of": inst.data_as_of.isoformat() if inst.data_as_of else None,
    }
