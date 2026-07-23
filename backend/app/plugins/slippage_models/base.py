"""滑点模型抽象基类"""

from abc import ABC, abstractmethod
from decimal import Decimal

class SlippageModel(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    def calculate(self, quantity: Decimal, price: Decimal, direction: str) -> Decimal: ...
