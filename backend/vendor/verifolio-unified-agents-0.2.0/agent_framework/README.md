# VeriFolio Unified Agent Runtime

`research_runtime` 现在只有一套 Agent 框架：统一定义、注册、能力路由、执行配置、
LangGraph 编排和结果信封。旧的 DuoAgent、FullResearchWorkflow、Monitor/FinRobot
专用工作流及隔离 Research Mesh 已移除。

## Agent 覆盖

注册表包含 44 个有本地实现且能按 ID 调用的 Agent：

| 来源 | 数量 | 本地适配 |
| --- | ---: | --- |
| TradingAgents | 12 | 结构化、证据约束的提示词角色 |
| FinRobot | 18 | 结构化提示词角色 |
| FinRobot Metrics | 1 | 受控 FMP/本地工件适配器 |
| QuantSkills Monitor | 4 | 确定性 PandaData 适配器 |
| QuantSkills Workflow | 9 | 结构化开发、测试、编排与发布角色 |

`quantskills:agent-macro-driven-rotation` 没有可核验源码，
`ai-trader:platform-agent-identity` 不是可复用 Agent；二者已按明确决策从 Agent
目录删除，不生成替代语义。

`definitions.py` 是唯一 Agent 真相源。`catalog/agents.json` 和
`catalog/agent-table.md` 都由它生成：

```bash
cd agent_framework
.venv/bin/python scripts/build_agent_catalog.py
.venv/bin/python -m research_runtime.catalog --verify
```

## 统一契约

每次运行只接受 `AgentRequest`，并返回 `AgentRun`：

- `AgentRegistry` 按稳定 `agent_id` 提供全部定义；
- `AgentRouter` 默认按任务、资产、标签、资源和执行配置选择最小集合，也支持
  `requested_agent_ids` 点名；
- `AgentRunner` 把计划编译成 LangGraph，所有适配器返回统一的
  `AgentResult`；
- 研究输出使用带作者与证据引用的 `Claim`，数据适配器还可附加安全审计元数据和
  `AgentArtifact`；
- JSON 结构无效、证据引用未知、资源缺失或权限不足时明确失败，不回退为自由文本或
  模拟成功。

执行配置是逐次请求门禁：

| 配置 | 边界 |
| --- | --- |
| `research` | 证据推理和只读确定性 Monitor |
| `workspace` | 允许选择本地开发语义角色和显式本地工件适配器 |
| `external` | 允许选择声明了外部语义的角色，但具体发布/CTP 动作还必须列入 `authorized_actions` |

提示词角色只返回 `proposed_actions`，不会自行修改文件、发布仓库或操作账户。当前唯一会写
本地文件的适配器是 `finrobot:equity:fmp-stable-metrics`，输出固定在已忽略的
`live-runs/finrobot/`。框架没有实现发布、注册、跟单、订单或资金动作。

## Python 使用

```python
from research_runtime import AgentRequest, AgentRunner, AssetKind
from research_runtime.config import Settings
from research_runtime.llm import OpenAICompatibleChat
from research_runtime.models import EvidenceRecord

request = AgentRequest(
    run_id="company-review-1",
    subject="示例基础设施公司",
    task_type="research",
    asset_kind=AssetKind.EQUITY,
    tags={"company_deep_dive", "risk_review"},
    evidence=[
        EvidenceRecord(
            identifier="E1",
            source="公司公告",
            excerpt="收入同比增长 18%。",
        )
    ],
)
runner = AgentRunner(
    chat_client=OpenAICompatibleChat(Settings.from_environment()),
)
result = runner.run(request)
```

点名调用时设置 `requested_agent_ids`。点名会跳过能力匹配，但不会绕过执行配置、资源或逐次
动作授权。

## CLI

统一入口为 `verifolio-agent`：

```bash
verifolio-agent \
  --run-id company-review-1 \
  --subject "示例基础设施公司" \
  --task-type research \
  --asset-kind equity \
  --tag company_deep_dive \
  --evidence "E1|公司公告|收入同比增长 18%。"
```

执行确定性 Monitor 时点名 Agent、声明数据资源，并通过 `--payload-json` 传入其
`PandaMonitorRequest`：

```bash
verifolio-agent \
  --run-id crowding-1 \
  --subject "平安银行拥挤度" \
  --task-type research \
  --asset-kind equity \
  --agent-id quantskills:agent-crowding-risk-monitor \
  --resource margin \
  --resource lhb_list \
  --payload-json '{"kind":"crowding_risk","subject":"平安银行拥挤度","symbol":"000001.SZ","start_date":"20250102","end_date":"20250110"}'
```

外部语义角色必须同时使用 `--profile external`、所需 `--resource` 和逐项
`--authorize-action`。这些参数只通过门禁，不会为尚未实现的外部执行器制造成功结果。

## MCP

`verifolio-agent-mcp` 是 stdio 服务，统一提供：

- `list_agents`
- `get_agent`
- `plan_agents`
- `run_agents`
- `catalog://agents`
- `catalog://skills`

它不再暴露旧的 Monitor 或 PandaData 专用 Agent 工具。PandaData 仍通过 Monitor
适配器使用固定数据白名单；FMP 密钥只通过环境变量进入隔离进程。

## 验证

```bash
cd agent_framework
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.panda-venv/bin/python -m pytest -q tests/test_mcp_server.py
.venv/bin/python scripts/build_agent_catalog.py --check
.venv/bin/python -m research_runtime.catalog --verify
```

