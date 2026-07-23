"""R2-01 授权书有效"""

from app.risk.base import RiskRule


class MandateActiveRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "R2-01"

    @property
    def name(self) -> str:
        return "授权书有效"

    @property
    def stage(self) -> int:
        return 2

    def check(self, context: dict) -> dict:
        mandate = context.get("mandate") or {}
        status = mandate.get("status") if isinstance(mandate, dict) else getattr(mandate, "status", None)
        ok = status == "active"
        return {
            "passed": ok,
            "rule_id": self.rule_id,
            "name": self.name,
            "explanation": "授权书状态为 active" if ok else f"授权书状态无效: {status}",
        }


def register():
    from app.plugins.registry import rule_registry
    rule_registry.register("mandate_active", MandateActiveRule)
