"""策略进化 - 历史胜率加权排序"""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evolution_feedback import EvolutionFeedback
from app.models.strategy import StrategyProposal


class StrategyEvolution:
    """根据历史表现调整策略候选排序权重"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_strategy_scores(self, user_id: str) -> dict:
        """更新策略评分"""
        result = await self.db.execute(
            select(EvolutionFeedback).where(
                EvolutionFeedback.user_id == user_id,
                EvolutionFeedback.feedback_type == "strategy_evaluation",
                EvolutionFeedback.evolution_applied == False,
            )
        )
        feedbacks = result.scalars().all()

        if not feedbacks:
            return {"status": "no_feedback", "strategies_updated": 0}

        # 按策略ID分组计算平均评分
        strategy_ratings: dict[str, list[int]] = {}
        for fb in feedbacks:
            sid = fb.target_id
            rating = fb.feedback_value.get("rating", 3)
            strategy_ratings.setdefault(sid, []).append(rating)

        updates = {}
        for sid, ratings in strategy_ratings.items():
            avg_rating = sum(ratings) / len(ratings)
            # 胜率 = (avg_rating / 5) 作为权重因子
            win_rate = avg_rating / 5.0
            updates[sid] = {
                "avg_rating": avg_rating,
                "evaluation_count": len(ratings),
                "win_rate": win_rate,
            }
            fb.evolution_applied = True

        await self.db.flush()
        return {"status": "applied", "strategies_updated": updates}

    async def get_strategy_ranking(self, user_id: str, context: dict) -> list[dict]:
        """获取策略排序（基于历史评分）"""
        result = await self.db.execute(
            select(StrategyProposal).where(
                StrategyProposal.user_id == user_id,
                StrategyProposal.status.in_(["candidate", "accepted"]),
            ).order_by(StrategyProposal.version.desc())
        )
        strategies = result.scalars().all()
        return [
            {"id": s.id, "version": s.version, "status": s.status, "explanation": s.explanation}
            for s in strategies
        ]
