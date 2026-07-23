"""数据查询工具 - 供 Agent 查询市场行情与资产基本信息"""

from datetime import date

from app.dependencies import get_data_provider


async def query_market_data(symbol: str, start: date, end: date) -> list[dict]:
    """查询指定标的在日期区间内的市场行情数据

    Args:
        symbol: 标的代码
        start: 开始日期
        end: 结束日期

    Returns:
        行情数据列表，每条包含 date/open/high/low/close/volume 等字段
    """
    provider = get_data_provider()
    return await provider.get_market_data(symbol, start, end)


async def query_instrument(symbol: str) -> dict:
    """查询指定标的的基本信息与财务数据

    Args:
        symbol: 标的代码

    Returns:
        包含 symbol/name/type/total_assets/nav_per_share 等字段的字典
    """
    provider = get_data_provider()
    return await provider.get_financial_data(symbol)
