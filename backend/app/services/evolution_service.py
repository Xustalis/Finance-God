"""自进化服务 - 整合反馈收集与进化评估"""

import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evolution_feedback import EvolutionFeedback


class EvolutionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def collect_profile_correction(self, user_id: str, dimension: str, old_value, new_value):
        feedback = EvolutionFeedback(
            id=str(uuid.uuid4()),
            user_id=user_id,
            feedback_type="profile_correction",
            target_type="profile_dimension",
            target_id=dimension,
            target_version=1,
            feedback_value={"dimension": dimension, "old_value": old_value, "new_value": new_value},
        )
        self.db.add(feedback)
        await self.db.flush()
        return {"id": feedback.id, "feedback_type": "profile_correction"}

    async def collect_strategy_evaluation(self, user_id: str, strategy_id: str, rating: int, comment: str = ""):
        feedback = EvolutionFeedback(
            id=str(uuid.uuid4()),
            user_id=user_id,
            feedback_type="strategy_evaluation",
            target_type="strategy_proposal",
            target_id=strategy_id,
            target_version=1,
            feedback_value={"rating": rating, "comment": comment},
        )
        self.db.add(feedback)
        await self.db.flush()
        return {"id": feedback.id, "feedback_type": "strategy_evaluation"}

    async def collect_bias_feedback(self, user_id: str, bias_type: str, confirmed: bool):
        feedback = EvolutionFeedback(
            id=str(uuid.uuid4()),
            user_id=user_id,
            feedback_type="bias_confirmation" if confirmed else "bias_rejection",
            target_type="cognitive_bias",
            target_id=bias_type,
            target_version=1,
            feedback_value={"bias_type": bias_type, "confirmed": confirmed},
        )
        self.db.add(feedback)
        await self.db.flush()
        return {"id": feedback.id, "feedback_type": feedback.feedback_type}

    async def run_evolution(self, user_id: str) -> dict:
        """触发进化评估"""
        from app.evolution.profile_evolution import ProfileEvolution
        from app.evolution.strategy_evolution import StrategyEvolution
        from app.evolution.bias_evolution import BiasEvolution

        profile_evo = ProfileEvolution(self.db)
        strategy_evo = StrategyEvolution(self.db)
        bias_evo = BiasEvolution(self.db)

        profile_result = await profile_evo.recalculate_confidence_weights(user_id)
        strategy_result = await strategy_evo.update_strategy_scores(user_id)
        bias_result = await bias_evo.update_thresholds(user_id)

        return {
            "profile_evolution": profile_result,
            "strategy_evolution": strategy_result,
            "bias_evolution": bias_result,
        }
