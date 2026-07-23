"""持仓路由 - 当前持仓/CSV导入"""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.services.holding_service import HoldingService

router = APIRouter()


@router.get("/current")
async def get_current_holdings(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = HoldingService(db)
    holdings = await service.get_current(user_id)
    return ApiResponse.ok(holdings)


@router.post("/imports")
async def import_holdings(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    # utf-8-sig 兼容带 BOM 的 CSV(常见于中文导出工具)
    csv_text = content.decode("utf-8-sig")
    service = HoldingService(db)
    result = await service.import_csv(user_id, csv_text)
    return ApiResponse.ok(result)
