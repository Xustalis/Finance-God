"""All locally reimplemented agent definitions."""

from __future__ import annotations

from .contracts import (
    AgentAdapterKind,
    AgentDefinition,
    AssetKind,
    ExecutionProfile,
)

_LOCAL_SOURCE = "agent_framework/src/research_runtime/definitions.py"
_NO_EXECUTION = (
    "Use supplied evidence only. Separate facts from inferences, expose unknowns, and do not "
    "carry out or claim trading, pricing, sizing, suitability, publishing, or external actions."
)


def _definition(
    agent_id: str,
    title: str,
    source: str,
    description: str,
    *,
    adapter: AgentAdapterKind = AgentAdapterKind.PROMPT,
    profile: ExecutionProfile = ExecutionProfile.RESEARCH,
    task_types: set[str] | None = None,
    tags: set[str] | None = None,
    asset_kinds: set[AssetKind] | None = None,
    resources: set[str] | None = None,
    external_actions: set[str] | None = None,
    authorizations: dict[str, set[str]] | None = None,
    auto_select: bool = False,
    always_active: bool = False,
    priority: int = 100,
    upstream_path: str,
    license_name: str,
) -> AgentDefinition:
    return AgentDefinition(
        agent_id=agent_id,
        title=title,
        source=source,
        description=f"{description} {_NO_EXECUTION}",
        adapter=adapter,
        minimum_profile=profile,
        task_types=task_types or {"research"},
        routing_tags=tags or set(),
        asset_kinds=asset_kinds or set(),
        required_resources=resources or set(),
        external_actions=external_actions or set(),
        authorization_by_task=authorizations or {},
        auto_select=auto_select,
        always_active=always_active,
        priority=priority,
        source_path=_LOCAL_SOURCE,
        upstream_path=upstream_path,
        license=license_name,
    )


_TRADING_UPSTREAM = "references/projects/tradingagents/tradingagents/agents"
_TRADING_ROLES = (
    (
        "fundamentals_analyst",
        "Fundamentals Analyst",
        "Assess operating fundamentals and financial disclosures.",
        set(),
        True,
        20,
    ),
    (
        "market_analyst",
        "Market Analyst",
        "Assess market structure and indicators present in the evidence.",
        set(),
        True,
        21,
    ),
    (
        "sentiment_analyst",
        "Sentiment Analyst",
        "Assess sentiment direction, confidence, and limitations.",
        {"sentiment"},
        False,
        22,
    ),
    (
        "news_analyst",
        "News Analyst",
        "Assess company, macroeconomic, and event-driven evidence.",
        set(),
        True,
        23,
    ),
    (
        "bull_researcher",
        "Support Researcher",
        "Build the strongest support case while exposing its assumptions.",
        set(),
        True,
        40,
    ),
    (
        "bear_researcher",
        "Counter Researcher",
        "Build the strongest counter-case and challenge unsupported optimism.",
        set(),
        True,
        41,
    ),
    (
        "research_manager",
        "Research Manager",
        "Synthesize contested research and identify unresolved evidence gaps.",
        {"governance"},
        False,
        60,
    ),
    (
        "trader",
        "Implementation Reviewer",
        (
            "Translate research into implementation questions and control requirements "
            "without a trade."
        ),
        {"implementation"},
        False,
        61,
    ),
    (
        "aggressive_debator",
        "Aggressive Risk Analyst",
        "Examine upside exposure and opportunity cost under explicit assumptions.",
        {"risk_debate"},
        False,
        50,
    ),
    (
        "neutral_debator",
        "Neutral Risk Analyst",
        "Compare upside and downside evidence without privileging either case.",
        {"risk_debate"},
        False,
        51,
    ),
    (
        "conservative_debator",
        "Conservative Risk Analyst",
        "Stress downside scenarios, missing evidence, concentration, and liquidity.",
        {"risk_debate"},
        False,
        52,
    ),
    (
        "portfolio_manager",
        "Governance Reviewer",
        "Compile governance preconditions and outstanding risks for a human decision-maker.",
        {"governance"},
        False,
        70,
    ),
)


def _trading_agents() -> list[AgentDefinition]:
    return [
        _definition(
            f"tradingagents:{key}",
            title,
            "TradingAgents",
            mission,
            tags=tags,
            auto_select=True,
            always_active=always_active,
            priority=priority,
            upstream_path=_TRADING_UPSTREAM,
            license_name="Apache-2.0",
        )
        for key, title, mission, tags, always_active, priority in _TRADING_ROLES
    ]


