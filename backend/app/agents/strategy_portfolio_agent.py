"""策略与组合 Agent - 生成资产配置策略、构建目标组合并制定再平衡计划"""

from app.agents.base import AgentPlugin, AgentInput, AgentOutput


# 当 context 中未提供资产池时的默认资产池
_DEFAULT_ASSET_POOL: dict = {
    "equity": {
        "a_shares": [
            {"symbol": "510300", "name": "沪深300ETF", "market": "a_shares", "volatility": 0.18, "expected_return": 0.08},
            {"symbol": "512100", "name": "中证1000ETF", "market": "a_shares", "volatility": 0.25, "expected_return": 0.10},
            {"symbol": "510050", "name": "上证50ETF", "market": "a_shares", "volatility": 0.16, "expected_return": 0.07},
        ],
        "us_stocks": [
            {"symbol": "SPY", "name": "S&P 500 ETF", "market": "us_stocks", "volatility": 0.15, "expected_return": 0.09},
            {"symbol": "QQQ", "name": "纳斯达克100 ETF", "market": "us_stocks", "volatility": 0.22, "expected_return": 0.12},
        ],
        "hk_stocks": [
            {"symbol": "2800.HK", "name": "盈富基金", "market": "hk_stocks", "volatility": 0.18, "expected_return": 0.08},
        ],
    },
    "bond": [
        {"symbol": "511010", "name": "国债ETF", "market": "bond", "volatility": 0.03, "expected_return": 0.03},
        {"symbol": "511260", "name": "十年国债ETF", "market": "bond", "volatility": 0.04, "expected_return": 0.035},
    ],
    "cash": [
        {"symbol": "MONEY_MARKET", "name": "货币基金", "market": "cash", "volatility": 0.001, "expected_return": 0.02},
    ],
}

# 权益资产在各市场间的默认分配比例
_DEFAULT_EQUITY_MARKET_SPLIT: dict[str, float] = {
    "a_shares": 0.40,
    "us_stocks": 0.35,
    "hk_stocks": 0.25,
}


