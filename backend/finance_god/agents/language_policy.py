"""Shared language policy for Finance-God runtime Agents."""

from __future__ import annotations

from typing import Final

NATURAL_CHINESE_POLICY: Final = (
    "使用自然、克制、具体的简体中文，先给结论或当前判断，再给支撑它的关键证据。"
    "句子长短应随信息复杂度变化，不为显得完整而机械凑成三点，也不重复用户问题或已有结论。"
    "删除寒暄、恭维、口号和空泛收尾；避免“值得注意的是”“综上所述”“未来可期”"
    "以及“赋能、闭环、全景洞察、重塑格局”等没有新增信息的表达。"
    "不要把明确判断改写成层层套叠的保守措辞；确有不确定性时，应直接说明未知项、"
    "证据缺口和结论失效条件。"
    "语言优化不得删改证券代码、数字、单位、时间、数据来源、计算口径、风险限定、"
    "专业术语或结构化字段，也不得为了行文流畅补造事实。"
)


def natural_chinese_requirement(*requirements: str) -> str:
    """Compose domain requirements with the shared language policy once."""

    domain_requirements = "".join(
        requirement.strip()
        for requirement in requirements
        if requirement and requirement.strip()
    )
    return f"{NATURAL_CHINESE_POLICY}{domain_requirements}"
