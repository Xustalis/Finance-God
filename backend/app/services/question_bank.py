"""问题模板池：为六个画像维度提供多变体、可去重、确定性的提问选择。

设计目标：
- 每个维度至少 3 个变体，覆盖 initial / retry / deepened 三个层级，
  以及 scenario / direct / metaphor 三种表达方式。
- 收录现有 ``ai_orchestrator`` 中的 INITIAL_RISK_QUESTION、QUESTION_STEMS、
  RETRY_QUESTION_STEMS 原文，保证向后兼容（注意：本模块不 import
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
    ProfileDimension.RISK_TOLERANCE.value: (
        # 向后兼容：现有 INITIAL_RISK_QUESTION 原文
        QuestionTemplate(
            "rt_initial_direct_01",
            "initial",
            "direct",
            "如果这笔资金出现约15%的阶段性亏损，你更可能继续持有、减少投入，还是全部卖出？",
        ),
        # 向后兼容：现有 QUESTION_STEMS 原文
        QuestionTemplate(
            "rt_initial_direct_02",
            "initial",
            "direct",
            "你通常会怎样应对一笔投资的阶段性亏损？",
        ),
        QuestionTemplate(
            "rt_initial_scenario_01",
            "initial",
            "scenario",
            "假如你投的 10 万，三个月后变成 8 万五，那天晚上你会想做点什么？",
        ),
        # 向后兼容：现有 RETRY_QUESTION_STEMS 原文
        QuestionTemplate(
            "rt_retry_direct_01",
            "retry",
            "direct",
            "换个角度，如果账户短期下跌约15%，你会选择持有、减仓还是卖出？",
        ),
        QuestionTemplate(
            "rt_deepened_metaphor_01",
            "deepened",
            "metaphor",
            "你刚才提到“{excerpt}”，如果把投资比作坐过山车，你觉得自己能安心坐到多大的起伏？",
        ),
    ),
    ProfileDimension.LIQUIDITY_NEED.value: (
        QuestionTemplate(
            "ln_initial_direct_01",
            "initial",
            "direct",
            "这笔资金预计多久内可能需要取用？",
        ),
        QuestionTemplate(
            "ln_initial_scenario_01",
            "initial",
            "scenario",
            "这笔钱里，有没有一部分是一年内可能要用的？比如房租、学费或者应急？",
        ),
        QuestionTemplate(
            "ln_retry_direct_01",
            "retry",
            "direct",
            "换个角度，这笔钱最早可能在什么时候需要使用？",
        ),
        QuestionTemplate(
            "ln_deepened_scenario_01",
            "deepened",
            "scenario",
            "你提到“{excerpt}”，如果哪天突然要用一笔钱应急，你会先从哪里拿？",
        ),
    ),
    ProfileDimension.INVESTMENT_GOAL.value: (
        QuestionTemplate(
            "ig_initial_direct_01",
            "initial",
            "direct",
            "你最希望这笔资金优先支持哪个生活目标？",
        ),
        QuestionTemplate(
            "ig_initial_scenario_01",
            "initial",
            "scenario",
            "想象三五年后这笔钱帮你实现了一件事，你最希望那是什么？",
        ),
        QuestionTemplate(
            "ig_retry_direct_01",
            "retry",
            "direct",
            "换个角度，你希望这笔钱首先解决什么长期需求？",
        ),
        QuestionTemplate(
            "ig_deepened_metaphor_01",
            "deepened",
            "metaphor",
            "你刚才说到“{excerpt}”，如果这笔钱是一颗种子，你更希望它慢慢长成什么样子？",
        ),
    ),
    ProfileDimension.LOSS_BEHAVIOR.value: (
        QuestionTemplate(
            "lb_initial_direct_01",
            "initial",
            "direct",
            "市场明显下跌时，你更可能持有、减仓还是卖出？",
        ),
        QuestionTemplate(
            "lb_initial_scenario_01",
            "initial",
            "scenario",
            "回想一下上次账户绿了一大片的时候，你当时的第一反应是什么？",
        ),
        QuestionTemplate(
            "lb_retry_direct_01",
            "retry",
            "direct",
            "换个角度，遇到明显下跌时你通常会采取什么行动？",
        ),
        QuestionTemplate(
            "lb_deepened_scenario_01",
            "deepened",
            "scenario",
            "你提到“{excerpt}”，如果亏损继续扩大，你觉得自己大概会在哪个点上开始坐不住？",
        ),
    ),
    ProfileDimension.INVESTMENT_KNOWLEDGE.value: (
        QuestionTemplate(
            "ik_initial_direct_01",
            "initial",
            "direct",
            "你对常见投资产品和价格波动有多少实际了解？",
        ),
        QuestionTemplate(
            "ik_initial_scenario_01",
            "initial",
            "scenario",
            "平时朋友聊到基金、股票这些话题时，你一般是能接上话，还是更多在旁边听？",
        ),
        QuestionTemplate(
            "ik_retry_direct_01",
            "retry",
            "direct",
            "换个角度，你曾经亲自了解或使用过哪些投资产品？",
        ),
        QuestionTemplate(
            "ik_deepened_direct_01",
            "deepened",
            "direct",
            "你刚才提到“{excerpt}”，方便再聊聊你是怎么了解到它的吗？",
        ),
    ),
    ProfileDimension.INCOME_STABILITY.value: (
        QuestionTemplate(
            "is_initial_direct_01",
            "initial",
            "direct",
            "如果方便回答，你未来一年的收入稳定性大致如何？你也可以跳过。",
        ),
        QuestionTemplate(
            "is_initial_scenario_01",
            "initial",
            "scenario",
            "如果方便回答，可以聊聊你的收入是比较固定，还是会随季节或项目有些起伏？不方便的话也可以跳过。",
        ),
        QuestionTemplate(
            "is_retry_direct_01",
            "retry",
            "direct",
            "如果方便回答，你能否只说收入是稳定、偶有波动还是不稳定？也可以跳过。",
        ),
        QuestionTemplate(
            "is_deepened_scenario_01",
            "deepened",
            "scenario",
            "如果方便回答，未来一年里会不会有一些收入上的变化，比如换工作或者休整一段时间？也可以跳过。",
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
