"""问题兜底池：为六个画像维度各提供 1 条中性、确定性的兜底问题。

设计目标：
- 正常问诊由 AI 依据用户当前画像动态生成问题；本模块只作**极小兜底**，
  仅当 AI 调用失败或返回空/非法问题时使用，保证对话不中断。
- 每个维度只保留 1 条 initial / direct 的中性问题，不再维护多变体，
  以贯彻“少写模板、由 AI 思考该问什么”的产品方向。
- 保留 INITIAL_RISK_QUESTION 原文用于向后兼容（注意：本模块不 import
  ai_orchestrator，避免循环依赖）。
- ``select_question`` 是纯函数：同样输入返回同样输出，不使用随机数。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.onboarding import ProfileDimension

__all__ = [
    "QuestionTemplate",
    "QUESTION_TEMPLATES",
    "make_excerpt",
    "render_template",
    "select_question",
]

# 与 ai_orchestrator._content_excerpt 保持一致的截断长度
EXCERPT_LIMIT = 24

# 模板中含 {excerpt} 占位但没有可用摘要时的兜底填充
_EXCERPT_FALLBACK = "刚才聊到的内容"


@dataclass(frozen=True)
class QuestionTemplate:
    """单个问题模板。

    - template_id: 全局唯一标识
    - level: "initial" / "retry" / "deepened"
    - mode: "scenario" / "direct" / "metaphor"
    - content: 中文问题文本，可包含可选的 {excerpt} 占位符
    """

    template_id: str
    level: str
    mode: str
    content: str


# ---------------------------------------------------------------------------
# 模板池数据（顺序即确定性选择顺序）
# ---------------------------------------------------------------------------

QUESTION_TEMPLATES: dict[str, tuple[QuestionTemplate, ...]] = {
    # 每个维度仅保留 1 条中性 initial/direct 兜底问题；正常问诊由 AI 动态生成。
    ProfileDimension.RISK_TOLERANCE.value: (
        # 向后兼容：现有 INITIAL_RISK_QUESTION 原文
        QuestionTemplate(
            "rt_initial_direct_01",
            "initial",
            "direct",
            "如果这笔资金出现约15%的阶段性亏损，你更可能继续持有、减少投入，还是全部卖出？",
        ),
    ),
    ProfileDimension.LIQUIDITY_NEED.value: (
        QuestionTemplate(
            "ln_initial_direct_01",
            "initial",
            "direct",
            "这笔资金预计多久内可能需要取用？",
        ),
    ),
    ProfileDimension.INVESTMENT_GOAL.value: (
        QuestionTemplate(
            "ig_initial_direct_01",
            "initial",
            "direct",
            "你最希望这笔资金优先支持哪个生活目标？",
        ),
    ),
    ProfileDimension.LOSS_BEHAVIOR.value: (
        QuestionTemplate(
            "lb_initial_direct_01",
            "initial",
            "direct",
            "市场明显下跌时，你更可能持有、减仓还是卖出？",
        ),
    ),
    ProfileDimension.INVESTMENT_KNOWLEDGE.value: (
        QuestionTemplate(
            "ik_initial_direct_01",
            "initial",
            "direct",
            "你对常见投资产品和价格波动有多少实际了解？",
        ),
    ),
    ProfileDimension.INCOME_STABILITY.value: (
        QuestionTemplate(
            "is_initial_direct_01",
            "initial",
            "direct",
            "如果方便回答，你未来一年的收入稳定性大致如何？你也可以跳过。",
        ),
    ),
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def make_excerpt(content: str | None, limit: int = EXCERPT_LIMIT) -> str:
    """压缩空白并截断到 limit 字以内（与现有 _content_excerpt 行为一致）。"""
    if not content:
        return ""
    compact = " ".join(content.strip().split())
    return compact if len(compact) <= limit else compact[:limit].rstrip()


def render_template(template: QuestionTemplate, user_excerpt: str | None = None) -> str:
    """渲染模板内容，保证结果中不残留 {excerpt} 占位符。"""
    content = template.content
    if "{excerpt}" not in content:
        return content
    excerpt = make_excerpt(user_excerpt)
    return content.format(excerpt=excerpt or _EXCERPT_FALLBACK)


def _level_priority(followup_count: int) -> tuple[str, ...]:
    if followup_count <= 0:
        return ("initial", "retry", "deepened")
    return ("retry", "deepened", "initial")


def select_question(
    dimension: str,
    *,
    followup_count: int = 0,
    asked_questions: list[str] | None = None,
    user_excerpt: str | None = None,
) -> str:
    """为指定维度确定性地选出下一个问题。

    - followup_count == 0 时优先 initial 变体；>= 1 时优先 retry/deepened。
    - 剔除渲染后文本已出现在 asked_questions 中的候选；候选耗尽时逐级降级，
      全部问过时返回该维度第一个变体，保证永远返回非空问题。
    """
    templates = QUESTION_TEMPLATES.get(str(dimension))
    if not templates:
        raise ValueError(f"unknown profile dimension: {dimension!r}")

    asked = {question.strip() for question in (asked_questions or []) if question}

    # 1) 按层级优先顺序，取第一个未问过的候选
    for level in _level_priority(followup_count):
        for template in templates:
            if template.level != level:
                continue
            rendered = render_template(template, user_excerpt)
            if rendered not in asked:
                return rendered

    # 2) 降级：任意未问过的变体
    for template in templates:
        rendered = render_template(template, user_excerpt)
        if rendered not in asked:
            return rendered

    # 3) 全部问过：返回第一个变体，保证非空
    return render_template(templates[0], user_excerpt)
