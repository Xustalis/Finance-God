"""PandaAI 数据提供者 - 通过 httpx 调用 PandaAI API 的轻量封装"""

import json
from datetime import date

import httpx

from app.config import settings
from app.plugins.data_providers.base import DataProvider


class PandaAIDataProvider(DataProvider):
    """基于 PandaAI Cloud API 的数据提供者（自然语言查询的薄封装）"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.pandaai_api_key
        self.base_url = (base_url or "https://api.pandaai.org/v1").rstrip("/")

    async def get_market_data(self, symbol: str, start: date, end: date) -> list[dict]:
        prompt = (
            f"返回标的 {symbol} 从 {start.isoformat()} 到 {end.isoformat()} 的日线行情数据，"
            "字段包含 date/open/high/low/close/volume，输出 JSON 数组。"
        )
        return await self._query(prompt)

    async def get_financial_data(self, symbol: str) -> dict:
        prompt = f"返回标的 {symbol} 的基本面/财务数据，输出 JSON 对象。"
        return await self._query(prompt)

    async def get_index_data(self, index_code: str, start: date, end: date) -> list[dict]:
        prompt = (
            f"返回指数 {index_code} 从 {start.isoformat()} 到 {end.isoformat()} 的日数据，"
            "字段包含 date/open/high/low/close/volume，输出 JSON 数组。"
        )
        return await self._query(prompt)

    async def get_macro_data(self, indicator: str, start: date, end: date) -> list[dict]:
        prompt = (
            f"返回宏观经济指标 {indicator} 从 {start.isoformat()} 到 {end.isoformat()} 的数据，"
            "字段包含 date/value/unit，输出 JSON 数组。"
        )
        return await self._query(prompt)

    async def get_calendar(self, market: str) -> list:
        prompt = f"返回 {market} 市场的交易日历/节假日信息，输出 JSON 数组。"
        return await self._query(prompt)

    async def _query(self, prompt: str):
        """向 PandaAI 发送自然语言查询并解析 JSON 结果"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"prompt": prompt, "response_format": "json"}
        url = f"{self.base_url}/query"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        # 兼容多种返回结构：直接是列表/字典，或包在 data/result/answer 字段里
        if isinstance(data, (list, dict)):
            return data
        for key in ("data", "result", "answer", "output"):
            if isinstance(data, dict) and key in data:
                value = data[key]
                if isinstance(value, str):
                    try:
                        return json.loads(value)
                    except json.JSONDecodeError:
                        return value
                return value
        return data


def register():
    from app.plugins.registry import data_provider_registry
    data_provider_registry.register("pandaai", PandaAIDataProvider)
