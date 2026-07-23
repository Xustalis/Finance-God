"""数据提供者抽象基类"""

from abc import ABC, abstractmethod
from datetime import date

class DataProvider(ABC):
    @abstractmethod
    async def get_market_data(self, symbol: str, start: date, end: date) -> list[dict]: ...
    
    @abstractmethod
    async def get_financial_data(self, symbol: str) -> dict: ...
    
    @abstractmethod
    async def get_index_data(self, index_code: str, start: date, end: date) -> list[dict]: ...
    
    @abstractmethod
    async def get_macro_data(self, indicator: str, start: date, end: date) -> list[dict]: ...
    
    @abstractmethod
    async def get_calendar(self, market: str) -> list: ...
