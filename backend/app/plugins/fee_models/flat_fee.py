"""固定费率手续费模型：max(5, 成交金额 * 0.0003)"""

from decimal import Decimal

from app.plugins.fee_models.base import FeeModel


class FlatFeeModel(FeeModel):
    """按成交金额的 3bp 计费，最低 5 元"""

    @property
    def name(self) -> str:
        return "flat"

    def calculate(self, quantity: Decimal, price: Decimal, direction: str) -> Decimal:
        notional = quantity * price
        fee = notional * Decimal("0.0003")
        minimum = Decimal("5")
        return max(fee, minimum)


def register():
    from app.plugins.registry import fee_model_registry
    fee_model_registry.register("flat", FlatFeeModel)
