"""Finance-God A2A Agent Card。

Card 遵循 A2A 0.3 / JSONRPC binding 规范：
- defaultOutputModes 使用通用文本类输出模式（text/plain、text/markdown、application/json）；
- capabilities.streaming=true 并由网关实现 message/stream 终态事件序列；
- skills 对应 Finance-God 真实的 desk 工作流（finance_god.agents.contracts.WorkflowKey）
  与 44-Agent 治理目录（finance_god.agents.catalog），不虚构不存在的能力。
"""

from __future__ import annotations

AGENT_VERSION = "1.0.0"


def build_agent_card(base_url: str) -> dict:
    return {
        "protocolVersion": "0.3",
        "name": "Finance-God 多智能体投研 Agent",
        "description": (
            "Finance-God 是中文优先的多智能体投研与仿真交易系统。"
            "接到自然语言任务后，由 Planner 从 44-Agent 治理目录中选拨分析师团队"
            "（基本面/行情/情绪/新闻分析师、多空研究员、研究经理、组合管理人等角色）"
            "并行执行研究，每个结论区分事实与推断并引用证据编号，最后由研究经理综合"
            "观点与分歧。系统内置 16 类研究工作流（市场环境、公司研究、组合压力、交易"
            "计划、交易复盘等），底座模型为 DeepSeek V4 Pro。所有输出仅用于投研教育与"
            "仿真演示：不执行真实券商交易，不承诺收益，不构成投资建议，输出均附风险提示。"
        ),
        "url": f"{base_url}/a2a",
        "preferredTransport": "JSONRPC",
        "version": AGENT_VERSION,
        "provider": {
            "organization": "Finance-God Team",
            "url": base_url,
        },
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "text/markdown", "application/json"],
        "skills": [
            {
                "id": "multi-agent-research",
                "name": "多智能体协作研究",
                "description": (
                    "核心能力：Planner 根据任务从 44-Agent 目录选拨分析师团队并行研究，"
                    "产出带证据引用的分角色结论（事实/推断分类），研究经理综合观点与"
                    "分歧。流式模式下实时推送研究计划与各阶段进展，过程完整可解释。"
                ),
                "tags": ["finance", "multi-agent", "research", "workflow"],
                "examples": [
                    "分析新能源行业的投资逻辑和主要风险",
                    "研究一家白酒龙头公司的基本面多空论点",
                ],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain", "text/markdown"],
            },
            {
                "id": "market-context",
                "name": "市场环境解读",
                "description": (
                    "对应 market_context 工作流：结合行情快照与市场观察，"
                    "输出教学性的市场结构、指数走势与情绪解读。"
                ),
                "tags": ["finance", "market", "education"],
                "examples": ["最近A股市场整体环境怎么样？", "解读一下当前大盘走势"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain", "text/markdown"],
            },
            {
                "id": "company-research",
                "name": "公司深度研究",
                "description": (
                    "对应 company_research 工作流：由基本面/行情/情绪/新闻分析师、"
                    "多空研究员与研究经理等多 Agent 角色协作，产出带证据引用的教学研究结论。"
                ),
                "tags": ["finance", "research", "multi-agent"],
                "examples": ["帮我研究一下贵州茅台的基本面", "分析这家公司的多空论点"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain", "text/markdown"],
            },
            {
                "id": "portfolio-stress",
                "name": "组合压力与风险讲解",
                "description": (
                    "对应 portfolio_stress 工作流：从回撤、集中度、流动性等维度"
                    "讲解仿真组合的压力测试思路与风险控制要点。"
                ),
                "tags": ["finance", "portfolio", "risk"],
                "examples": ["我的组合回撤风险大吗？", "讲讲组合压力测试怎么做"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain", "text/markdown"],
            },
            {
                "id": "trade-plan-simulation",
                "name": "仿真交易计划讲解",
                "description": (
                    "对应 trade_plan_generation 工作流：讲解仿真盘交易计划的生成、"
                    "订单草稿预填与执行复核流程；全部为仿真环境，不涉及真实资金。"
                ),
                "tags": ["finance", "simulation", "trading"],
                "examples": ["演示一笔仿真买入的完整流程", "帮我生成一份教学交易计划"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain", "text/markdown"],
            },
            {
                "id": "post-trade-review",
                "name": "交易复盘",
                "description": (
                    "对应 post_trade_review 工作流：对仿真交易记录做教学性复盘，"
                    "总结决策依据、执行偏差与可改进点。"
                ),
                "tags": ["finance", "review", "education"],
                "examples": ["复盘一下我上周的仿真交易"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain", "text/markdown"],
            },
            {
                "id": "investment-qa",
                "name": "投资概念问答",
                "description": (
                    "对应交易台直答路径：对投资概念、风险等级、投资者画像等"
                    "教学问题给出直接、自然、简洁的中文回答。"
                ),
                "tags": ["finance", "education", "qa"],
                "examples": ["什么是稳健型投资者？", "帮我分析一个稳健型投资者的画像"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            },
        ],
    }
