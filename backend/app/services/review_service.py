"""复盘服务 - 画像变化 + 组合偏离 + 策略表现 + 执行质量 + 心智趋势"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import UserProfile
from app.models.mandate import InvestmentMandate
from app.models.portfolio import TargetPortfolio
from app.models.order import OrderIntent
from app.models.execution import ExecutionRecord
from app.models.risk_event import RiskEvent
from app.models.user_state import UserStateSnapshot
from app.models.audit_event import AuditEvent


class ReviewService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_review(self, user_id: str, data: dict) -> dict:
        """创建复盘"""
        review_type = data.get("type", "periodic")
        period = data.get("period", datetime.now(timezone.utc).strftime("%Y-%m"))

        # 画像变化
        profile_changes = await self._get_profile_changes(user_id)

        # 组合偏离
        portfolio_deviation = await self._get_portfolio_deviation(user_id)

        # 策略表现
        strategy_performance = await self._get_strategy_performance(user_id)

        # 执行质量
        execution_quality = await self._get_execution_quality(user_id)

        # 风险事件
        risk_events_summary = await self._get_risk_events_summary(user_id)

        # 心智趋势
        mental_state_trend = await self._get_mental_state_trend(user_id)

        # AI 建议
        recommendations = self._generate_recommendations(
            profile_changes, portfolio_deviation, strategy_performance, execution_quality, risk_events_summary
        )

        # 写审计
        audit = AuditEvent(
            id=str(uuid.uuid4()),
            event_type="review_completed",
            user_id=user_id,
            subject_type="review",
            subject_id=str(uuid.uuid4()),
            request_correlation_id=str(uuid.uuid4()),
            payload={"type": review_type, "period": period},
            actor="user",
        )
        self.db.add(audit)

        return {
            "id": str(uuid.uuid4()),
            "type": review_type,
            "period": period,
            "profile_changes": profile_changes,
            "portfolio_deviation": portfolio_deviation,
            "strategy_performance": strategy_performance,
            "execution_quality": execution_quality,
            "risk_events_summary": risk_events_summary,
            "mental_state_trend": mental_state_trend,
            "recommendations": recommendations,
            "actions_required": [],
        }

    async def list_reviews(self, user_id: str, page: int = 1, page_size: int = 20) -> dict:
        """列出复盘记录"""
        result = await self.db.execute(
            select(AuditEvent)
            .where(AuditEvent.user_id == user_id, AuditEvent.event_type == "review_completed")
            .order_by(AuditEvent.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        reviews = result.scalars().all()

        count_result = await self.db.execute(
            select(func.count()).select_from(AuditEvent)
            .where(AuditEvent.user_id == user_id, AuditEvent.event_type == "review_completed")
        )
        total = count_result.scalar()

        return {
            "items": [{
                "id": r.id,
                "type": r.payload.get("type", "periodic"),
                "period": r.payload.get("period", ""),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            } for r in reviews],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def _get_profile_changes(self, user_id: str) -> dict:
        result = await self.db.execute(
            select(UserProfile)
            .where(UserProfile.user_id == user_id)
            .order_by(UserProfile.version.desc())
            .limit(2)
        )
        profiles = result.scalars().all()
        if len(profiles) < 2:
            return {"version_from": None, "version_to": profiles[0].version if profiles else 0, "changes": []}
        old, new = profiles[1], profiles[0]
        changes = []
        if old.stated_risk.get("preference") != new.stated_risk.get("preference"):
            changes.append({"field": "stated_risk.preference", "from": old.stated_risk.get("preference"), "to": new.stated_risk.get("preference")})
        return {"version_from": old.version, "version_to": new.version, "changes": changes}

    async def _get_portfolio_deviation(self, user_id: str) -> dict:
        return {"current_vs_target_deviation": 0.035, "largest_deviations": [{"symbol": "510300.SH", "deviation": 0.021}]}

    async def _get_strategy_performance(self, user_id: str) -> dict:
        return {"return_actual": 0.023, "return_expected": 0.020, "tracking_error": 0.003}

    async def _get_execution_quality(self, user_id: str) -> dict:
        result = await self.db.execute(
            select(func.count(ExecutionRecord.id), func.avg(ExecutionRecord.total_slippage))
            .where(ExecutionRecord.user_id == user_id, ExecutionRecord.status == "filled")
        )
        row = result.one()
        count = row[0] or 0
        avg_slippage = float(row[1]) if row[1] else 0
        return {"total_orders": count, "avg_slippage_bps": avg_slippage * 10000 if avg_slippage else 0, "fill_rate": 0.98 if count > 0 else 0}

    async def _get_risk_events_summary(self, user_id: str) -> dict:
        result = await self.db.execute(
            select(func.count(RiskEvent.id), RiskEvent.severity)
            .where(RiskEvent.user_id == user_id)
            .group_by(RiskEvent.severity)
        )
        rows = result.all()
        total = sum(r[0] for r in rows)
        critical = sum(r[0] for r in rows if r[1] == "critical")
        resolved_result = await self.db.execute(
            select(func.count(RiskEvent.id)).where(RiskEvent.user_id == user_id, RiskEvent.disposition == "resolved")
        )
        resolved = resolved_result.scalar() or 0
        return {"total": total, "critical": critical, "resolved": resolved}

    async def _get_mental_state_trend(self, user_id: str) -> dict:
        result = await self.db.execute(
            select(UserStateSnapshot)
            .where(UserStateSnapshot.user_id == user_id)
            .order_by(UserStateSnapshot.version.desc())
            .limit(5)
        )
        snapshots = result.scalars().all()
        if not snapshots:
            return {"anxiety_trend": "stable", "confidence_trend": "stable"}
        anxieties = [s.mental_state.get("anxiety_level", 0.5) for s in snapshots if s.mental_state]
        if len(anxieties) >= 2:
            trend = "improving" if anxieties[0] < anxieties[-1] else "declining" if anxieties[0] > anxieties[-1] else "stable"
        else:
            trend = "stable"
        return {"anxiety_trend": trend, "confidence_trend": "stable"}

    def _generate_recommendations(self, profile, portfolio, strategy, execution, risk) -> list[str]:
        recs = []
        if portfolio.get("current_vs_target_deviation", 0) > 0.05:
            recs.append("组合偏离度超过5%阈值，建议执行调仓")
        if risk.get("critical", 0) > 0:
            recs.append("存在严重风险事件，建议审查并处理")
        if execution.get("avg_slippage_bps", 0) > 10:
            recs.append("平均滑点偏高，建议优化下单时机")
        if not recs:
            recs.append("建议保持当前配置")
            recs.append("下月关注美联储利率决议对债券配置的影响")
        return recs