_FINROBOT_LIBRARY_PATH = "references/projects/finrobot/finrobot/agents/agent_library.py"
_FINROBOT_LIBRARY = (
    (
        "Software_Developer",
        "Software Developer",
        "Analyze and implement bounded Python software tasks.",
        ExecutionProfile.WORKSPACE,
        {"software_development"},
        {"python"},
    ),
    (
        "Data_Analyst",
        "Data Analyst",
        "Analyze supplied structured data and explain reproducible findings.",
        ExecutionProfile.RESEARCH,
        {"data_analysis", "research"},
        {"data_analysis"},
    ),
    (
        "Programmer",
        "Programmer",
        "Design and implement bounded programming tasks.",
        ExecutionProfile.WORKSPACE,
        {"software_development"},
        {"python"},
    ),
    (
        "Accountant",
        "Accountant",
        "Assess accounting evidence, reconciliations, and disclosure quality.",
        ExecutionProfile.RESEARCH,
        {"research"},
        {"accounting"},
    ),
    (
        "Statistician",
        "Statistician",
        "Assess statistical methods, uncertainty, and robustness.",
        ExecutionProfile.RESEARCH,
        {"data_analysis", "research"},
        {"statistics"},
    ),
    (
        "IT_Specialist",
        "IT Specialist",
        "Diagnose bounded infrastructure and integration tasks.",
        ExecutionProfile.WORKSPACE,
        {"software_development", "diagnostics"},
        {"infrastructure"},
    ),
    (
        "Artificial_Intelligence_Engineer",
        "Artificial Intelligence Engineer",
        "Design and review bounded AI implementation tasks.",
        ExecutionProfile.WORKSPACE,
        {"software_development"},
        {"ai"},
    ),
    (
        "Financial_Analyst",
        "Financial Analyst",
        "Analyze financial evidence and communicate its limitations.",
        ExecutionProfile.RESEARCH,
        {"research"},
        {"financials"},
    ),
    (
        "Market_Analyst",
        "FinRobot Market Analyst",
        "Analyze supplied company, market, and news evidence.",
        ExecutionProfile.RESEARCH,
        {"research"},
        {"market_context"},
    ),
    (
        "Expert_Investor",
        "Investment Report Reviewer",
        "Synthesize an evidence-bound financial analysis report for review.",
        ExecutionProfile.RESEARCH,
        {"research"},
        {"report"},
    ),
)


def _finrobot_library_agents() -> list[AgentDefinition]:
    return [
        _definition(
            f"finrobot:library:{key}",
            title,
            "FinRobot",
            description,
            profile=profile,
            task_types=task_types,
            tags=tags,
            auto_select=False,
            upstream_path=_FINROBOT_LIBRARY_PATH,
            license_name="Apache-2.0",
        )
        for key, title, description, profile, task_types, tags in _FINROBOT_LIBRARY
    ]


_FINROBOT_EQUITY_ROOT = (
    "references/projects/finrobot/finrobot_equity/core/src/modules/equity_agents"
)
_FINROBOT_EQUITY = (
    (
        "CompanyOverviewAgent",
        "Company Overview",
        "Build a sourced company identity, business-model, and operating overview.",
        {"company_deep_dive"},
        30,
        "company_overview_agent.py",
    ),
    (
        "CompetitorAnalysisAgent",
        "Competitive Landscape",
        "Assess competitors and the evidence for durable competitive advantages.",
        {"company_deep_dive", "competitive_review"},
        31,
        "competitor_analysis_agent.py",
    ),
    (
        "InvestmentOverviewAgent",
        "Investment Thesis Review",
        "Assess the evidence for and against a stated investment thesis.",
        {"thesis_review"},
        45,
        "investment_overview_agent.py",
    ),
    (
        "MajorTakeawaysAgent",
        "Major Takeaways",
        "Extract the most decision-relevant supported and contested findings.",
        {"report"},
        65,
        "major_takeaways_agent.py",
    ),
    (
        "NewsSummaryAgent",
        "News Summary",
        "Summarize supplied news evidence and distinguish events from interpretation.",
        {"news_review"},
        32,
        "news_summary_agent.py",
    ),
    (
        "RiskAnalystAgent",
        "Equity Risk Analyst",
        "Identify evidence-backed company, market, and financial risks.",
        {"risk_review"},
        48,
        "risks_agent.py",
    ),
    (
        "TaglineAnalystAgent",
        "Research Tagline",
        "Produce a concise neutral characterization grounded in the research record.",
        {"report"},
        66,
        "tagline_agent.py",
    ),
    (
        "ValuationOverviewAgent",
        "Valuation Context",
        "Explain deterministic valuation inputs and sensitivities without a price target.",
        {"valuation_review"},
        44,
        "valuation_overview_agent.py",
    ),
)