class StrategyPortfolioAgent(AgentPlugin):
    """根据授权约束、市场情绪与用户心理状态生成配置策略与目标组合"""

    @property
    def name(self) -> str:
        return "strategy_portfolio_agent"

    @property
    def capabilities(self) -> list[str]:
        return ["strategy_generation", "portfolio_construction", "rebalance_planning"]

    async def execute(self, input: AgentInput) -> AgentOutput:
        try:
            mandate = input.context.get("mandate", {})
            risk_budget = mandate.get("risk_budget", {})
            max_drawdown = float(risk_budget.get("max_drawdown", 0.20))
            concentration_limits = mandate.get("concentration_limits", {})
            cash_boundary = mandate.get("cash_boundary", {})

            # --- Step 2: 根据最大回撤确定股/债/现金配置 ---
            if max_drawdown <= 0.10:
                profile = "conservative"
                equity_cap = 0.30
            elif max_drawdown <= 0.20:
                profile = "moderate"
                equity_cap = 0.60
            else:
                profile = "aggressive"
                equity_cap = 0.80

            equity_weight = equity_cap * 0.85
            remaining = 1.0 - equity_weight
            bond_weight = remaining * 0.75
            cash_weight = remaining * 0.25

            # --- Step 3: 根据市场情绪调整 (+/- 5%，不超过约束) ---
            market_sentiment = float(input.context.get("market_sentiment", 0.5))
            adjustment = (market_sentiment - 0.5) * 0.10
            equity_weight = max(0.0, min(equity_cap, equity_weight + adjustment))
            remaining = 1.0 - equity_weight
            cash_min = float(cash_boundary.get("min_ratio", 0.05))
            bond_weight = remaining * 0.75
            cash_weight = remaining * 0.25
            # 确保现金满足下限
            if cash_weight < cash_min:
                cash_weight = cash_min
                bond_weight = 1.0 - equity_weight - cash_weight

            global_allocation = {
                "profile": profile,
                "equity": round(equity_weight, 4),
                "bond": round(bond_weight, 4),
                "cash": round(cash_weight, 4),
                "max_drawdown_budget": max_drawdown,
            }

            # --- Step 4: 映射到具体资产 ---
            asset_pool = input.context.get("asset_pool", _DEFAULT_ASSET_POOL)
            market_split = input.context.get(
                "equity_market_split", _DEFAULT_EQUITY_MARKET_SPLIT
            )

            target_weights: dict[str, float] = {}
            market_allocation: dict[str, float] = {}

            # 权益资产分配到各市场
            equity_pool = asset_pool.get("equity", {})
            for market_key, split_ratio in market_split.items():
                instruments = equity_pool.get(market_key, [])
                if not instruments:
                    continue
                market_weight = equity_weight * split_ratio
                market_allocation[f"equity.{market_key}"] = round(market_weight, 4)
                per_instrument = market_weight / len(instruments)
                for inst in instruments:
                    target_weights[inst["symbol"]] = round(per_instrument, 4)

            # 债券资产均匀分配
            bond_instruments = asset_pool.get("bond", [])
            if bond_instruments:
                per_bond = bond_weight / len(bond_instruments)
                market_allocation["bond"] = round(bond_weight, 4)
                for inst in bond_instruments:
                    target_weights[inst["symbol"]] = round(per_bond, 4)

            # 现金
            cash_instruments = asset_pool.get("cash", [])
            if cash_instruments:
                market_allocation["cash"] = round(cash_weight, 4)
                for inst in cash_instruments:
                    target_weights[inst["symbol"]] = round(cash_weight, 4)

            # 归一化（处理浮点累积误差）
            total = sum(target_weights.values())
            if total > 0:
                target_weights = {k: round(v / total, 4) for k, v in target_weights.items()}

            # 构建 instruments 元数据字典供计算使用
            instruments_meta: dict[str, dict] = {}
            for category_pool in list(asset_pool.get("equity", {}).values()) + [
                asset_pool.get("bond", []),
                asset_pool.get("cash", []),
            ]:
                for inst in category_pool:
                    instruments_meta[inst["symbol"]] = inst

            # --- Step 5-6: 计算再平衡计划与约束检查 ---
            from app.agents.tools.portfolio_calc import (
                calculate_risk_metrics,
                calculate_rebalance_plan,
                check_constraints,
            )

            current_portfolio = input.context.get("current_portfolio", {})
            rebalance_plan = calculate_rebalance_plan(current_portfolio, target_weights)

            max_single = float(concentration_limits.get("max_single_asset", 0.30))
            constraint_mandate = {
                "max_single_asset": max_single,
                "cash_ratio_min": cash_min,
                "cash_symbols": [inst["symbol"] for inst in asset_pool.get("cash", [])],
            }
            constraint_report = check_constraints(target_weights, constraint_mandate)

            # --- Step 7: 风险指标与情景分析 ---
            risk_metrics = calculate_risk_metrics(target_weights, instruments_meta)
            risk_scenarios = self._generate_risk_scenarios(risk_metrics)

            return AgentOutput(
                agent_name=self.name,
                status="success",
                data={
                    "global_allocation": global_allocation,
                    "market_allocation": market_allocation,
                    "target_weights": [
                        {"symbol": s, "weight": w} for s, w in target_weights.items()
                    ],
                    "rebalance_plan": rebalance_plan,
                    "constraint_report": constraint_report,
                    "risk_metrics": risk_metrics,
                    "risk_scenarios": risk_scenarios,
                },
                trace={
                    "profile": profile,
                    "max_drawdown": max_drawdown,
                    "market_sentiment": market_sentiment,
                    "instruments_count": len(target_weights),
                },
            )
        except Exception as e:
            return AgentOutput(
                agent_name=self.name,
                status="failed",
                error=str(e),
            )

    @staticmethod
    def _generate_risk_scenarios(risk_metrics: dict) -> list[dict]:
        """生成基础/乐观/悲观三种风险情景"""
        exp_ret = float(risk_metrics.get("expected_return", 0.06))
        vol = float(risk_metrics.get("portfolio_volatility", 0.12))

        return [
            {
                "name": "base",
                "expected_return": round(exp_ret, 4),
                "expected_volatility": round(vol, 4),
                "probability": 0.50,
            },
            {
                "name": "optimistic",
                "expected_return": round(exp_ret + vol, 4),
                "expected_volatility": round(vol * 0.7, 4),
                "probability": 0.25,
            },
            {
                "name": "pessimistic",
                "expected_return": round(exp_ret - vol, 4),
                "expected_volatility": round(vol * 1.3, 4),
                "probability": 0.25,
            },
        ]

    async def health_check(self) -> dict:
        return {"status": "healthy"}


def register():
    from app.plugins.registry import agent_registry
    agent_registry.register("strategy_portfolio_agent", StrategyPortfolioAgent)
