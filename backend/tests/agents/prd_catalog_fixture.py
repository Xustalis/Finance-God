"""Independent PRD 7 fixture; production catalog code must not import this module."""

WORKFLOWS = (
    "company_research",
    "market_context",
    "portfolio_stress",
    "strategy_validation",
    "review_only",
    "data_quality_review",
    "fund_research",
    "portfolio_construction",
    "trade_plan_generation",
    "order_review",
    "simulation_execution",
    "post_trade_review",
    "event_impact",
    "cross_market_analysis",
    "strategy_monitoring",
)

_A = dict(
    zip(
        "CR MC PS SV RO DQ FR PC TP OR SE PR EI CM SM".split(),
        WORKFLOWS,
        strict=True,
    )
)


def _keys(value: str) -> frozenset[str]:
    return frozenset(_A[item] for item in value.split())


# agent_id -> mandatory, conditional, condition_id applied to every C cell.
PRD_AGENT_MATRIX = {
    "tradingagents:fundamentals_analyst": (
        _keys("CR RO"),
        _keys("FR EI PR"),
        "issuer_or_underlying",
    ),
    "tradingagents:market_analyst": (
        _keys("CR MC DQ FR CM"),
        _keys("TP OR EI SM"),
        "planner_selected",
    ),
    "tradingagents:sentiment_analyst": (
        _keys("MC"),
        _keys("CR FR EI CM"),
        "qualified_sentiment_evidence",
    ),
    "tradingagents:news_analyst": (
        _keys("CR MC EI"),
        _keys("FR CM RO PR"),
        "planner_selected",
    ),
    "tradingagents:bull_researcher": (
        _keys("CR"),
        _keys("FR TP EI"),
        "requires_debate",
    ),
    "tradingagents:bear_researcher": (
        _keys("CR"),
        _keys("FR TP EI RO"),
        "planner_selected",
    ),
    "tradingagents:research_manager": (
        _keys("CR MC RO DQ"),
        _keys("FR EI CM PR SM"),
        "planner_selected",
    ),
    "tradingagents:trader": (_keys("TP OR"), _keys("SE PR"), "planner_selected"),
    "tradingagents:aggressive_debator": (
        _keys("CR PS"),
        _keys("FR PC TP"),
        "planner_selected",
    ),
    "tradingagents:neutral_debator": (
        _keys("CR PS"),
        _keys("FR PC TP OR"),
        "planner_selected",
    ),
    "tradingagents:conservative_debator": (
        _keys("CR MC PS RO"),
        _keys("FR PC TP OR EI"),
        "planner_selected",
    ),
    "tradingagents:portfolio_manager": (
        _keys("CR MC PS RO PC TP OR"),
        _keys("FR PR SM"),
        "planner_selected",
    ),
    "finrobot:library:Software_Developer": (
        _keys(""),
        _keys("SV DQ SM"),
        "requires_code_implementation",
    ),
    "finrobot:library:Data_Analyst": (
        _keys("DQ FR PC PR CM SM"),
        _keys("CR MC PS SV EI"),
        "planner_selected",
    ),
    "finrobot:library:Programmer": (
        _keys(""),
        _keys("SV DQ SM"),
        "requires_non_alpha_implementation",
    ),
    "finrobot:library:Accountant": (
        _keys(""),
        _keys("CR FR PR DQ"),
        "planner_selected",
    ),
    "finrobot:library:Statistician": (
        _keys("DQ SV PC SM"),
        _keys("PS FR PR CM"),
        "planner_selected",
    ),
    "finrobot:library:IT_Specialist": (
        _keys(""),
        _keys("DQ SV SE SM"),
        "technical_fault",
    ),
    "finrobot:library:Artificial_Intelligence_Engineer": (
        _keys(""),
        _keys("SV DQ SM"),
        "ai_model_or_quality_issue",
    ),
    "finrobot:library:Financial_Analyst": (
        _keys("CR FR"),
        _keys("PC TP EI PR"),
        "planner_selected",
    ),
    "finrobot:library:Market_Analyst": (
        _keys("MC CM"),
        _keys("CR FR EI TP"),
        "planner_selected",
    ),
    "finrobot:library:Expert_Investor": (
        _keys(""),
        _keys("CR FR TP PR"),
        "requires_report_review",
    ),
    "finrobot:equity:CompanyOverviewAgent": (
        _keys("CR"),
        _keys("EI CM"),
        "planner_selected",
    ),
    "finrobot:equity:CompetitorAnalysisAgent": (
        _keys("CR"),
        _keys("EI"),
        "planner_selected",
    ),
    "finrobot:equity:InvestmentOverviewAgent": (
        _keys("CR"),
        _keys("TP PR EI"),
        "planner_selected",
    ),
    "finrobot:equity:MajorTakeawaysAgent": (
        _keys("CR"),
        _keys("FR EI TP PR"),
        "planner_selected",
    ),
    "finrobot:equity:NewsSummaryAgent": (
        _keys("EI"),
        _keys("CR MC FR CM"),
        "planner_selected",
    ),
    "finrobot:equity:RiskAnalystAgent": (
        _keys("CR"),
        _keys("RO FR TP OR EI PR"),
        "planner_selected",
    ),
    "finrobot:equity:TaglineAnalystAgent": (
        _keys(""),
        _keys("CR EI"),
        "requires_ui_tagline",
    ),
    "finrobot:equity:ValuationOverviewAgent": (
        _keys("CR"),
        _keys("EI TP PR"),
        "planner_selected",
    ),
    "finrobot:equity:fmp-stable-metrics": (
        _keys(""),
        _keys("CR DQ EI"),
        "equity_fmp_workspace_available",
    ),
    "quantskills:agent-correlation-break-research": (
        _keys("PS PC CM"),
        _keys("FR SM"),
        "planner_selected",
    ),
    "quantskills:agent-crowding-risk-monitor": (
        _keys("PS"),
        _keys("MC FR PC SM"),
        "planner_selected",
    ),
    "quantskills:agent-derivatives-skew-sentiment-monitor": (
        _keys(""),
        _keys("MC PS FR EI CM SM"),
        "option_data_available",
    ),
    "quantskills:agent-market-regime-monitor": (
        _keys("MC CM"),
        _keys("PS FR PC TP SM"),
        "planner_selected",
    ),
    "quantskills:agent-for-liangshuyuan-tasks": (
        _keys(""),
        _keys("SV SM"),
        "complex_panda_trading_development",
    ),
    "quantskills:agent-quantspace": (_keys("SV SM"), _keys("PR"), "planner_selected"),
    "quantskills:agent-ssquant": (
        _keys(""),
        _keys("SV DQ SE SM"),
        "isolated_ssquant_simulation_available",
    ),
    "quantskills:liangshuyuan:analyst-agent": (
        _keys("SV"),
        _keys("SM"),
        "planner_selected",
    ),
    "quantskills:liangshuyuan:dev-alpha-agent": (
        _keys("SV"),
        _keys("SM"),
        "planner_selected",
    ),
    "quantskills:liangshuyuan:dev-build-agent": (
        _keys(""),
        _keys("SV SM DQ"),
        "planner_selected",
    ),
    "quantskills:liangshuyuan:main-agent": (
        _keys("SV SM"),
        _keys(""),
        "planner_selected",
    ),
    "quantskills:liangshuyuan:test-agent": (
        _keys("SV"),
        _keys("SM DQ"),
        "planner_selected",
    ),
    "financegod:planner": (frozenset(WORKFLOWS), frozenset(), "planner_selected"),
}