def _finrobot_equity_agents() -> list[AgentDefinition]:
    return [
        _definition(
            f"finrobot:equity:{key}",
            title,
            "FinRobot",
            description,
            tags=tags,
            asset_kinds={AssetKind.EQUITY},
            auto_select=True,
            priority=priority,
            upstream_path=f"{_FINROBOT_EQUITY_ROOT}/{filename}",
            license_name="Apache-2.0",
        )
        for key, title, description, tags, priority, filename in _FINROBOT_EQUITY
    ]


_QUANT_ROOT = "references/projects/quantskills-agents"


def _monitor_agents() -> list[AgentDefinition]:
    values = (
        (
            "agent-correlation-break-research",
            "Correlation Break Monitor",
            "Measure changes in cross-asset correlation structure from controlled data.",
            {"portfolio_stress"},
            {AssetKind.PORTFOLIO},
            {"future_dominant_corr"},
        ),
        (
            "agent-crowding-risk-monitor",
            "Crowding Risk Monitor",
            "Measure funding and event evidence associated with crowding risk.",
            {"crowding_review"},
            {AssetKind.EQUITY, AssetKind.FUND, AssetKind.MARKET, AssetKind.PORTFOLIO},
            {"margin", "lhb_list"},
        ),
        (
            "agent-derivatives-skew-sentiment-monitor",
            "Derivatives Volatility Monitor",
            "Compare implied and historical volatility evidence without a trading signal.",
            {"derivatives_review"},
            {AssetKind.EQUITY, AssetKind.FUND, AssetKind.MARKET},
            {"option_implied_volatility", "option_underlying_volatility"},
        ),
        (
            "agent-market-regime-monitor",
            "Market Regime Monitor",
            "Describe market-regime evidence from prices, funding, events, and volatility.",
            {"market_context"},
            {AssetKind.EQUITY, AssetKind.FUND, AssetKind.MARKET, AssetKind.PORTFOLIO},
            {"market_bars", "margin", "lhb_list", "option_underlying_volatility"},
        ),
    )
    return [
        _definition(
            f"quantskills:{key}",
            title,
            "QuantSkills",
            description,
            adapter=AgentAdapterKind.DETERMINISTIC_MONITOR,
            tags=tags,
            asset_kinds=asset_kinds,
            resources=resources,
            auto_select=True,
            priority=10,
            upstream_path=f"{_QUANT_ROOT}/{key}/AGENTS.md",
            license_name="GPL-3.0 contract; independent local implementation",
        )
        for key, title, description, tags, asset_kinds, resources in values
    ]


