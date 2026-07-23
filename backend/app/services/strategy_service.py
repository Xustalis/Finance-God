"""策略服务 - 策略候选生成"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import StrategyProposal
from app.models.mandate import InvestmentMandate
from app.models.market_context import MarketContext
from app.models.cooldown import CooldownPeriod
from app.core.exceptions import (
    ForbiddenError,
    ResourceNotFoundError,
    CooldownActiveError,
    MandateNotActiveError,
)


class StrategyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_proposal(self, user_id: str, data: dict) -> dict:
        """生成策略候选"""
        mandate_id = data.get("mandate_id")
        result = await self.db.execute(
            select(InvestmentMandate).where(InvestmentMandate.id == mandate_id)
        )
        mandate = result.scalar_one_or_none()
        if not mandate:
            raise ResourceNotFoundError("授权书", mandate_id)
        if mandate.user_id != user_id:
            raise ForbiddenError("无权使用该授权书")
        if mandate.status != "active":
            raise MandateNotActiveError(mandate.status)

        # 冷静期：策略生成可被暂停
        cd_result = await self.db.execute(
            select(CooldownPeriod).where(
                CooldownPeriod.user_id == user_id,
                CooldownPeriod.status == "active",
            )
        )
        cooldown = cd_result.scalar_one_or_none()
        if cooldown and (cooldown.affected_scope or {}).get("strategy_generation", True):
            raise CooldownActiveError(cooldown.id)

        mc_result = await self.db.execute(
            select(MarketContext)
            .order_by(MarketContext.version.desc())
            .limit(1)
        )
        market_ctx = mc_result.scalar_one_or_none()

        risk_budget = mandate.risk_budget or {}
        max_drawdown = float(risk_budget.get("max_drawdown", 0.2))

        if max_drawdown <= 0.10:
            equity_ratio, bond_ratio, cash_ratio = 0.30, 0.50, 0.20
            risk_profile = "conservative"
        elif max_drawdown <= 0.20:
            equity_ratio, bond_ratio, cash_ratio = 0.60, 0.30, 0.10
            risk_profile = "moderate"
        else:
            equity_ratio, bond_ratio, cash_ratio = 0.80, 0.15, 0.05
            risk_profile = "aggressive"

        if market_ctx and market_ctx.overall_sentiment is not None:
            sentiment = float(market_ctx.overall_sentiment)
            adjustment = (sentiment - 0.5) * 0.10
            equity_ratio = max(0.0, min(0.95, equity_ratio + adjustment))
            remaining = max(0.0, 1.0 - equity_ratio)
            # 保持债/现比例
            bond_share = 0.75 if risk_profile != "conservative" else 0.71
            bond_ratio = remaining * bond_share
            cash_ratio = remaining - bond_ratio
            cash_ratio = max(0.05, cash_ratio)
            bond_ratio = max(0.0, 1.0 - equity_ratio - cash_ratio)

        global_allocation = {
            "cash_ratio": round(cash_ratio, 4),
            "equity_ratio": round(equity_ratio, 4),
            "bond_ratio": round(bond_ratio, 4),
        }

        asset_scope = mandate.asset_scope or {}
        allowed_markets = asset_scope.get("allowed_markets", ["a_shares"])
        market_weights = {}
        splits = {"a_shares": 0.5, "us_stocks": 0.3, "hk_stocks": 0.2}
        active = [m for m in splits if m in allowed_markets]
        if not active:
            active = ["a_shares"]
        split_total = sum(splits[m] for m in active)
        for m in active:
            market_weights[m] = {"weight": round(equity_ratio * (splits[m] / split_total), 4)}

        risk_scenarios = [
            {"scenario_name": "基准", "expected_return": 0.08, "expected_volatility": 0.12, "max_drawdown": -0.15, "probability": 0.5},
            {"scenario_name": "乐观", "expected_return": 0.15, "expected_volatility": 0.14, "max_drawdown": -0.10, "probability": 0.25},
            {"scenario_name": "悲观", "expected_return": -0.05, "expected_volatility": 0.18, "max_drawdown": -0.25, "probability": 0.25},
        ]

        result = await self.db.execute(
            select(StrategyProposal)
            .where(StrategyProposal.user_id == user_id)
            .order_by(StrategyProposal.version.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        new_version = (latest.version + 1) if latest else 1

        proposal = StrategyProposal(
            id=str(uuid.uuid4()),
            version=new_version,
            user_id=user_id,
            mandate_version=mandate.version,
            market_context_id=market_ctx.id if market_ctx else None,
            research_memo_ids=[],
            global_allocation=global_allocation,
            market_allocation=market_weights,
            mental_adaptations={"adaptations_applied": [], "explanation": "当前心智状态正常，无额外调整"},
            risk_scenarios=risk_scenarios,
            assumptions=["市场情绪中性", "无重大政策变化"],
            applicable_mandate_scope={"risk_profile": risk_profile},
            invalidation_conditions=["授权书变更", "市场环境失效"],
            model_version="rule_engine_v1",
            explanation=(
                f"基于您的风险偏好（{risk_profile}）和最大回撤限制（{max_drawdown:.0%}），"
                f"建议{equity_ratio:.0%}权益+{bond_ratio:.0%}债券+{cash_ratio:.0%}现金的配置"
            ),
            status="candidate",
        )
        self.db.add(proposal)
        await self.db.flush()
        return self._to_dict(proposal)

    async def pause(self, user_id: str, reason: str = "用户主动暂停") -> dict:
        """暂停用户所有候选/活跃策略"""
        result = await self.db.execute(
            select(StrategyProposal).where(
                StrategyProposal.user_id == user_id,
                StrategyProposal.status.in_(["candidate", "active", "approved"]),
            )
        )
        proposals = result.scalars().all()
        for p in proposals:
            p.status = "paused"
        await self.db.flush()
        return {"paused": True, "reason": reason, "count": len(proposals), "scope": "user"}

    def _to_dict(self, proposal: StrategyProposal) -> dict:
        return {
            "id": proposal.id,
            "version": proposal.version,
            "status": proposal.status,
            "global_allocation": proposal.global_allocation,
            "market_allocation": proposal.market_allocation,
            "risk_scenarios": proposal.risk_scenarios,
            "assumptions": proposal.assumptions,
            "mental_adaptations": proposal.mental_adaptations,
            "explanation": proposal.explanation,
            "mandate_version": proposal.mandate_version,
            "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        }
