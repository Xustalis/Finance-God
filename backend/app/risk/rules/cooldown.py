"""R2-04 冷静期拦截新订单"""

from app.risk.base import RiskRule


class CooldownRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "R2-04"

    @property
    def name(self) -> str:
        return "冷静期"

    @property
    def stage(self) -> int:
        return 2

    def check(self, context: dict) -> dict:
        cooldown = context.get("cooldown")
        if not cooldown:
            return {
                "passed": True,
                "rule_id": self.rule_id,
                "name": self.name,
                "explanation": "无活跃冷静期",
            }
        scope = {}
        if isinstance(cooldown, dict):
            scope = cooldown.get("affected_scope") or {}
            active = cooldown.get("status") == "active" or cooldown.get("active") is True
            reason = cooldown.get("trigger_reason") or cooldown.get("reason") or "冷静期生效"
        else:
            scope = getattr(cooldown, "affected_scope", None) or {}
            active = getattr(cooldown, "status", None) == "active"
            reason = getattr(cooldown, "trigger_reason", "冷静期生效")

        blocks_orders = scope.get("new_orders", True) if active else False
        ok = not (active and blocks_orders)
        return {
            "passed": ok,
            "rule_id": self.rule_id,
            "name": self.name,
            "explanation": "无订单阻断" if ok else str(reason),
        }


def register():
    from app.plugins.registry import rule_registry
    rule_registry.register("cooldown", CooldownRule)
