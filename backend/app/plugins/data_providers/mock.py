"""Mock 数据提供者 - 返回合理的测试数据（行情/财务/指数/宏观/日历）"""

import math
from datetime import date, timedelta

from app.plugins.data_providers.base import DataProvider


class MockDataProvider(DataProvider):
    """生成模拟 ETF 行情与指数/宏观数据，便于无外部依赖地测试链路"""

    async def get_market_data(self, symbol: str, start: date, end: date) -> list[dict]:
        rows: list[dict] = []
        base_price = 10.0
        cur = start
        i = 0
        while cur <= end:
            close = round(base_price + math.sin(i / 5.0) * 0.5 + i * 0.01, 4)
            rows.append({
                "symbol": symbol,
                "date": cur.isoformat(),
                "open": round(close - 0.05, 4),
                "high": round(close + 0.1, 4),
                "low": round(close - 0.1, 4),
                "close": close,
                "volume": 1_000_000 + (i % 7) * 100_000,
            })
            cur += timedelta(days=1)
            i += 1
        return rows

    async def get_financial_data(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "name": f"Mock ETF {symbol}",
            "type": "etf",
            "total_assets": 5_000_000_000,
            "nav_per_share": 10.25,
            "expense_ratio": 0.0015,
            "top_holdings": [
                {"code": "600519", "name": "贵州茅台", "weight": 0.12},
                {"code": "601318", "name": "中国平安", "weight": 0.08},
                {"code": "000858", "name": "五粮液", "weight": 0.06},
            ],
        }

    async def get_index_data(self, index_code: str, start: date, end: date) -> list[dict]:
        rows: list[dict] = []
        base = 3000.0
        cur = start
        i = 0
        while cur <= end:
            close = round(base + math.sin(i / 7.0) * 30 + i * 0.5, 4)
            rows.append({
                "index_code": index_code,
                "date": cur.isoformat(),
                "open": round(close - 5, 4),
                "high": round(close + 10, 4),
                "low": round(close - 10, 4),
                "close": close,
                "volume": 50_000_000,
            })
            cur += timedelta(days=1)
            i += 1
        return rows

    async def get_macro_data(self, indicator: str, start: date, end: date) -> list[dict]:
        rows: list[dict] = []
        cur = start
        i = 0
        while cur <= end:
            value = round(100 + math.sin(i / 12.0) * 2 + i * 0.01, 4)
            rows.append({
                "indicator": indicator,
                "date": cur.isoformat(),
                "value": value,
                "unit": "%",
            })
            cur += timedelta(days=30)
            i += 1
        return rows

    async def get_calendar(self, market: str) -> list:
        return [
            {"market": market, "date": "2026-01-01", "event": "元旦", "is_open": False},
            {"market": market, "date": "2026-02-17", "event": "春节", "is_open": False},
            {"market": market, "date": "2026-04-04", "event": "清明节", "is_open": False},
            {"market": market, "date": "2026-05-01", "event": "劳动节", "is_open": False},
            {"market": market, "date": "2026-06-19", "event": "端午节", "is_open": False},
            {"market": market, "date": "2026-09-25", "event": "中秋节", "is_open": False},
            {"market": market, "date": "2026-10-01", "event": "国庆节", "is_open": False},
        ]


def register():
    from app.plugins.registry import data_provider_registry
    data_provider_registry.register("mock", MockDataProvider)
