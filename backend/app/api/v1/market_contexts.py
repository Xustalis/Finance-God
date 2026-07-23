"""市场环境路由 - 当前市场环境"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.market_context import MarketContext

router = APIRouter()


@router.get("/current")
async def get_current_market_context(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MarketContext)
        .order_by(MarketContext.version.desc(), MarketContext.created_at.desc())
        .limit(1)
    )
    ctx = result.scalar_one_or_none()
    if not ctx:
        return ApiResponse.ok(None)
    return ApiResponse.ok(_to_dict(ctx))


def _to_dict(ctx: MarketContext) -> dict:
    return {
        "id": ctx.id,
        "version": ctx.version,
        "markets": ctx.markets,
        "overall_sentiment": float(ctx.overall_sentiment),
        "events_summary": ctx.events_summary,
        "data_quality": ctx.data_quality,
        "sources": ctx.sources,
        "applicable_markets": ctx.applicable_markets,
        "applicable_instruments": ctx.applicable_instruments,
        "confidence": float(ctx.confidence),
        "usable_status": ctx.usable_status,
        "data_as_of": ctx.data_as_of.isoformat() if ctx.data_as_of else None,
        "expires_at": ctx.expires_at.isoformat() if ctx.expires_at else None,
        "created_at": ctx.created_at.isoformat() if ctx.created_at else None,
    }