def _quant_workflow_agents() -> list[AgentDefinition]:
    values = (
        (
            "quantskills:agent-for-liangshuyuan-tasks",
            "Panda Trading Workflow",
            (
                "Route bounded quantitative-development work through analysis, development, "
                "and testing."
            ),
            ExecutionProfile.WORKSPACE,
            {"quant_development"},
            {"panda_trading"},
            "agent-for-liangshuyuan-tasks/AGENTS.md",
        ),
        (
            "quantskills:agent-quantspace",
            "QuantSpace Workflow",
            "Plan and review reusable quantitative research, backtests, and reports.",
            ExecutionProfile.WORKSPACE,
            {"quant_development", "backtest"},
            {"quantspace"},
            "agent-quantspace/AGENTS.md",
        ),
        (
            "quantskills:agent-ssquant",
            "SSQuant Workflow",
            "Diagnose SSQuant data, strategy, backtest, reporting, and guarded CTP tasks.",
            ExecutionProfile.WORKSPACE,
            {"quant_development", "backtest", "diagnostics", "live_trading"},
            {"ssquant"},
            "agent-ssquant/AGENTS.md",
        ),
        (
            "quantskills:liangshuyuan:analyst-agent",
            "Task Analyst",
            "Convert a supplied task into explicit requirements, boundaries, and ambiguities.",
            ExecutionProfile.WORKSPACE,
            {"quant_development"},
            {"requirements"},
            "agent-for-liangshuyuan-tasks/agents/analyst-agent/SKILL.md",
        ),
        (
            "quantskills:liangshuyuan:dev-alpha-agent",
            "Alpha Developer",
            "Design and validate bounded alpha-factor implementation work.",
            ExecutionProfile.WORKSPACE,
            {"quant_development"},
            {"alpha"},
            "agent-for-liangshuyuan-tasks/agents/dev-alpha-agent/SKILL.md",
        ),
        (
            "quantskills:liangshuyuan:dev-build-agent",
            "Quant Tool Developer",
            "Design and validate bounded reusable quantitative tools.",
            ExecutionProfile.WORKSPACE,
            {"quant_development"},
            {"build"},
            "agent-for-liangshuyuan-tasks/agents/dev-build-agent/SKILL.md",
        ),
        (
            "quantskills:liangshuyuan:main-agent",
            "Quant Development Orchestrator",
            "Coordinate requirements, development, testing, and delivery reports.",
            ExecutionProfile.WORKSPACE,
            {"quant_development"},
            {"orchestration"},
            "agent-for-liangshuyuan-tasks/agents/main-agent/SKILL.md",
        ),
        (
            "quantskills:liangshuyuan:test-agent",
            "Quant QA",
            "Design and evaluate tests without modifying the implementation under test.",
            ExecutionProfile.WORKSPACE,
            {"quant_development", "testing"},
            {"testing"},
            "agent-for-liangshuyuan-tasks/agents/test-agent/SKILL.md",
        ),
    )
    agents = []
    for agent_id, title, description, profile, task_types, tags, relative_path in values:
        external_actions = set()
        authorizations = {}
        if agent_id == "quantskills:agent-ssquant":
            external_actions = {"ctp_start", "order_entry", "order_cancel"}
            authorizations = {
                "live_trading": {"ctp_start", "order_entry", "order_cancel"}
            }
        agents.append(
            _definition(
                agent_id,
                title,
                "QuantSkills",
                description,
                profile=profile,
                task_types=task_types,
                tags=tags,
                resources={"workspace"},
                external_actions=external_actions,
                authorizations=authorizations,
                auto_select=True,
                always_active=agent_id.endswith("main-agent"),
                priority=20 if agent_id.endswith("main-agent") else 30,
                upstream_path=f"{_QUANT_ROOT}/{relative_path}",
                license_name="MIT"
                if "liangshuyuan" in agent_id or agent_id.endswith("tasks")
                else "GPL-3.0 contract; independent local implementation",
            )
        )
    return agents


def all_agent_definitions() -> tuple[AgentDefinition, ...]:
    """Return the complete 43-agent local registry."""

    definitions = [
        *_trading_agents(),
        *_finrobot_library_agents(),
        *_finrobot_equity_agents(),
        _definition(
            "finrobot:equity:fmp-stable-metrics",
            "FMP Stable Equity Metrics",
            "FinRobot",
            "Generate deterministic financial metrics through the isolated compatibility process.",
            adapter=AgentAdapterKind.FINROBOT_METRICS,
            profile=ExecutionProfile.WORKSPACE,
            task_types={"data_analysis", "research"},
            tags={"financials"},
            asset_kinds={AssetKind.EQUITY},
            resources={"fmp", "workspace"},
            auto_select=False,
            priority=10,
            upstream_path="references/projects/finrobot/finrobot_equity/core/src/modules/"
            "financial_data_processor.py",
            license_name="Apache-2.0",
        ),
        *_monitor_agents(),
        *_quant_workflow_agents(),
    ]
    if len(definitions) != 43:
        raise RuntimeError(f"expected 43 local agent definitions, found {len(definitions)}")
    identifiers = [item.agent_id for item in definitions]
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("local agent identifiers must be unique")
    return tuple(definitions)


AGENT_DEFINITIONS = all_agent_definitions()


def serialize_agent_definition(definition: AgentDefinition) -> dict[str, object]:
    """Return a deterministic JSON-ready representation for generated artifacts."""

    payload = definition.model_dump(mode="json")
    for field in (
        "task_types",
        "routing_tags",
        "asset_kinds",
        "required_resources",
        "external_actions",
    ):
        payload[field] = sorted(payload[field])
    payload["authorization_by_task"] = {
        task_type: sorted(actions)
        for task_type, actions in sorted(definition.authorization_by_task.items())
    }
    return payload
