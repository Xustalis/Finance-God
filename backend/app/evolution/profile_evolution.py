"""画像进化 - 贝叶斯置信度校准"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evolution_feedback import EvolutionFeedback


class ProfileEvolution:
    """根据用户修正历史调整置信度计算权重"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def recalculate_confidence_weights(self, user_id: str) -> dict:
        """重新计算画像维度的置信度权重"""
        result = await self.db.execute(
            select(EvolutionFeedback).where(
                EvolutionFeedback.user_id == user_id,
                EvolutionFeedback.feedback_type == "profile_correction",
                EvolutionFeedback.evolution_applied == False,  # noqa: E712
            )
        )
        feedbacks = list(result.scalars().all())

        if not feedbacks:
            return {"status": "no_feedback", "adjustments": 0}

        dimension_corrections: dict[str, int] = {}
        for fb in feedbacks:
            dim = (fb.feedback_value or {}).get("dimension", "unknown")
            dimension_corrections[dim] = dimension_corrections.get(dim, 0) + 1

        adjustments = {}
        for dim, count in dimension_corrections.items():
            prior = 0.5
            likelihood = 1.0 / (1.0 + count * 0.2)
            posterior = prior * likelihood / (prior * likelihood + (1 - prior) * (1 - likelihood) + 1e-9)
            adjustments[dim] = {
                "correction_count": count,
                "old_weight": float(prior),
                "new_weight": float(posterior),
            }

        # 标记全部反馈为已应用
        for fb in feedbacks:
            fb.evolution_applied = True

        await self.db.flush()
        return {"status": "applied", "adjustments": adjustments}

    async def suggest_question_improvements(self) -> list[dict]:
        """建议改进画像问题"""
        return [
            {"dimension": "stated_risk", "suggestion": "增加情景测试问题以区分陈述与实际风险偏好"},
            {"dimension": "behavioral_prefs", "suggestion": "增加回撤反应的具体场景描述"},
        ]
