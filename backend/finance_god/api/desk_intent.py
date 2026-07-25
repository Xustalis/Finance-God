"""Single source of truth for deterministic trading-desk intent routing."""

from __future__ import annotations

from dataclasses import dataclass

from finance_god.agents.contracts import WorkflowKey


@dataclass(frozen=True, slots=True)
class _IntentRule:
    workflow: WorkflowKey
    terms: tuple[str, ...]


# Specific operational intents must precede broad research and market terms.
_INTENT_RULES = (
    _IntentRule(
        WorkflowKey.SIMULATION_EXECUTION,
        ("仿真执行", "模拟执行", "模拟下单", "执行已确认订单"),
    ),
    _IntentRule(
        WorkflowKey.ORDER_REVIEW,
        ("订单草稿", "订单复核", "复核订单", "下单前检查", "提交前检查"),
    ),
    _IntentRule(
        WorkflowKey.POST_TRADE_REVIEW,
        (
            "交易后复盘",
            "交易复盘",
            "成交复盘",
            "执行复盘",
            "滑点复盘",
            "成交滑点",
            "复盘策略执行",
        ),
    ),
    _IntentRule(
        WorkflowKey.STRATEGY_MONITORING,
        ("策略监控", "策略漂移", "策略失效", "策略表现", "监控策略"),
    ),
    _IntentRule(
        WorkflowKey.DATA_QUALITY_REVIEW,
        ("数据质量", "数据异常", "数据缺失", "数据冲突", "行情对不上", "价格对不上"),
    ),
    _IntentRule(
        WorkflowKey.CROSS_MARKET_ANALYSIS,
        ("跨市场", "股债汇", "股债商品", "汇率联动", "市场联动"),
    ),
    _IntentRule(
        WorkflowKey.EVENT_IMPACT,
        ("事件影响", "公告影响", "重大异动", "行情提醒", "突发事件"),
    ),
    _IntentRule(
        WorkflowKey.PORTFOLIO_CONSTRUCTION,
        ("组合构建", "构建组合", "资产配置", "配置权重", "目标权重"),
    ),
    _IntentRule(
        WorkflowKey.TRADE_PLAN_GENERATION,
        ("交易方案", "交易计划", "建仓计划", "调仓计划", "生成计划"),
    ),
    _IntentRule(
        WorkflowKey.FUND_RESEARCH,
        ("基金研究", "研究基金", "ETF研究", "研究ETF", "LOF研究", "研究LOF"),
    ),
    _IntentRule(
        WorkflowKey.RESEARCH_CANDIDATES,
        (
            "推荐股票",
            "推荐几只股票",
            "股票推荐",
            "选股",
            "可研究候选",
            "研究候选",
            "候选股票",
        ),
    ),
    _IntentRule(
        WorkflowKey.STRATEGY_VALIDATION,
        ("策略验证", "验证策略", "回测", "因子验证", "Alpha验证", "alpha验证"),
    ),
    _IntentRule(
        WorkflowKey.PORTFOLIO_STRESS,
        ("组合压力", "压力测试", "持仓风险", "组合风险", "回撤", "集中度"),
    ),
    _IntentRule(
        WorkflowKey.REVIEW_ONLY,
        ("只读复核", "只复核", "不要执行", "不生成交易计划"),
    ),
    _IntentRule(
        WorkflowKey.COMPANY_RESEARCH,
        ("公司研究", "研究公司", "基本面", "财务分析", "公司估值", "个股研究"),
    ),
    _IntentRule(
        WorkflowKey.MARKET_CONTEXT,
        ("市场环境", "当前行情", "市场状态", "行情走势", "大盘走势"),
    ),
)

_GENERAL_WORKFLOW_TERMS = (
    "分析",
    "研究",
    "比较",
    "评估",
    "制定",
    "生成",
    "推荐",
    "监控",
    "复核",
    "复盘",
    "执行",
    "行情",
    "走势",
    "持仓",
    "组合",
    "订单",
)

_CONCEPT_PREFIXES = ("什么是", "什么意思", "如何理解", "解释一下概念")
_CONTEXT_SIGNALS = (
    "当前",
    "现在",
    "最近",
    "今日",
    "我的",
    "这只",
    "该公司",
    "行情",
    "走势",
    "持仓",
    "组合",
    "订单",
)


def classify_desk_intent(message: str) -> WorkflowKey | None:
    """Return an explicit workflow intent, leaving generic requests unresolved."""

    text = message.strip()
    if not text:
        raise ValueError("request_intent cannot be blank")
    for rule in _INTENT_RULES:
        if any(term in text for term in rule.terms):
            return rule.workflow
    return None


def requires_desk_workflow(message: str) -> bool:
    """Distinguish operational research from greetings and concept questions."""

    text = message.strip()
    if not text:
        raise ValueError("request_intent cannot be blank")
    if text.startswith(_CONCEPT_PREFIXES) and not any(
        signal in text for signal in _CONTEXT_SIGNALS
    ):
        return False
    return classify_desk_intent(text) is not None or any(
        term in text for term in _GENERAL_WORKFLOW_TERMS
    )


def select_desk_workflow(message: str, *, section: str) -> WorkflowKey:
    """Select a workflow with explicit intent taking priority over workspace."""

    explicit = classify_desk_intent(message)
    if explicit is not None:
        return explicit
    if section == "portfolio":
        return WorkflowKey.PORTFOLIO_STRESS
    if section == "trading":
        return WorkflowKey.TRADE_PLAN_GENERATION
    if section == "watchlist":
        return WorkflowKey.COMPANY_RESEARCH
    if section == "review":
        return WorkflowKey.POST_TRADE_REVIEW
    return WorkflowKey.MARKET_CONTEXT
