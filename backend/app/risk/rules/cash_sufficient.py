"""R3-01 现金充足"""

from decimal import Decimal

from app.risk.base import RiskRule


class CashSufficientRule(RiskRule):
    @property
    def rule_id(self) -> str:
        return "R3-01"

    @property
    def name(self) -> str:
        return "现金充足"

    @property
    def stage(self) -> int:
        return 3

    def check(self, context: dict) -> dict:
        direction = context.get("direction", "buy")
        if direction != "buy":
            return {
                "passed": True,
                "rule_id": self.rule_id,
                "name": self.name,
                "explanation": "卖出无需现金校验",
            }
        cash = Decimal(str(context.get("cash_balance", 0)))
        order_value = Decimal(str(context.get("order_value", 0)))
        fee = Decimal(str(context.get("fee", 0)))
        ok = cash >= order_value + fee
        return {
            "passed": ok,
            "rule_id": self.rule_id,
            "name": self.name,
            "explanation": (
                f"现金 {cash} 足够覆盖 {order_value + fee}"
                if ok
                else f"现金 {cash} 不足，需要 {order_value + fee}"
            ),
        }


def register():
    from app.plugins.registry import rule_registry
    rule_registry.register("cash_sufficient", CashSufficientRule)
