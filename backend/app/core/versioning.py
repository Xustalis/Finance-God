"""版本化工具 - 全链路版本追溯"""

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel


class VersionInfo(BaseModel):
    """版本信息"""
    version: int
    created_at: datetime
    entity_type: str
    entity_id: uuid.UUID


class TraceChain(BaseModel):
    """版本追溯链"""
    profile_version: int | None = None
    mandate_version: int | None = None
    strategy_version: int | None = None
    portfolio_version: int | None = None
    market_context_id: str | None = None
    holding_snapshot_version: int | None = None
    user_state_snapshot_id: str | None = None


def generate_request_correlation_id() -> str:
    """生成请求关联ID, 用于串联一次完整操作链"""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """获取UTC当前时间"""
    return datetime.now(timezone.utc)
