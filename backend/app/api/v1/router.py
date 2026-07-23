"""API v1 路由聚合"""

from fastapi import APIRouter

api_router = APIRouter()

# 认证
from app.api.v1.auth import router as auth_router
api_router.include_router(auth_router, prefix="/auth", tags=["认证"])

# 画像
from app.api.v1.profiles import router as profiles_router
api_router.include_router(profiles_router, prefix="/profiles", tags=["用户画像"])

# 用户状态
from app.api.v1.user_states import router as user_states_router
api_router.include_router(user_states_router, prefix="/user-states", tags=["用户心智状态"])

# 授权书
from app.api.v1.mandates import router as mandates_router
api_router.include_router(mandates_router, prefix="/mandates", tags=["投资授权书"])

# 持仓
from app.api.v1.holdings import router as holdings_router
api_router.include_router(holdings_router, prefix="/holdings", tags=["持仓"])

# 资产
from app.api.v1.instruments import router as instruments_router
api_router.include_router(instruments_router, prefix="/instruments", tags=["资产主数据"])

# 策略
from app.api.v1.strategies import router as strategies_router
api_router.include_router(strategies_router, prefix="/strategies", tags=["策略"])

# 组合
from app.api.v1.portfolios import router as portfolios_router
api_router.include_router(portfolios_router, prefix="/target-portfolios", tags=["目标组合"])

# 订单
from app.api.v1.orders import router as orders_router
api_router.include_router(orders_router, prefix="/orders", tags=["订单"])

# 复盘
from app.api.v1.reviews import router as reviews_router
api_router.include_router(reviews_router, prefix="/reviews", tags=["复盘"])

# 风险事件
from app.api.v1.risk_events import router as risk_events_router
api_router.include_router(risk_events_router, prefix="/risk-events", tags=["风险事件"])

# Agent
from app.api.v1.agents import router as agents_router
api_router.include_router(agents_router, prefix="/agents", tags=["Agent"])

# 市场环境
from app.api.v1.market_contexts import router as market_contexts_router
api_router.include_router(market_contexts_router, prefix="/market-contexts", tags=["市场环境"])

# 审计
from app.api.v1.audit_events import router as audit_events_router
api_router.include_router(audit_events_router, prefix="/audit-events", tags=["审计"])
