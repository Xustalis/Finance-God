"""固定基点滑点模型：price * 0.0005（5 bps）"""

from decimal import Decimal

from app.plugins.slippage_models.base import SlippageModel


class FixedBpsSlippageModel(SlippageModel):
    """固定 5bps 滑点"""

    @property
    def name(self) -> str:
        return "fixed_bps"

    def calculate(self, quantity: Decimal, price: Decimal, direction: str) -> Decimal:
        return price * Decimal("0.0005")


def register():
    from app.plugins.registry import slippage_model_registry
    slippage_model_registry.register("fixed_bps", FixedBpsSlippageModel)
