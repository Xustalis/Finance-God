"""研究工具 - 基于 LLM 生成结构化研究备忘录"""

import json

from app.dependencies import get_llm_provider
from app.plugins.llm_providers.base import LLMRequest


async def generate_research_memo(instrument_id: str, symbol: str, name: str) -> dict:
    """为指定资产生成结构化研究备忘录

    Args:
        instrument_id: 资产唯一标识
        symbol: 标的代码
        name: 资产名称

    Returns:
        包含 facts/bull_case/bear_case/risks/unknowns 的研究备忘录字典
    """
    llm = get_llm_provider()

    system_prompt = (
        "你是一位专业的投资分析师。请基于给定资产信息生成结构化研究备忘录。\n"
        "输出 JSON 格式，包含以下字段：\n"
        '- facts: 已知事实列表，每项为字符串\n'
        '- bull_case: 看涨理由，格式 {"points": [...], "expected_return": 0.0}\n'
        '- bear_case: 看跌理由，格式 {"points": [...], "expected_return": 0.0}\n'
        '- risks: 风险因素列表，每项为字符串\n'
        '- unknowns: 未知因素列表，每项为字符串'
    )

    user_message = f"资产ID: {instrument_id}\n代码: {symbol}\n名称: {name}\n\n请生成研究备忘录。"

    request = LLMRequest(
        system_prompt=system_prompt,
        user_message=user_message,
        temperature=0.3,
    )

    response = await llm.complete(request)

    try:
        data = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        data = {}

    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "name": name,
        "facts": data.get("facts", []),
        "bull_case": data.get("bull_case", {"points": [], "expected_return": 0.0}),
        "bear_case": data.get("bear_case", {"points": [], "expected_return": 0.0}),
        "risks": data.get("risks", []),
        "unknowns": data.get("unknowns", []),
    }
