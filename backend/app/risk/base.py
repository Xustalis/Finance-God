"""风控规则抽象基类"""

from abc import ABC, abstractmethod
from typing import Any


class RiskRule(ABC):
    """单条风控规则"""

    @property
    @abstractmethod
    def rule_id(self) -> str: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def stage(self) -> int:
        """1=组合前 2=下单前 3=提交前"""
        return 1

    @abstractmethod
    def check(self, context: dict[str, Any]) -> dict:
        """返回 {passed, rule_id, name, explanation}"""
        ...