# condition_id -> signals, asset kinds, resources, data capabilities.
PRD_CONDITION_REQUIREMENTS = {
    "planner_selected": (frozenset(), frozenset(), frozenset(), frozenset()),
    "issuer_or_underlying": (
        frozenset({"issuer_or_underlying"}),
        frozenset(),
        frozenset(),
        frozenset(),
    ),
    "qualified_sentiment_evidence": (
        frozenset({"qualified_sentiment_evidence"}),
        frozenset(),
        frozenset(),
        frozenset(),
    ),
    "requires_debate": (
        frozenset({"requires_debate"}),
        frozenset(),
        frozenset(),
        frozenset(),
    ),
    "requires_code_implementation": (
        frozenset({"requires_code_implementation"}),
        frozenset(),
        frozenset({"workspace"}),
        frozenset(),
    ),
    "requires_non_alpha_implementation": (
        frozenset({"requires_non_alpha_implementation"}),
        frozenset(),
        frozenset({"workspace"}),
        frozenset(),
    ),
    "technical_fault": (
        frozenset({"technical_fault"}),
        frozenset(),
        frozenset(),
        frozenset(),
    ),
    "ai_model_or_quality_issue": (
        frozenset({"ai_model_or_quality_issue"}),
        frozenset(),
        frozenset(),
        frozenset(),
    ),
    "requires_report_review": (
        frozenset({"requires_report_review"}),
        frozenset(),
        frozenset(),
        frozenset(),
    ),
    "requires_ui_tagline": (
        frozenset({"requires_ui_tagline"}),
        frozenset(),
        frozenset(),
        frozenset(),
    ),
    "equity_fmp_workspace_available": (
        frozenset(),
        frozenset({"equity"}),
        frozenset({"fmp", "workspace"}),
        frozenset(),
    ),
    "option_data_available": (
        frozenset(),
        frozenset(),
        frozenset(),
        frozenset({"option_implied_volatility", "option_underlying_volatility"}),
    ),
    "complex_panda_trading_development": (
        frozenset({"complex_panda_trading_development"}),
        frozenset(),
        frozenset({"workspace", "panda_trading"}),
        frozenset(),
    ),
    "isolated_ssquant_simulation_available": (
        frozenset(),
        frozenset(),
        frozenset({"workspace", "ssquant_simulation"}),
        frozenset(),
    ),
}
