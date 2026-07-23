"""风险 Agent - 执行三阶段风险检查（合规/组合/执行后）"""

from app.agents.base import AgentPlugin, AgentInput, AgentOutput


class RiskAgent(AgentPlugin):
    """调用 RiskEngine 执行指定阶段的风险检查，返回通过/阻断结果"""

    @property
    def name(self) -> str:
        return "risk_agent"

    @property
    def capabilities(self) -> list[str]:
        return ["risk_check_stage_1", "risk_check_stage_2", "risk_check_stage_3"]

    async def execute(self, input: AgentInput) -> AgentOutput:
        try:
            from app.risk.engine import RiskEngine

            stage = int(input.context.get("stage", 1))
            if stage not in (1, 2, 3):
                return AgentOutput(
                    agent_name=self.name,
                    status="failed",
                    error=f"未知的风险检查阶段: {stage}，有效值为 1/2/3",
                )

            engine = RiskEngine()
            result = engine.run_checks(stage=stage, context=input.context)

            # 兼容 dict 与对象两种返回类型
            if isinstance(result, dict):
                results = result.get("results", [])
                passed = result.get("passed", True)
                blocked_by = result.get("blocked_by", [])
            else:
                results = getattr(result, "results", [])
                passed = getattr(result, "passed", True)
                blocked_by = getattr(result, "blocked_by", [])

            status = "success" if passed else "blocked"

            return AgentOutput(
                agent_name=self.name,
                status=status,
                data={
                    "stage": stage,
                    "results": results,
                    "passed": passed,
                    "blocked_by": blocked_by,
                },
                trace={
                    "stage": stage,
                    "checks_run": len(results) if isinstance(results, list) else 0,
                },
            )
        except ImportError:
            return AgentOutput(
                agent_name=self.name,
                status="failed",
                error="RiskEngine 不可用：app.risk.engine 模块未找到",
            )
        except Exception as e:
            return AgentOutput(
                agent_name=self.name,
                status="failed",
                error=str(e),
            )

    async def health_check(self) -> dict:
        try:
            from app.risk.engine import RiskEngine
            engine = RiskEngine()
            rules_loaded = getattr(engine, "rules_count", None)
            if rules_loaded is None and hasattr(engine, "rules"):
                rules_loaded = len(engine.rules)
            return {
                "status": "healthy",
                "rules_loaded": rules_loaded if rules_loaded is not None else 0,
            }
        except Exception:
            return {"status": "degraded", "rules_loaded": 0}


def register():
    from app.plugins.registry import agent_registry
    agent_registry.register("risk_agent", RiskAgent)
