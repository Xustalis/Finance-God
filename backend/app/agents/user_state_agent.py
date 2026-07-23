"""用户状态 Agent - 分析用户心理状态、认知偏误与冷静期评估"""

from app.agents.base import AgentPlugin, AgentInput, AgentOutput


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class UserStateAgent(AgentPlugin):
    """分析用户行为信号，评估焦虑/贪婪/冲动水平，检测认知偏误，并决定是否触发冷静期"""

    @property
    def name(self) -> str:
        return "user_state_agent"

    @property
    def capabilities(self) -> list[str]:
        return ["mental_state_analysis", "bias_detection", "cooldown_assessment"]

    async def execute(self, input: AgentInput) -> AgentOutput:
        try:
            signals = input.context.get("behavioral_signals", {})
            mental_state = self._calculate_mental_state(signals)
            cognitive_biases = self._detect_biases(signals)

            anxiety = mental_state["anxiety_level"]
            impulsivity = mental_state["impulsivity"]
            cooldown_active = anxiety > 0.7 or impulsivity > 0.8

            cooldown_reason = None
            cooldown_type = None
            if cooldown_active:
                reasons = []
                if anxiety > 0.7:
                    reasons.append(f"焦虑水平过高 ({anxiety:.2f})")
                    cooldown_type = "anxiety"
                if impulsivity > 0.8:
                    reasons.append(f"冲动性过高 ({impulsivity:.2f})")
                    if cooldown_type is None:
                        cooldown_type = "impulsivity"
                cooldown_reason = "；".join(reasons)

            return AgentOutput(
                agent_name=self.name,
                status="success",
                data={
                    "mental_state": mental_state,
                    "cognitive_biases": cognitive_biases,
                    "cooldown_active": cooldown_active,
                    "cooldown_reason": cooldown_reason,
                    "cooldown_type": cooldown_type,
                },
                trace={
                    "signals_received": list(signals.keys()),
                    "signal_count": len(signals),
                },
            )
        except Exception as e:
            return AgentOutput(
                agent_name=self.name,
                status="failed",
                error=str(e),
            )

    def _calculate_mental_state(self, signals: dict) -> dict:
        """基于加权规则计算焦虑、贪婪、冲动水平（0-1）"""
        recent_loss_ratio = _clamp(float(signals.get("recent_loss_ratio", 0.0)))
        position_change_freq = _clamp(float(signals.get("position_change_frequency", 0.0)))
        repeated_actions = _clamp(float(signals.get("repeated_similar_actions", 0.0)))
        concentration_growth = _clamp(float(signals.get("concentration_in_growth", 0.0)))
        leverage_usage = _clamp(float(signals.get("leverage_usage", 0.0)))
        chasing_winners = _clamp(float(signals.get("chasing_winners", 0.0)))
        avg_holding_days = float(signals.get("avg_holding_period_days", 30.0))
        plan_deviation = _clamp(float(signals.get("plan_deviation", 0.0)))
        after_hours_ratio = _clamp(float(signals.get("after_hours_trading_ratio", 0.0)))

        # 焦虑：亏损比例 + 频繁调仓 + 重复操作
        anxiety_level = _clamp(
            0.40 * recent_loss_ratio
            + 0.30 * position_change_freq
            + 0.30 * repeated_actions
        )

        # 贪婪：成长股集中 + 杠杆 + 追涨
        greed_level = _clamp(
            0.35 * concentration_growth
            + 0.35 * leverage_usage
            + 0.30 * chasing_winners
        )

        # 冲动：短持有期 + 偏离计划 + 盘后交易
        holding_factor = 1.0 / (1.0 + max(avg_holding_days, 0.0) / 7.0)
        impulsivity = _clamp(
            0.35 * holding_factor
            + 0.35 * plan_deviation
            + 0.30 * after_hours_ratio
        )

        return {
            "anxiety_level": round(anxiety_level, 4),
            "greed_level": round(greed_level, 4),
            "impulsivity": round(impulsivity, 4),
            "overall_state": self._classify_state(anxiety_level, greed_level, impulsivity),
        }

    @staticmethod
    def _classify_state(anxiety: float, greed: float, impulsivity: float) -> str:
        if anxiety > 0.7 or impulsivity > 0.8:
            return "distressed"
        if greed > 0.7:
            return "overly_greedy"
        if anxiety > 0.4 or impulsivity > 0.5:
            return "elevated"
        return "stable"

    def _detect_biases(self, signals: dict) -> list[dict]:
        """检测五种认知偏误：损失厌恶、过度自信、羊群效应、锚定效应、处置效应"""
        recent_loss_ratio = _clamp(float(signals.get("recent_loss_ratio", 0.0)))
        repeated_actions = _clamp(float(signals.get("repeated_similar_actions", 0.0)))
        concentration_growth = _clamp(float(signals.get("concentration_in_growth", 0.0)))
        leverage_usage = _clamp(float(signals.get("leverage_usage", 0.0)))
        position_change_freq = _clamp(float(signals.get("position_change_frequency", 0.0)))
        chasing_winners = _clamp(float(signals.get("chasing_winners", 0.0)))
        avg_holding_days = float(signals.get("avg_holding_period_days", 30.0))
        plan_deviation = _clamp(float(signals.get("plan_deviation", 0.0)))

        biases: list[dict] = []

        # 1. 损失厌恶 - 持有亏损、对亏损过度敏感
        score = _clamp(0.60 * recent_loss_ratio + 0.40 * repeated_actions)
        biases.append({
            "name": "loss_aversion",
            "detected": score > 0.5,
            "score": round(score, 4),
            "evidence": "近期亏损比例较高且存在重复类似操作" if score > 0.5 else None,
        })

        # 2. 过度自信 - 高集中度、杠杆、频繁交易
        score = _clamp(0.40 * concentration_growth + 0.30 * leverage_usage + 0.30 * position_change_freq)
        biases.append({
            "name": "overconfidence",
            "detected": score > 0.5,
            "score": round(score, 4),
            "evidence": "成长股集中度高、杠杆使用频繁、交易活跃" if score > 0.5 else None,
        })

        # 3. 羊群效应 - 追涨、重复热门操作
        score = _clamp(0.60 * chasing_winners + 0.40 * repeated_actions)
        biases.append({
            "name": "herding",
            "detected": score > 0.5,
            "score": round(score, 4),
            "evidence": "追涨近期表现优异的资产、跟随市场热点" if score > 0.5 else None,
        })

        # 4. 锚定效应 - 围绕特定价位操作、偏离计划
        score = _clamp(0.50 * plan_deviation + 0.50 * repeated_actions)
        biases.append({
            "name": "anchoring",
            "detected": score > 0.5,
            "score": round(score, 4),
            "evidence": "偏离既定计划、围绕特定价格点位重复操作" if score > 0.5 else None,
        })

        # 5. 处置效应 - 卖盈持亏（持有期短 + 亏损比例高）
        holding_factor = 1.0 / (1.0 + max(avg_holding_days, 0.0) / 14.0)
        score = _clamp(0.50 * recent_loss_ratio + 0.50 * holding_factor)
        biases.append({
            "name": "disposition_effect",
            "detected": score > 0.5,
            "score": round(score, 4),
            "evidence": "持有亏损仓位时间较长、倾向过早卖出盈利仓位" if score > 0.5 else None,
        })

        return biases

    async def health_check(self) -> dict:
        return {"status": "healthy"}


def register():
    from app.plugins.registry import agent_registry
    agent_registry.register("user_state_agent", UserStateAgent)
