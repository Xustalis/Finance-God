"""Finance-God governance overlay over the immutable vendor Agent definitions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from enum import Enum
from types import MappingProxyType
from typing import Any
from typing import Final

from research_runtime import (
    AgentAdapterKind,
    AgentDefinition,
    AgentRegistry,
    ExecutionProfile,
)

from .contracts import (
    AgentGovernanceEntry,
    ConditionalRule,
    ContractDescriptor,
    ContractFieldDescriptor,
    ContractRegistry,
    ExecutionType,
    FailureKind,
    FailurePolicy,
    ImpactClass,
    NodeRequirement,
    RiskLevel,
    SelectionSignal,
    VendorCapabilitySnapshot,
    WorkflowCallMode,
    WorkflowDecision,
    WorkflowKey,
    WorkflowSelectionContext,
)

CATALOG_VERSION: Final = "1.0.0"
PLANNER_ID: Final = "financegod:planner"
VENDOR_CATALOG_FINGERPRINT: Final = (
    "f96b2fbf03a453db65d5cfe89cf5bbfce7c585e8df49c4443161efdc5478c99f"
)
AGENT_INPUT_CONTRACT_ID: Final = "financegod.agent-input.v1"
AGENT_OUTPUT_CONTRACT_ID: Final = "financegod.agent-output.v1"
PLANNER_INPUT_CONTRACT_ID: Final = "financegod.planner-input.v1"
PLANNER_OUTPUT_CONTRACT_ID: Final = "financegod.task-plan-output.v1"

TRADE_WRITE_TOOLS: Final = frozenset(
    {
        "ctp_start",
        "order_entry",
        "order_cancel",
        "account.write",
        "cash.write",
        "position.write",
        "order.write",
        "fill.write",
        "ledger.write",
        "authorization.write",
        "risk.override",
    }
)

_BINDING_FIELDS = (
    ContractFieldDescriptor("agent_id", "string", True, "稳定 Agent ID。"),
    ContractFieldDescriptor("contract_id", "string", True, "本契约 ID。"),
    ContractFieldDescriptor("schema_version", "string", True, "契约版本。"),
)
_VERSION_FIELDS = (
    *_BINDING_FIELDS,
    ContractFieldDescriptor("run_id", "string", True, "唯一运行 ID。"),
    ContractFieldDescriptor("workflow_id", "string", True, "正式工作流 ID。"),
    ContractFieldDescriptor("workflow_version", "string", True, "工作流版本。"),
    ContractFieldDescriptor("input_version", "string", True, "不可变输入版本。"),
)
_BASE_CONTRACT_REGISTRY: Final = MappingProxyType(
    {
        AGENT_INPUT_CONTRACT_ID: ContractDescriptor(
            contract_id=AGENT_INPUT_CONTRACT_ID,
            version="1",
            fields=(
                *_VERSION_FIELDS,
                ContractFieldDescriptor(
                    "evidence",
                    "EvidenceReference[]",
                    True,
                    "仅包含 approved=true 且带来源版本的证据引用。",
                ),
            ),
            purpose="所有研究、计算与隔离代码 Agent 的版本化输入。",
        ),
        AGENT_OUTPUT_CONTRACT_ID: ContractDescriptor(
            contract_id=AGENT_OUTPUT_CONTRACT_ID,
            version="1",
            fields=(
                *_BINDING_FIELDS,
                ContractFieldDescriptor("run_id", "string", True, "唯一运行 ID。"),
                ContractFieldDescriptor("artifact_id", "string", True, "产物 ID。"),
                ContractFieldDescriptor("output_version", "string", True, "产物版本。"),
                ContractFieldDescriptor(
                    "input_version",
                    "string",
                    True,
                    "可回溯的输入版本。",
                ),
                ContractFieldDescriptor(
                    "facts",
                    "EvidenceBoundStatement[]",
                    True,
                    "带证据 ID 的事实。",
                ),
                ContractFieldDescriptor(
                    "inferences",
                    "EvidenceBoundStatement[]",
                    True,
                    "与事实分离且带证据 ID 的推断。",
                ),
                ContractFieldDescriptor(
                    "recommendations",
                    "EvidenceBoundStatement[]",
                    True,
                    "带证据 ID 的待审阅建议，不是已执行动作。",
                ),
                ContractFieldDescriptor("unknowns", "string[]", True, "未知项。"),
                ContractFieldDescriptor(
                    "invalidation_conditions",
                    "string[]",
                    True,
                    "结论失效条件。",
                ),
            ),
            purpose="所有非 Planner Agent 的证据绑定产物。",
        ),
        PLANNER_INPUT_CONTRACT_ID: ContractDescriptor(
            contract_id=PLANNER_INPUT_CONTRACT_ID,
            version="1",
            fields=(
                *_VERSION_FIELDS,
                ContractFieldDescriptor(
                    "selection_context",
                    "WorkflowSelectionContext",
                    True,
                    "用户目标、市场/资产、授权状态、数据和资源；不含交易事实。",
                ),
            ),
            purpose="Planner 的只读路由上下文。",
        ),
        PLANNER_OUTPUT_CONTRACT_ID: ContractDescriptor(
            contract_id=PLANNER_OUTPUT_CONTRACT_ID,
            version="1",
            fields=(
                ContractFieldDescriptor("run_id", "string", True, "运行 ID。"),
                ContractFieldDescriptor("output_version", "string", True, "计划版本。"),
                ContractFieldDescriptor(
                    "workflow_selection",
                    "string",
                    True,
                    "正式工作流选择或受约束 TaskPlan。",
                ),
                ContractFieldDescriptor("node_ids", "string[]", True, "节点清单。"),
                ContractFieldDescriptor("dependencies", "object", True, "节点依赖。"),
                ContractFieldDescriptor("budget", "object", True, "次数与总时长预算。"),
                ContractFieldDescriptor(
                    "block_reasons",
                    "string[]",
                    True,
                    "显式阻断原因。",
                ),
            ),
            purpose="Planner 只产生编排建议，不产生研究或交易事实。",
        ),
    }
)

_COMMON_PROHIBITIONS = (
    "不得创建或修改订单、资金、持仓、成交、授权或正式风控事实。",
    "不得覆盖用户暂停、硬风控或冷静期。",
    "不得把建议、代码、请求或模拟结果表述为已执行动作。",
    "不得脱离输入证据生成事实、目标价、仓位、适当性结论或对外发布内容。",
)

_ABBREVIATIONS = {
    "CR": WorkflowKey.COMPANY_RESEARCH,
    "MC": WorkflowKey.MARKET_CONTEXT,
    "PS": WorkflowKey.PORTFOLIO_STRESS,
    "SV": WorkflowKey.STRATEGY_VALIDATION,
    "RO": WorkflowKey.REVIEW_ONLY,
    "DQ": WorkflowKey.DATA_QUALITY_REVIEW,
    "FR": WorkflowKey.FUND_RESEARCH,
    "PC": WorkflowKey.PORTFOLIO_CONSTRUCTION,
    "TP": WorkflowKey.TRADE_PLAN_GENERATION,
    "OR": WorkflowKey.ORDER_REVIEW,
    "SE": WorkflowKey.SIMULATION_EXECUTION,
    "PR": WorkflowKey.POST_TRADE_REVIEW,
    "EI": WorkflowKey.EVENT_IMPACT,
    "CM": WorkflowKey.CROSS_MARKET_ANALYSIS,
    "SM": WorkflowKey.STRATEGY_MONITORING,
}

# Product-owned metadata. Vendor execution metadata is referenced from AgentRegistry by stable ID.
_ROWS = (
    (
        "tradingagents:fundamentals_analyst",
        "审阅经营基本面和财务披露",
        "CR RO",
        "FR EI PR",
        "不给目标价、交易方向或仓位。",
    ),
    (
        "tradingagents:market_analyst",
        "分析行情结构、技术指标和市场证据",
        "CR MC DQ FR CM",
        "TP OR EI SM",
        "不把日线证据描述为实时盘中状态，不决定成交。",
    ),
    (
        "tradingagents:sentiment_analyst",
        "评估情绪方向、强度和偏差",
        "MC",
        "CR FR EI CM",
        "不在无数据时推断情绪，不生成交易信号。",
    ),
    (
        "tradingagents:news_analyst",
        "解释公司、宏观和事件新闻",
        "CR MC EI",
        "FR CM RO PR",
        "不把报道当作已证实事实，不访问未批准来源。",
    ),
    (
        "tradingagents:bull_researcher",
        "构建最强支持论点",
        "CR",
        "FR TP EI",
        "不忽略反证，不把观点变成订单建议。",
    ),
    (
        "tradingagents:bear_researcher",
        "构建最强反方论点",
        "CR",
        "FR TP EI RO",
        "不虚构风险，不单独否决定性服务结果。",
    ),
    (
        "tradingagents:research_manager",
        "汇总研究分歧并提出治理建议",
        "CR MC RO DQ",
        "FR EI CM PR SM",
        "不覆盖证据完整性、新鲜度或硬风险质量门。",
    ),
    (
        "tradingagents:trader",
        "将研究转译为实施问题和控制要求",
        "TP OR",
        "SE PR",
        "不决定数量或提交、撤销订单；解释失败不影响已受理订单。",
    ),
    (
        "tradingagents:aggressive_debator",
        "评估上行情景与机会成本",
        "CR PS",
        "FR PC TP",
        "不以收益机会覆盖硬风险。",
    ),
    (
        "tradingagents:neutral_debator",
        "对称比较上行与下行证据",
        "CR PS",
        "FR PC TP OR",
        "不用投票替代证据或确定性校验。",
    ),
    (
        "tradingagents:conservative_debator",
        "压测下行、集中度和流动性",
        "CR MC PS RO",
        "FR PC TP OR EI",
        "不生成正式硬风控结论或冻结订单。",
    ),
    (
        "tradingagents:portfolio_manager",
        "汇总组合治理前提和未解决风险",
        "CR MC PS RO PC TP OR",
        "FR PR SM",
        "不直接给最终权重，不改写优化器结果，不批准订单。",
    ),
    (
        "finrobot:library:Software_Developer",
        "实现受限 Python 研究或回测任务",
        "",
        "SV DQ SM",
        "不修改主项目或生产环境，不绕过隔离和测试。",
    ),
    (
        "finrobot:library:Data_Analyst",
        "对结构化数据做可复现分析",
        "DQ FR PC PR CM SM",
        "CR MC PS SV EI",
        "不补造缺失数据或隐式修正冲突。",
    ),
    (
        "finrobot:library:Programmer",
        "实现边界明确的通用编程任务",
        "",
        "SV DQ SM",
        "不接触凭证或账户，不在主环境直接运行生成代码。",
    ),
    (
        "finrobot:library:Accountant",
        "审阅会计证据和勾稽关系",
        "",
        "CR FR PR DQ",
        "不改账、不确认净值、不替代账务服务。",
    ),
    (
        "finrobot:library:Statistician",
        "评估统计方法与稳健性",
        "DQ SV PC SM",
        "PS FR PR CM",
        "不把相关性表述为因果或保证未来收益。",
    ),
    (
        "finrobot:library:IT_Specialist",
        "诊断数据、基础设施和集成问题",
        "",
        "DQ SV SE SM",
        "不读取或输出密钥，不静默降级数据源。",
    ),
    (
        "finrobot:library:Artificial_Intelligence_Engineer",
        "评审 AI 实现、提示和评测",
        "",
        "SV DQ SM",
        "不自行发布模型、扩大工具权限或使用未授权数据。",
    ),
    (
        "finrobot:library:Financial_Analyst",
        "综合分析财务证据",
        "CR FR",
        "PC TP EI PR",
        "不给无确定性模型支持的目标价或最终结论。",
    ),
    (
        "finrobot:library:Market_Analyst",
        "解释公司、市场与新闻环境",
        "MC CM",
        "CR FR EI TP",
        "不把不同市场时点拼接为同步事实。",
    ),
    (
        "finrobot:library:Expert_Investor",
        "独立复核投资分析报告",
        "",
        "CR FR TP PR",
        "不充当最终批准人或给出收益承诺。",
    ),
    (
        "finrobot:equity:CompanyOverviewAgent",
        "建立公司身份、业务模式和经营概览",
        "CR",
        "EI CM",
        "仅限股票发行人，不用于基金本体。",
    ),
    (
        "finrobot:equity:CompetitorAnalysisAgent",
        "分析竞争格局和优势证据",
        "CR",
        "EI",
        "不使用不可比口径强行排序。",
    ),
    (
        "finrobot:equity:InvestmentOverviewAgent",
        "复核投资论点的正反证据",
        "CR",
        "TP PR EI",
        "不自行创建论点后自证，不直接提出订单。",
    ),
    (
        "finrobot:equity:MajorTakeawaysAgent",
        "提取关键支持与争议结论",
        "CR",
        "FR EI TP PR",
        "不删除重要反证或把摘要当作新证据。",
    ),
    (
        "finrobot:equity:NewsSummaryAgent",
        "形成去重、可追溯的新闻摘要",
        "EI",
        "CR MC FR CM",
        "不把标题当事实，不使用未批准来源。",
    ),
    (
        "finrobot:equity:RiskAnalystAgent",
        "识别公司、市场和财务风险",
        "CR",
        "RO FR TP OR EI PR",
        "不产生或覆盖正式 RiskCheckResult。",
    ),
    (
        "finrobot:equity:TaglineAnalystAgent",
        "生成简短中性的研究特征摘要",
        "",
        "CR EI",
        "不写宣传语、评级口号、收益暗示或新事实。",
    ),
    (
        "finrobot:equity:ValuationOverviewAgent",
        "解释估值输入和敏感性",
        "CR",
        "EI TP PR",
        "不自行定价或输出目标价。",
    ),
    (
        "finrobot:equity:fmp-stable-metrics",
        "生成确定性股票财务指标",
        "",
        "CR DQ EI",
        "资源缺失时不伪造指标，不用于非股票资产。",
    ),
    (
        "quantskills:agent-correlation-break-research",
        "测量跨资产相关结构变化",
        "PS PC CM",
        "FR SM",
        "不把相关性变化直接转成买卖信号。",
    ),
    (
        "quantskills:agent-crowding-risk-monitor",
        "测量融资、事件和持仓拥挤风险",
        "PS",
        "MC FR PC SM",
        "资源缺失时不输出低拥挤结论，不直接减仓。",
    ),
    (
        "quantskills:agent-derivatives-skew-sentiment-monitor",
        "比较隐含与历史波动证据",
        "",
        "MC PS FR EI CM SM",
        "仅限研究，不提出期货或期权订单。",
    ),
    (
        "quantskills:agent-market-regime-monitor",
        "描述市场状态与切换条件",
        "MC CM",
        "PS FR PC TP SM",
        "不把市场状态直接当作交易许可。",
    ),
    (
        "quantskills:agent-for-liangshuyuan-tasks",
        "路由隔离量化需求、开发和测试",
        "",
        "SV SM",
        "不替代产品 Planner，不部署或触达账户。",
    ),
    (
        "quantskills:agent-quantspace",
        "规划和审阅量化研究与回测",
        "SV SM",
        "PR",
        "不把回测表述为收益保证或直接进入执行。",
    ),
    (
        "quantskills:agent-ssquant",
        "诊断 SSQuant 数据、策略和回测",
        "",
        "SV DQ SE SM",
        "P0 禁用 ctp_start、order_cancel、order_entry，不连接实盘。",
    ),
    (
        "quantskills:liangshuyuan:analyst-agent",
        "将量化任务转为需求与验收条件",
        "SV",
        "SM",
        "不自行扩大策略目标、数据范围或权限。",
    ),
    (
        "quantskills:liangshuyuan:dev-alpha-agent",
        "设计和验证 Alpha 因子",
        "SV",
        "SM",
        "不使用未来数据，不改变样本，不跳过测试。",
    ),
    (
        "quantskills:liangshuyuan:dev-build-agent",
        "设计和验证量化工具",
        "",
        "SV SM DQ",
        "不修改主项目，不绕过隔离、审查和测试。",
    ),
    (
        "quantskills:liangshuyuan:main-agent",
        "协调量化开发、测试和交付",
        "SV SM",
        "",
        "不替代产品 Planner，不覆盖失败测试或批准交易。",
    ),
    (
        "quantskills:liangshuyuan:test-agent",
        "独立评估量化验收测试",
        "SV",
        "SM DQ",
        "不修改被测实现或吞掉失败。",
    ),
)

_ROLE_CONTRACT_SEMANTICS: Final = {
    PLANNER_ID: (
        "用户目标、市场/资产、状态、数据和资源",
        "工作流选择、节点清单、依赖、预算和阻断理由",
    ),
    "tradingagents:fundamentals_analyst": (
        "财务、公告、公司证据",
        "基本面事实、推断、未知项和失效条件",
    ),
    "tradingagents:market_analyst": (
        "日线行情、指标、市场状态",
        "结构判断、异常和数据缺口",
    ),
    "tradingagents:sentiment_analyst": (
        "新闻和情绪证据",
        "方向、置信度、限制和反向证据",
    ),
    "tradingagents:news_analyst": (
        "新闻、公告、宏观事件",
        "事件事实、影响路径、时效和未知项",
    ),
    "tradingagents:bull_researcher": (
        "已验证事实和反方材料",
        "支持论点、假设和证据强弱",
    ),
    "tradingagents:bear_researcher": (
        "研究证据、支持论点和风险事件",
        "反方论点、薄弱假设和下行情景",
    ),
    "tradingagents:research_manager": (
        "Agent 产物、证据链和质量门",
        "条件化结论、分歧和治理建议",
    ),
    "tradingagents:trader": (
        "研究/策略、草稿、市场规则和执行结果",
        "实施约束、复核问题和偏离解释",
    ),
    "tradingagents:aggressive_debator": (
        "研究证据、组合暴露和约束",
        "上行情景、机会成本和敏感性",
    ),
    "tradingagents:neutral_debator": (
        "正反材料和组合影响",
        "平衡比较、关键分歧和条件结论",
    ),
    "tradingagents:conservative_debator": (
        "研究、组合和流动性证据",
        "下行压力、缺口和升级项",
    ),
    "tradingagents:portfolio_manager": (
        "研究/策略、约束、辩论和优化结果",
        "治理摘要、组合影响和待决事项",
    ),
    "finrobot:library:Software_Developer": (
        "需求、接口、测试和隔离工作区",
        "代码产物、测试证据和限制",
    ),
    "finrobot:library:Data_Analyst": (
        "数据、口径和质量标记",
        "统计结果、步骤、异常和限制",
    ),
    "finrobot:library:Programmer": (
        "编程需求、允许文件和测试要求",
        "受限实现与测试结果",
    ),
    "finrobot:library:Accountant": (
        "财报、基金报表或账本摘要",
        "会计一致性、披露风险和调节项",
    ),
    "finrobot:library:Statistician": ("样本、方法和结果", "置信区间、偏差和稳健性意见"),
    "finrobot:library:IT_Specialist": (
        "日志、接口状态和运行轨迹",
        "根因、影响范围和修复建议",
    ),
    "finrobot:library:Artificial_Intelligence_Engineer": (
        "模型/提示、评测集和运行证据",
        "设计意见、评测结果和风险",
    ),
    "finrobot:library:Financial_Analyst": (
        "财务指标、估值输入和基金资料",
        "财务分析、敏感项和限制",
    ),
    "finrobot:library:Market_Analyst": (
        "跨市场行情、新闻和汇率",
        "环境摘要、传导路径和未知项",
    ),
    "finrobot:library:Expert_Investor": (
        "研究包、分歧和计划影响",
        "审阅摘要、缺失项和人工判断项",
    ),
    "finrobot:equity:CompanyOverviewAgent": (
        "公司资料和业务披露",
        "公司概览、分部和来源",
    ),
    "finrobot:equity:CompetitorAnalysisAgent": (
        "公司、同业和行业证据",
        "同业比较与证据强弱",
    ),
    "finrobot:equity:InvestmentOverviewAgent": (
        "明确论点、研究证据和反证",
        "支持度、依赖条件和反例",
    ),
    "finrobot:equity:MajorTakeawaysAgent": (
        "完整研究/复盘证据",
        "关键结论、争议和未知项",
    ),
    "finrobot:equity:NewsSummaryAgent": (
        "新闻/公告及其时点",
        "事件摘要和事实/解释分层",
    ),
    "finrobot:equity:RiskAnalystAgent": (
        "研究证据和计划/订单影响",
        "风险清单、依据和未知项",
    ),
    "finrobot:equity:TaglineAnalystAgent": ("已治理结论和引用", "中性短摘要及证据链接"),
    "finrobot:equity:ValuationOverviewAgent": (
        "估值输入、可比口径和假设",
        "估值上下文、敏感性和局限",
    ),
    "finrobot:equity:fmp-stable-metrics": (
        "股票标的和 FMP 输入",
        "可复算指标、来源和错误",
    ),
    "quantskills:agent-correlation-break-research": (
        "收益序列、窗口和基准",
        "相关结构、变化点和样本限制",
    ),
    "quantskills:agent-crowding-risk-monitor": (
        "融资/事件数据和持仓暴露",
        "拥挤指标、证据和限制",
    ),
    "quantskills:agent-derivatives-skew-sentiment-monitor": (
        "隐含/历史波动和期限",
        "波动差异、情绪证据和限制",
    ),
    "quantskills:agent-market-regime-monitor": (
        "行情、融资、事件和波动",
        "状态分类、证据和切换条件",
    ),
    "quantskills:agent-for-liangshuyuan-tasks": (
        "量化需求、边界和工作区",
        "子任务计划和产物索引",
    ),
    "quantskills:agent-quantspace": (
        "策略、数据集、费用和回测配置",
        "回测/稳定性报告和限制",
    ),
    "quantskills:agent-ssquant": (
        "仿真数据、策略和隔离工作区",
        "诊断、代码或未执行请求",
    ),
    "quantskills:liangshuyuan:analyst-agent": (
        "策略目标、数据和约束",
        "需求、歧义和验收条件",
    ),
    "quantskills:liangshuyuan:dev-alpha-agent": (
        "已批准需求、数据契约和工作区",
        "Alpha 设计/代码和验证记录",
    ),
    "quantskills:liangshuyuan:dev-build-agent": (
        "工具需求、接口和测试要求",
        "工具实现和验证记录",
    ),
    "quantskills:liangshuyuan:main-agent": (
        "需求、开发、回测和测试产物",
        "治理汇总、未通过项和报告",
    ),
    "quantskills:liangshuyuan:test-agent": (
        "需求、实现和测试数据",
        "测试结果、失败证据和覆盖缺口",
    ),
}


def _contract_slug(agent_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", agent_id.lower()).strip("-")


def _role_contracts() -> dict[str, ContractDescriptor]:
    contracts: dict[str, ContractDescriptor] = {}
    for agent_id, (
        input_semantics,
        output_semantics,
    ) in _ROLE_CONTRACT_SEMANTICS.items():
        slug = _contract_slug(agent_id)
        input_id = f"financegod.agent-input.{slug}.v1"
        output_id = f"financegod.agent-output.{slug}.v1"
        contracts[input_id] = ContractDescriptor(
            contract_id=input_id,
            version="1",
            fields=(
                *_VERSION_FIELDS,
                ContractFieldDescriptor(
                    "evidence",
                    "EvidenceReference[]",
                    agent_id != PLANNER_ID,
                    "仅包含批准且带来源版本的证据引用。",
                ),
                ContractFieldDescriptor(
                    "role_inputs",
                    "object",
                    True,
                    input_semantics,
                ),
            ),
            purpose=f"{agent_id} 的版本化输入：{input_semantics}。",
            required_non_empty_fields=frozenset({"role_inputs"}),
            required_role_payload_keys=(
                frozenset(
                    {
                        "user_goal",
                        "market_asset_context",
                        "status_context",
                        "data_context",
                        "resource_context",
                    }
                )
                if agent_id == PLANNER_ID
                else frozenset({"subject"})
            ),
        )
        contracts[output_id] = ContractDescriptor(
            contract_id=output_id,
            version="1",
            fields=(
                *_BASE_CONTRACT_REGISTRY[AGENT_OUTPUT_CONTRACT_ID].fields,
                ContractFieldDescriptor(
                    "role_output",
                    "object",
                    True,
                    output_semantics,
                ),
            ),
            purpose=f"{agent_id} 的版本化输出：{output_semantics}。",
            required_non_empty_fields=(
                frozenset({"role_output"})
                if agent_id == PLANNER_ID
                else frozenset(
                    {
                        "role_output",
                        "unknowns",
                        "invalidation_conditions",
                    }
                )
            ),
            required_role_payload_keys=(
                frozenset(
                    {
                        "workflow_selection",
                        "node_ids",
                        "dependencies",
                        "budget",
                        "block_reasons",
                    }
                )
                if agent_id == PLANNER_ID
                else frozenset({"analysis"})
            ),
        )
    return contracts


CONTRACT_REGISTRY: Final = ContractRegistry(
    {**_BASE_CONTRACT_REGISTRY, **_role_contracts()}
)

_SPECIAL_CONDITIONS: Final = {
    "tradingagents:fundamentals_analyst": ConditionalRule(
        condition_id="issuer_or_underlying",
        description="涉及发行人或基金底层持仓，且 Planner 显式选择。",
        required_signals=frozenset({SelectionSignal.ISSUER_OR_UNDERLYING}),
    ),
    "tradingagents:sentiment_analyst": ConditionalRule(
        condition_id="qualified_sentiment_evidence",
        description="存在合格情绪证据，且 Planner 显式选择。",
        required_signals=frozenset({SelectionSignal.QUALIFIED_SENTIMENT_EVIDENCE}),
    ),
    "tradingagents:bull_researcher": ConditionalRule(
        condition_id="requires_debate",
        description="工作流需要正反论证，且 Planner 显式选择。",
        required_signals=frozenset({SelectionSignal.REQUIRES_DEBATE}),
    ),
    "finrobot:library:Software_Developer": ConditionalRule(
        condition_id="requires_code_implementation",
        description="确需受限代码实现，且隔离工作区可用。",
        required_signals=frozenset({SelectionSignal.REQUIRES_CODE_IMPLEMENTATION}),
        required_resources=frozenset({"workspace"}),
    ),
    "finrobot:library:Programmer": ConditionalRule(
        condition_id="requires_non_alpha_implementation",
        description="确需非 Alpha 工具或适配实现，且隔离工作区可用。",
        required_signals=frozenset({SelectionSignal.REQUIRES_NON_ALPHA_IMPLEMENTATION}),
        required_resources=frozenset({"workspace"}),
    ),
    "finrobot:library:IT_Specialist": ConditionalRule(
        condition_id="technical_fault",
        description="存在技术故障，且 Planner 显式选择。",
        required_signals=frozenset({SelectionSignal.TECHNICAL_FAULT}),
    ),
    "finrobot:library:Artificial_Intelligence_Engineer": ConditionalRule(
        condition_id="ai_model_or_quality_issue",
        description="涉及 AI 模型或质量异常，且 Planner 显式选择。",
        required_signals=frozenset({SelectionSignal.AI_MODEL_OR_QUALITY_ISSUE}),
    ),
    "finrobot:library:Expert_Investor": ConditionalRule(
        condition_id="requires_report_review",
        description="需要报告级复核，且 Planner 显式选择。",
        required_signals=frozenset({SelectionSignal.REQUIRES_REPORT_REVIEW}),
    ),
    "finrobot:equity:TaglineAnalystAgent": ConditionalRule(
        condition_id="requires_ui_tagline",
        description="界面需要一句话中性摘要，且 Planner 显式选择。",
        required_signals=frozenset({SelectionSignal.REQUIRES_UI_TAGLINE}),
    ),
    "finrobot:equity:fmp-stable-metrics": ConditionalRule(
        condition_id="equity_fmp_workspace_available",
        description="股票资产且 FMP 与隔离工作区可用，且 Planner 显式选择。",
        required_asset_kinds=frozenset({"equity"}),
        required_resources=frozenset({"fmp", "workspace"}),
    ),
    "quantskills:agent-derivatives-skew-sentiment-monitor": ConditionalRule(
        condition_id="option_data_available",
        description="期权隐含波动率和标的历史波动率能力可用，且 Planner 显式选择。",
        required_data_capabilities=frozenset(
            {"option_implied_volatility", "option_underlying_volatility"}
        ),
    ),
    "quantskills:agent-for-liangshuyuan-tasks": ConditionalRule(
        condition_id="complex_panda_trading_development",
        description="复杂 Panda Trading 开发且隔离工作区可用，且 Planner 显式选择。",
        required_signals=frozenset({SelectionSignal.COMPLEX_PANDA_TRADING_DEVELOPMENT}),
        required_resources=frozenset({"workspace", "panda_trading"}),
    ),
    "quantskills:agent-ssquant": ConditionalRule(
        condition_id="isolated_ssquant_simulation_available",
        description="隔离 SSQuant 仿真资源可用，且 Planner 显式选择。",
        required_resources=frozenset({"workspace", "ssquant_simulation"}),
    ),
}


def _workflow_matrix(
    agent_id: str,
    mandatory: str,
    conditional: str,
) -> MappingProxyType[WorkflowKey, WorkflowDecision]:
    matrix = {
        workflow: WorkflowDecision(WorkflowCallMode.DENIED) for workflow in WorkflowKey
    }
    for abbreviation in mandatory.split():
        matrix[_ABBREVIATIONS[abbreviation]] = WorkflowDecision(
            WorkflowCallMode.MANDATORY
        )
    for abbreviation in conditional.split():
        workflow = _ABBREVIATIONS[abbreviation]
        if matrix[workflow].mode is not WorkflowCallMode.DENIED:
            raise ValueError(f"workflow {workflow.value} cannot be both M and C")
        rule = _SPECIAL_CONDITIONS.get(
            agent_id,
            ConditionalRule(
                condition_id="planner_selected",
                description="满足工作流业务上下文且 Planner 显式选择。",
            ),
        )
        matrix[workflow] = WorkflowDecision(
            WorkflowCallMode.CONDITIONAL,
            conditional_rule=rule,
        )
    return MappingProxyType(matrix)


def _normalize_vendor_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _normalize_vendor_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        return sorted(_normalize_vendor_value(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [_normalize_vendor_value(item) for item in value]
    return value


def _definition_fingerprint(definition: AgentDefinition) -> str:
    payload = _normalize_vendor_value(definition.model_dump())
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _catalog_fingerprint(definitions: Iterable[AgentDefinition]) -> str:
    rows = sorted(
        (
            definition.agent_id,
            _definition_fingerprint(definition),
        )
        for definition in definitions
    )
    encoded = json.dumps(
        rows,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _vendor_snapshot(definition: AgentDefinition) -> VendorCapabilitySnapshot:
    declared_actions = frozenset(definition.external_actions)
    authorizations = tuple(
        (task, frozenset(actions))
        for task, actions in sorted(definition.authorization_by_task.items())
    )
    return VendorCapabilitySnapshot(
        agent_id=definition.agent_id,
        fingerprint=_definition_fingerprint(definition),
        adapter=definition.adapter.value,
        minimum_profile=definition.minimum_profile.value,
        required_resources=frozenset(definition.required_resources),
        declared_external_actions=declared_actions,
        denied_external_actions=declared_actions,
        declared_authorizations_by_task=authorizations,
        denied_authorizations_by_task=authorizations,
        effective_authorizations_by_task=(),
        effective_external_actions=frozenset(),
        source=definition.source,
        source_path=definition.source_path,
        upstream_path=definition.upstream_path,
        license=definition.license,
    )


def _execution_controls(
    definition: AgentDefinition | None,
) -> tuple[ExecutionType, ImpactClass, RiskLevel, int]:
    if definition is None:
        return ExecutionType.PLANNER, ImpactClass.COMPUTE, RiskLevel.HIGH, 15
    if definition.agent_id == "quantskills:agent-ssquant":
        return (
            ExecutionType.SANDBOX,
            ImpactClass.EXECUTION_FORBIDDEN,
            RiskLevel.CRITICAL,
            120,
        )
    if definition.adapter in {
        AgentAdapterKind.DETERMINISTIC_MONITOR,
        AgentAdapterKind.FINROBOT_METRICS,
    }:
        return ExecutionType.DETERMINISTIC, ImpactClass.COMPUTE, RiskLevel.MODERATE, 15
    if definition.minimum_profile is ExecutionProfile.WORKSPACE:
        return ExecutionType.SANDBOX, ImpactClass.SANDBOX_CODE, RiskLevel.HIGH, 120
    return ExecutionType.PROMPT, ImpactClass.READ_ONLY, RiskLevel.LOW, 60


def _tools(
    execution_type: ExecutionType,
    definition: AgentDefinition | None,
) -> frozenset[str]:
    if execution_type is ExecutionType.PLANNER:
        return frozenset(
            {
                "agent.catalog.read",
                "workflow.catalog.read",
                "resource.status.read",
                "authorization.snapshot.read",
                "task_plan.propose",
            }
        )
    base = {"evidence.read", "artifact.read", "artifact.propose"}
    if execution_type is ExecutionType.DETERMINISTIC:
        base.add("deterministic.compute")
        if definition is not None:
            base.update(
                f"resource.{name}.read" for name in definition.required_resources
            )
    if execution_type is ExecutionType.SANDBOX:
        base.update(
            {
                "sandbox.workspace.read",
                "sandbox.workspace.write",
                "sandbox.code.execute",
            }
        )
    return frozenset(base)


def _data_permissions(
    execution_type: ExecutionType,
    definition: AgentDefinition | None,
) -> frozenset[str]:
    if execution_type is ExecutionType.PLANNER:
        return frozenset(
            {
                "user_goal.read",
                "market_asset_context.read",
                "agent_status.read",
                "resource_status.read",
                "authorization_snapshot.read",
                "workflow_catalog.read",
            }
        )
    permissions = {"approved_evidence.read", "versioned_artifact.read"}
    if definition is not None:
        permissions.update(
            f"resource.{name}.read" for name in definition.required_resources
        )
    if execution_type is ExecutionType.SANDBOX:
        permissions.add("sandbox_workspace.scoped")
    return frozenset(permissions)


def _failure_policy(timeout_seconds: int) -> FailurePolicy:
    return FailurePolicy(
        retry_limits={
            FailureKind.TRANSIENT: 2,
            FailureKind.VALIDATION: 0,
            FailureKind.AUTHENTICATION: 0,
            FailureKind.PERMISSION: 0,
        },
        total_attempt_limit=3,
        total_duration_seconds=timeout_seconds * 3,
    )


def _governance_relations(agent_id: str) -> tuple[str, ...]:
    if agent_id == PLANNER_ID:
        return (
            "受确定性路由优先级、资源、权限与风险门治理。",
            "只提出工作流或 TaskPlan，不审查研究事实。",
        )
    if agent_id == "tradingagents:research_manager":
        return (
            "审查研究 Agent 的证据链、分歧和质量门。",
            "其通过建议仍受确定性证据、新鲜度、权限和硬风险门约束。",
        )
    if agent_id == "quantskills:liangshuyuan:test-agent":
        return ("独立审查量化实现与验收测试；不得修改被测实现。",)
    if agent_id == "quantskills:liangshuyuan:main-agent":
        return ("汇总量化开发和独立测试结果；失败测试不得被覆盖。",)
    return (
        "输出接受对应工作流治理 Agent 审查。",
        "最终资格由确定性字段、证据、新鲜度、权限和硬风险门决定。",
    )


def _entry(
    *,
    agent_id: str,
    responsibility: str,
    mandatory: str,
    conditional: str,
    specific_prohibition: str,
    definition: AgentDefinition | None,
) -> AgentGovernanceEntry:
    execution_type, impact_class, risk_level, timeout_seconds = _execution_controls(
        definition
    )
    slug = _contract_slug(agent_id)
    input_contract_id = f"financegod.agent-input.{slug}.v1"
    output_contract_id = f"financegod.agent-output.{slug}.v1"
    return AgentGovernanceEntry(
        agent_id=agent_id,
        chinese_responsibility=responsibility,
        capability_boundary=(
            f"仅可{responsibility}，通过版本化输入和产物通信；"
            "不得掌握或修改交易与授权事实。"
        ),
        workflow_matrix=_workflow_matrix(agent_id, mandatory, conditional),
        input_contract_id=input_contract_id,
        output_contract_id=output_contract_id,
        tool_allowlist=_tools(execution_type, definition),
        data_permission_allowlist=_data_permissions(execution_type, definition),
        risk_level=risk_level,
        impact_class=impact_class,
        execution_type=execution_type,
        timeout_seconds=timeout_seconds,
        failure_policy=_failure_policy(timeout_seconds),
        default_requirement=NodeRequirement.REQUIRED,
        evidence_requirements=frozenset(
            {
                "只使用批准且版本化的输入证据。",
                "事实必须引用证据 ID，并区分推断、未知项和失效条件。",
                "资源缺失、低置信度或失败必须显式输出。",
            }
        ),
        governance_relations=_governance_relations(agent_id),
        prohibited_behaviors=(*_COMMON_PROHIBITIONS, specific_prohibition),
        version=CATALOG_VERSION,
        vendor_capability=(
            None if definition is None else _vendor_snapshot(definition)
        ),
    )


class AgentGovernanceCatalog:
    """Validated Finance-God overlay; it never mutates the vendor registry."""

    def __init__(
        self, vendor_definitions: Iterable[AgentDefinition] | None = None
    ) -> None:
        expected_product_ids = {row[0] for row in _ROWS} | {PLANNER_ID}
        if set(_ROLE_CONTRACT_SEMANTICS) != expected_product_ids:
            raise ValueError("role contract registry must cover all 44 Agent IDs")
        definitions = tuple(
            AgentRegistry().list() if vendor_definitions is None else vendor_definitions
        )
        vendor_by_id = {definition.agent_id: definition for definition in definitions}
        if len(vendor_by_id) != len(definitions):
            raise ValueError("vendor Agent identifiers must be unique")
        actual_fingerprint = _catalog_fingerprint(definitions)
        if actual_fingerprint != VENDOR_CATALOG_FINGERPRINT:
            raise ValueError(
                "vendor capability fingerprint drift; "
                f"expected={VENDOR_CATALOG_FINGERPRINT}, actual={actual_fingerprint}"
            )

        expected_vendor_ids = {row[0] for row in _ROWS}
        actual_vendor_ids = set(vendor_by_id)
        if actual_vendor_ids != expected_vendor_ids:
            missing = sorted(expected_vendor_ids - actual_vendor_ids)
            unexpected = sorted(actual_vendor_ids - expected_vendor_ids)
            raise ValueError(
                f"vendor catalog drift; missing={missing}, unexpected={unexpected}"
            )

        entries = [
            _entry(
                agent_id=agent_id,
                responsibility=responsibility,
                mandatory=mandatory,
                conditional=conditional,
                specific_prohibition=prohibition,
                definition=vendor_by_id[agent_id],
            )
            for agent_id, responsibility, mandatory, conditional, prohibition in _ROWS
        ]
        entries.append(
            _entry(
                agent_id=PLANNER_ID,
                responsibility="产品级规划与编排",
                mandatory=" ".join(_ABBREVIATIONS),
                conditional="",
                specific_prohibition=(
                    "不研究，不绕过选择优先级，不扩大权限，不接触交易事实。"
                ),
                definition=None,
            )
        )
        self._entries = MappingProxyType({entry.agent_id: entry for entry in entries})
        self._validate(entries)

    @staticmethod
    def _validate(entries: list[AgentGovernanceEntry]) -> None:
        identifiers = [entry.agent_id for entry in entries]
        if len(identifiers) != 44 or len(set(identifiers)) != 44:
            raise ValueError(
                "Finance-God Agent catalog must contain 44 unique identifiers"
            )
        for entry in entries:
            if entry.tool_allowlist & TRADE_WRITE_TOOLS:
                raise ValueError(
                    f"{entry.agent_id} authorizes a prohibited trading tool"
                )
            if entry.agent_id != PLANNER_ID and not any(
                decision.mode is not WorkflowCallMode.DENIED
                for decision in entry.workflow_matrix.values()
            ):
                raise ValueError(
                    f"{entry.agent_id} must map to at least one formal workflow"
                )
            if entry.input_contract_id not in CONTRACT_REGISTRY:
                raise ValueError(f"{entry.agent_id} input contract is not registered")
            if entry.output_contract_id not in CONTRACT_REGISTRY:
                raise ValueError(f"{entry.agent_id} output contract is not registered")
            capability = entry.vendor_capability
            if capability is not None:
                if capability.effective_external_actions:
                    raise ValueError(
                        f"{entry.agent_id} effective external actions must be empty"
                    )
                if capability.effective_authorizations_by_task:
                    raise ValueError(
                        f"{entry.agent_id} effective external authorizations must be empty"
                    )
                if not capability.declared_external_actions.issubset(
                    capability.denied_external_actions
                ):
                    raise ValueError(
                        f"{entry.agent_id} vendor external actions must be explicitly denied"
                    )
        planner = next(entry for entry in entries if entry.agent_id == PLANNER_ID)
        if any(
            decision.mode is not WorkflowCallMode.MANDATORY
            for decision in planner.workflow_matrix.values()
        ):
            raise ValueError("financegod:planner must cover all 15 workflows")
        if planner.vendor_capability is not None:
            raise ValueError(
                "financegod:planner must remain outside the vendor runtime"
            )
        ssquant = next(
            entry for entry in entries if entry.agent_id == "quantskills:agent-ssquant"
        )
        if not {"ctp_start", "order_cancel", "order_entry"}.isdisjoint(
            ssquant.tool_allowlist
        ):
            raise ValueError("SSQuant trading actions must remain denied")
        ssquant_capability = ssquant.vendor_capability
        expected_ssquant_actions = frozenset(
            {"ctp_start", "order_cancel", "order_entry"}
        )
        if (
            ssquant_capability is None
            or ssquant_capability.declared_external_actions != expected_ssquant_actions
            or ssquant_capability.denied_external_actions != expected_ssquant_actions
            or ssquant_capability.effective_external_actions
        ):
            raise ValueError("SSQuant vendor external actions must all be denied")
        declared_authorizations = dict(
            ssquant_capability.declared_authorizations_by_task
        )
        denied_authorizations = dict(ssquant_capability.denied_authorizations_by_task)
        if (
            declared_authorizations.get("live_trading") != expected_ssquant_actions
            or denied_authorizations.get("live_trading") != expected_ssquant_actions
            or ssquant_capability.effective_authorizations_by_task
        ):
            raise ValueError("SSQuant live_trading authorization drift")

    def get(self, agent_id: str) -> AgentGovernanceEntry:
        try:
            return self._entries[agent_id]
        except KeyError as error:
            raise ValueError(f"unknown Finance-God Agent: {agent_id}") from error

    def list(self) -> tuple[AgentGovernanceEntry, ...]:
        return tuple(self._entries.values())

    def for_workflow(
        self,
        workflow: WorkflowKey | str,
        context: WorkflowSelectionContext | None = None,
    ) -> tuple[AgentGovernanceEntry, ...]:
        try:
            key = (
                workflow if isinstance(workflow, WorkflowKey) else WorkflowKey(workflow)
            )
        except ValueError as error:
            raise ValueError(f"unknown formal workflow: {workflow}") from error
        return tuple(entry for entry in self.list() if entry.is_allowed(key, context))

    def __len__(self) -> int:
        return len(self._entries)
