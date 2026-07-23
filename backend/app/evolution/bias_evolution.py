"""偏差检测进化 - 检测阈值自适应调整"""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evolution_feedback import EvolutionFeedback


# 默认阈值（可被进化层调整）
DEFAULT_THRESHOLDS = {
    "anxiety": 0.7,
    "greed": 0.7,
    "impulsivity": 0.8,
    "loss_aversion": 0.7,
    "overconfidence": 0.7,
    "herding": 0.6,
    "anchoring": 0.6,
    "disposition_effect": 0.6,
}


class BiasEvolution:
    """根据用户确认/拒绝调整偏差检测阈值"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_thresholds(self, user_id: str) -> dict:
        """更新偏差检测阈值"""
        result = await self.db.execute(
            select(EvolutionFeedback).where(
                EvolutionFeedback.user_id == user_id,
                EvolutionFeedback.feedback_type.in_(["bias_confirmation", "bias_rejection"]),
                EvolutionFeedback.evolution_applied == False,
            )
        )
        feedbacks = result.scalars().all()

        if not feedbacks:
            return {"status": "no_feedback", "thresholds": DEFAULT_THRESHOLDS}

        # 统计各偏差类型的确认/拒绝次数
        bias_stats: dict[str, dict] = {}
        for fb in feedbacks:
            bias_type = fb.feedback_value.get("bias_type", "unknown")
            confirmed = fb.feedback_value.get("confirmed", False)
            if bias_type not in bias_stats:
                bias_stats[bias_type] = {"confirmations": 0, "rejections": 0}
            if confirmed:
                bias_stats[bias_type]["confirmations"] += 1
            else:
                bias_stats[bias_type]["rejections"] += 1

        # 自适应调整: 确认多 -> 阈值降低（更敏感）; 拒绝多 -> 阈值升高（更保守）
        adjusted_thresholds = dict(DEFAULT_THRESHOLDS)
        adjustments = {}
        for bias_type, stats in bias_stats.items():
            old_threshold = adjusted_thresholds.get(bias_type, 0.7)
            confirmations = stats["confirmations"]
            rejections = stats["rejections"]
            total = confirmations + rejections

            if total > 0:
                # 确认率高的偏差，降低阈值（更敏感）
                confirmation_rate = confirmations / total
                adjustment = (confirmation_rate - 0.5) * 0.2  # ±0.1
                new_threshold = max(0.3, min(0.9, old_threshold - adjustment))
                adjusted_thresholds[bias_type] = new_threshold
                adjustments[bias_type] = {
                    "old_threshold": old_threshold,
                    "new_threshold": new_threshold,
                    "confirmations": confirmations,
                    "rejections": rejections,
                }

            # 标记为已应用
            for fb in feedbacks:
                if fb.feedback_value.get("bias_type") == bias_type:
                    fb.evolution_applied = True

        await self.db.flush()
        return {"status": "applied", "adjustments": adjustments, "thresholds": adjusted_thresholds}

    async def get_adaptive_thresholds(self, user_id: str, bias_type: str = "") -> dict:
        """获取自适应阈值"""
        # 简化: 返回默认阈值
        if bias_type:
            return {"bias_type": bias_type, "threshold": DEFAULT_THRESHOLDS.get(bias_type, 0.7)}
        return {"thresholds": DEFAULT_THRESHOLDS}
