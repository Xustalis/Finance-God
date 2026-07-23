"""风控规则引擎 - 三段校验编排"""

from typing import Any

from app.plugins.registry import rule_registry


class RiskEngine:
    """按 stage 执行已注册规则"""

    def __init__(self):
        self._rules: list = []
        self._load_rules()

    def _load_rules(self) -> None:
        self._rules = []
        for name in rule_registry.list_available():
            try:
                self._rules.append(rule_registry.get(name))
            except Exception:
                continue

    @property
    def rules(self) -> list:
        return self._rules

    @property
    def rules_count(self) -> int:
        return len(self._rules)

    def run_checks(self, stage: int, context: dict[str, Any] | None = None) -> dict:
        context = context or {}
        results = []
        blocked_by = []
        passed = True

        for rule in self._rules:
            rule_stage = getattr(rule, "stage", 1)
            if rule_stage != stage:
                continue
            try:
                result = rule.check(context)
            except Exception as e:
                result = {
                    "passed": False,
                    "rule_id": getattr(rule, "rule_id", "unknown"),
                    "name": getattr(rule, "name", type(rule).__name__),
                    "explanation": f"规则执行异常: {e}",
                }
            results.append(result)
            if not result.get("passed", False):
                passed = False
                blocked_by.append(result)

        # 无规则时默认通过（MVP），但记录空检查
        if not results:
            results.append({
                "passed": True,
                "rule_id": "NO_RULES",
                "name": "无已注册规则",
                "explanation": f"stage={stage} 无规则，默认通过",
            })

        return {
            "stage": stage,
            "passed": passed,
            "results": results,
            "blocked_by": blocked_by,
        }
