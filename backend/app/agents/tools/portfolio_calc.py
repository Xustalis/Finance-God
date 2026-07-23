"""组合计算工具 - 风险指标计算、再平衡计划生成与约束检查"""

from typing import Any


def calculate_risk_metrics(weights: dict[str, float], instruments: dict[str, dict]) -> dict:
    """计算组合风险指标

    Args:
        weights: 标的代码 -> 权重的字典
        instruments: 标的代码 -> 元数据的字典，元数据应包含 volatility 和 expected_return

    Returns:
        包含 portfolio_volatility/portfolio_var_95/expected_return/sharpe_ratio/
        max_drawdown_estimate/diversification_ratio 的字典
    """
    risk_free_rate = 0.02

    # 组合波动率（简化：假设资产间不相关，使用加权方差平方根）
    weighted_var = 0.0
    for symbol, weight in weights.items():
        vol = float(instruments.get(symbol, {}).get("volatility", 0.20))
        weighted_var += (weight ** 2) * (vol ** 2)
    portfolio_volatility = weighted_var ** 0.5

    # VaR 95%（单边）
    portfolio_var_95 = 1.65 * portfolio_volatility

    # 期望收益
    expected_return = 0.0
    for symbol, weight in weights.items():
        ret = float(instruments.get(symbol, {}).get("expected_return", 0.06))
        expected_return += weight * ret

    # 夏普比率
    sharpe_ratio = (
        (expected_return - risk_free_rate) / portfolio_volatility
        if portfolio_volatility > 0
        else 0.0
    )

    # 最大回撤估计（简化：2 倍波动率）
    max_drawdown_estimate = 2.0 * portfolio_volatility

    # 分散化比率（加权平均波动率 / 组合波动率）
    weighted_avg_vol = 0.0
    for symbol, weight in weights.items():
        vol = float(instruments.get(symbol, {}).get("volatility", 0.20))
        weighted_avg_vol += abs(weight) * vol
    diversification_ratio = (
        weighted_avg_vol / portfolio_volatility if portfolio_volatility > 0 else 1.0
    )

    return {
        "portfolio_volatility": round(portfolio_volatility, 4),
        "portfolio_var_95": round(portfolio_var_95, 4),
        "expected_return": round(expected_return, 4),
        "sharpe_ratio": round(sharpe_ratio, 4),
        "max_drawdown_estimate": round(max_drawdown_estimate, 4),
        "diversification_ratio": round(diversification_ratio, 4),
    }


def calculate_rebalance_plan(
    current: dict[str, float], target: dict[str, float]
) -> list[dict[str, Any]]:
    """生成再平衡计划

    Args:
        current: 标的代码 -> 当前权重的字典
        target: 标的代码 -> 目标权重的字典

    Returns:
        再平衡操作列表，每项包含 symbol/action/current_weight/target_weight/delta_weight，
        按绝对变化量降序排列
    """
    all_symbols = set(current.keys()) | set(target.keys())
    plan: list[dict[str, Any]] = []

    for symbol in all_symbols:
        cur = float(current.get(symbol, 0.0))
        tgt = float(target.get(symbol, 0.0))
        delta = tgt - cur
        if abs(delta) < 0.001:
            continue
        plan.append({
            "symbol": symbol,
            "action": "buy" if delta > 0 else "sell",
            "current_weight": round(cur, 4),
            "target_weight": round(tgt, 4),
            "delta_weight": round(delta, 4),
        })

    plan.sort(key=lambda x: abs(x["delta_weight"]), reverse=True)
    return plan


def check_constraints(weights: dict[str, float], mandate: dict) -> dict:
    """检查组合权重是否满足授权约束

    Args:
        weights: 标的代码 -> 权重的字典
        mandate: 包含 max_single_asset/cash_ratio_min/cash_symbols 的约束字典

    Returns:
        包含 passed/violations/total_checks/passed_checks 的字典
    """
    violations: list[dict[str, Any]] = []

    # 单资产集中度检查
    max_single = float(mandate.get("max_single_asset", 0.30))
    for symbol, weight in weights.items():
        if weight > max_single:
            violations.append({
                "rule": "max_single_asset",
                "symbol": symbol,
                "value": round(weight, 4),
                "limit": max_single,
                "message": f"{symbol} 权重 {weight:.1%} 超过单资产上限 {max_single:.1%}",
            })

    # 现金比例下限检查
    cash_ratio_min = float(mandate.get("cash_ratio_min", 0.05))
    cash_symbols = mandate.get("cash_symbols", ["MONEY_MARKET"])
    cash_weight = sum(float(weights.get(s, 0.0)) for s in cash_symbols)
    if cash_weight < cash_ratio_min:
        violations.append({
            "rule": "cash_ratio_min",
            "value": round(cash_weight, 4),
            "limit": cash_ratio_min,
            "message": f"现金比例 {cash_weight:.1%} 低于下限 {cash_ratio_min:.1%}",
        })

    # 总权重检查
    total_weight = sum(float(w) for w in weights.values())
    if abs(total_weight - 1.0) > 0.02:
        violations.append({
            "rule": "total_weight",
            "value": round(total_weight, 4),
            "limit": 1.0,
            "message": f"总权重 {total_weight:.1%} 偏离 100%",
        })

    total_checks = len(weights) + 2  # 每个资产 + 现金 + 总权重
    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "total_checks": total_checks,
        "passed_checks": total_checks - len(violations),
    }
