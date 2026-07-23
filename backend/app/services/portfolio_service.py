"""组合服务 - 目标组合构造 + 调仓计划"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import TargetPortfolio
from app.models.strategy import StrategyProposal
from app.models.holding import HoldingSnapshot
from app.models.mandate import InvestmentMandate
from app.models.instrument import Instrument
from app.models.market_context import MarketContext
from app.core.exceptions import ForbiddenError, ResourceNotFoundError, ValidationError


class PortfolioService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate(self, user_id: str, data: dict) -> dict:
        """生成目标组合"""
        strategy_id = data.get("strategy_proposal_id")
        result = await self.db.execute(
            select(StrategyProposal).where(StrategyProposal.id == strategy_id)
        )
        strategy = result.scalar_one_or_none()
        if not strategy:
            raise ResourceNotFoundError("策略", strategy_id)
        if strategy.user_id != user_id:
            raise ForbiddenError("无权使用该策略")

        # 获取授权书
        m_result = await self.db.execute(
            select(InvestmentMandate).where(
                InvestmentMandate.user_id == user_id,
                InvestmentMandate.version == strategy.mandate_version,
            )
        )
        mandate = m_result.scalar_one_or_none()

        # 获取持仓
        h_result = await self.db.execute(
            select(HoldingSnapshot)
            .where(HoldingSnapshot.user_id == user_id)
            .order_by(HoldingSnapshot.version.desc())
            .limit(1)
        )
        holding = h_result.scalar_one_or_none()

        # 获取市场环境
        mc_result = await self.db.execute(
            select(MarketContext).order_by(MarketContext.version.desc()).limit(1)
        )
        market_ctx = mc_result.scalar_one_or_none()

        # 获取可用资产池
        asset_scope = mandate.asset_scope if mandate else {}
        allowed_types = asset_scope.get("allowed_asset_types") or ["etf"]
        allowed_markets = asset_scope.get("allowed_markets") or ["a_shares"]

        stmt = select(Instrument).where(Instrument.status == "active")
        if allowed_types:
            stmt = stmt.where(Instrument.asset_type.in_(allowed_types))
        if allowed_markets:
            stmt = stmt.where(Instrument.market.in_(allowed_markets))
        stmt = stmt.limit(20)

        instruments = (await self.db.execute(stmt)).scalars().all()

        global_alloc = strategy.global_allocation or {}
        equity_ratio = float(global_alloc.get("equity_ratio", 0.6))
        bond_ratio = float(global_alloc.get("bond_ratio", 0.3))
        cash_ratio = float(global_alloc.get("cash_ratio", 0.1))

        # 归一化大类配比
        total_alloc = equity_ratio + bond_ratio + cash_ratio
        if total_alloc > 0:
            equity_ratio /= total_alloc
            bond_ratio /= total_alloc
            cash_ratio /= total_alloc

        equity_instruments = [
            i for i in instruments
            if i.asset_type in ("etf", "mutual_fund") and i.market in allowed_markets
        ]
        target_weights: list[dict] = []

        conc_limits = mandate.concentration_limits if mandate else {}
        max_single = float(conc_limits.get("max_single_asset", 0.3)) if conc_limits else 0.3

        if equity_instruments:
            raw = equity_ratio / len(equity_instruments)
            for inst in equity_instruments:
                weight = min(raw, max_single)
                target_weights.append({
                    "instrument_id": inst.id,
                    "symbol": inst.symbol,
                    "name": inst.name,
                    "weight": weight,
                    "target_value": 0,
                    "current_weight": 0,
                    "delta": 0,
                })

        # 现金桶（虚拟）
        if cash_ratio > 0:
            target_weights.append({
                "instrument_id": "CASH",
                "symbol": "CASH",
                "name": "现金",
                "weight": cash_ratio,
                "target_value": 0,
                "current_weight": 0,
                "delta": 0,
            })

        # 权重归一化
        w_sum = sum(tw["weight"] for tw in target_weights) or 1.0
        for tw in target_weights:
            tw["weight"] = round(tw["weight"] / w_sum, 4)
        # 修正浮点误差到 1.0
        residual = round(1.0 - sum(tw["weight"] for tw in target_weights), 4)
        if target_weights and residual != 0:
            target_weights[0]["weight"] = round(target_weights[0]["weight"] + residual, 4)

        total_value = float(holding.total_market_value) if holding and holding.total_market_value else 500000.0
        if total_value <= 0:
            total_value = 500000.0

        if holding and holding.positions:
            current_map = {
                p["instrument_id"]: p for p in holding.positions if "instrument_id" in p
            }
            for tw in target_weights:
                if tw["instrument_id"] in current_map:
                    tw["current_weight"] = float(current_map[tw["instrument_id"]].get("weight", 0) or 0)
                tw["delta"] = round(tw["weight"] - tw["current_weight"], 4)
                tw["target_value"] = round(tw["weight"] * total_value, 2)
        else:
            for tw in target_weights:
                tw["delta"] = tw["weight"]
                tw["target_value"] = round(tw["weight"] * total_value, 2)

        constraint_report = self._check_constraints(target_weights, mandate, holding, cash_ratio)

        # 简化风险指标：用权益占比估算
        risk_metrics = {
            "expected_return": round(0.03 + equity_ratio * 0.08, 4),
            "expected_volatility": round(0.04 + equity_ratio * 0.14, 4),
            "sharpe_ratio": round((0.03 + equity_ratio * 0.08 - 0.02) / max(0.04 + equity_ratio * 0.14, 0.01), 4),
            "max_drawdown": round(-(0.05 + equity_ratio * 0.20), 4),
            "var_95": round(-(0.02 + equity_ratio * 0.04), 4),
        }

        rebalance_plan = []
        for tw in target_weights:
            if tw["symbol"] == "CASH":
                continue
            if abs(tw["delta"]) > 0.01:
                est = abs(tw["delta"]) * total_value
                rebalance_plan.append({
                    "instrument_id": tw["instrument_id"],
                    "symbol": tw["symbol"],
                    "action": "buy" if tw["delta"] > 0 else "sell",
                    "quantity": 0,
                    "estimated_value": round(est, 2),
                    "priority": 1 if abs(tw["delta"]) > 0.05 else 2,
                    "reason": f"{'增加' if tw['delta'] > 0 else '减少'}{tw['symbol']}配置至目标权重",
                })

        constructible = True
        constructible_reason = None
        if holding and float(holding.unresolved_weight or 0) > 0.15:
            constructible = False
            constructible_reason = f"未解析持仓占比 {float(holding.unresolved_weight):.0%} 超过 15% 阈值"
        elif not constraint_report.get("passed_all", True):
            constructible = False
            constructible_reason = "约束校验未通过"
        elif not equity_instruments:
            constructible = False
            constructible_reason = "可用资产池为空，请先导入 instruments 主数据"

        p_result = await self.db.execute(
            select(TargetPortfolio)
            .where(TargetPortfolio.user_id == user_id)
            .order_by(TargetPortfolio.version.desc())
            .limit(1)
        )
        latest_p = p_result.scalar_one_or_none()
        new_version = (latest_p.version + 1) if latest_p else 1

        if not market_ctx:
            # 无市场环境时仍允许 draft，但标记数据覆盖率
            market_context_id = str(uuid.uuid4())
            data_coverage = Decimal("0.5")
        else:
            market_context_id = market_ctx.id
            data_coverage = Decimal("0.95")

        portfolio = TargetPortfolio(
            id=str(uuid.uuid4()),
            version=new_version,
            user_id=user_id,
            strategy_proposal_id=strategy.id,
            mandate_version=strategy.mandate_version,
            profile_version=mandate.profile_version if mandate else 1,
            holding_snapshot_version=holding.version if holding else 0,
            market_context_id=market_context_id,
            target_weights=target_weights,
            constraint_report=constraint_report,
            risk_metrics=risk_metrics,
            rebalance_plan=rebalance_plan,
            total_expected_cost=Decimal(str(round(len(rebalance_plan) * 5.0, 2))),
            total_expected_slippage=Decimal(str(round(sum(p["estimated_value"] for p in rebalance_plan) * 0.0005, 2))),
            constructible=constructible,
            constructible_reason=constructible_reason,
            data_coverage=data_coverage,
            status="draft",
        )
        self.db.add(portfolio)
        await self.db.flush()
        return self._to_dict(portfolio)

    def _check_constraints(self, weights: list, mandate, holding, cash_ratio: float) -> dict:
        passed = []
        failed = []
        warnings = []

        conc_limits = mandate.concentration_limits if mandate else {}
        max_single = float(conc_limits.get("max_single_asset", 0.3)) if conc_limits else 0.3

        for w in weights:
            if w["symbol"] == "CASH":
                continue
            if w["weight"] > max_single + 1e-6:
                failed.append({
                    "rule": "max_single_asset",
                    "value": w["weight"],
                    "limit": max_single,
                    "severity": "critical",
                    "explanation": f"{w['symbol']} 权重 {w['weight']:.0%} 超过限制 {max_single:.0%}",
                })
            else:
                passed.append({
                    "rule": "max_single_asset",
                    "value": w["weight"],
                    "limit": max_single,
                    "note": f"{w['symbol']} 满足",
                })

        min_cash = 0.05
        if mandate and mandate.cash_boundary:
            min_cash = float(mandate.cash_boundary.get("min_cash_ratio", 0.05))
        if cash_ratio + 1e-6 >= min_cash:
            passed.append({"rule": "min_cash_ratio", "value": cash_ratio, "limit": min_cash})
        else:
            failed.append({
                "rule": "min_cash_ratio",
                "value": cash_ratio,
                "limit": min_cash,
                "severity": "critical",
            })

        unresolved = float(holding.unresolved_weight) if holding else 0.0
        if unresolved > 0.15:
            failed.append({
                "rule": "unresolved_weight",
                "value": unresolved,
                "limit": 0.15,
                "severity": "critical",
            })
        else:
            passed.append({"rule": "unresolved_weight", "value": unresolved, "limit": 0.15})

        total_w = sum(float(w["weight"]) for w in weights)
        if abs(total_w - 1.0) > 0.02:
            failed.append({
                "rule": "total_weight",
                "value": total_w,
                "limit": 1.0,
                "severity": "critical",
            })
        else:
            passed.append({"rule": "total_weight", "value": total_w, "limit": 1.0})

        return {
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "passed_all": len(failed) == 0,
        }

    def _to_dict(self, portfolio: TargetPortfolio) -> dict:
        return {
            "id": portfolio.id,
            "version": portfolio.version,
            "constructible": portfolio.constructible,
            "constructible_reason": portfolio.constructible_reason,
            "target_weights": portfolio.target_weights,
            "constraint_report": portfolio.constraint_report,
            "risk_metrics": portfolio.risk_metrics,
            "rebalance_plan": portfolio.rebalance_plan,
            "total_expected_cost": float(portfolio.total_expected_cost),
            "total_expected_slippage": float(portfolio.total_expected_slippage),
            "data_coverage": float(portfolio.data_coverage),
            "status": portfolio.status,
            "created_at": portfolio.created_at.isoformat() if portfolio.created_at else None,
        }
