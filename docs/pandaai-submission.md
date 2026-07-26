# Finance-God 多智能体投研 Agent —— PandaAI「交易未来」赛道作品说明

> AdventureX 26 · PandaAI Build the Next AI Trader 赛道提交材料

| 提交项 | 内容 |
|---|---|
| Agent 名称 | Finance-God 多智能体投研 Agent |
| Agent Card URL | `http://124.221.77.214:8000/.well-known/agent-card.json` |
| A2A Endpoint | `http://124.221.77.214:8000/a2a`（JSONRPC，支持流式） |
| 鉴权方式 | 无需鉴权 |
| 底座模型 | DeepSeek V4 Pro |
| 代码仓库 | <https://github.com/Xustalis/Finance-God> |

---

## 1. 项目简介（Project Overview）

Finance-God 是一个**中文优先的多智能体投研与仿真交易系统**。它不是一个聊天机器人，而是一支 AI 投研团队：接到自然语言任务后，由 **Planner 从 44-Agent 治理目录中选拨分析师团队**（基本面 / 行情 / 情绪 / 新闻分析师、多空研究员、研究经理、组合管理人等角色）并行执行研究，每个结论**区分事实与推断并引用证据编号**，最后由研究经理综合观点与分歧，产出结构化研究报告。

本次参赛以 **A2A Remote Agent** 形式提交（对应赛道方向 ⑤ Multi-Agent Workflow + ③ Research Agent）：通过标准 A2A 0.3 协议网关对外暴露系统能力，评测平台可直接发现 Agent Card、发送自然语言任务并实时观察多智能体协作过程。

**定位与边界**：所有输出仅用于投研教育与仿真演示——不执行真实券商交易、不承诺收益、不构成投资建议，输出均附风险提示。

## 2. 核心功能（Core Features）

1. **多智能体协作研究（旗舰能力）**
   Planner 依据任务语义从 44-Agent 目录做能力路由（capability route），动态选拨 3-5 个角色并行研究；研究经理汇总各角色结论、显式呈现观点分歧。全过程在流式模式下实时推送（研究计划 → 各角色进展 → 综合结论）。
2. **16 类研究工作流**
   市场环境解读、公司深度研究、组合压力测试、仿真交易计划、交易复盘等，A2A Skills 与系统真实工作流一一对应（不虚构能力）。
3. **可解释输出**
   每份报告包含「执行过程」小节，留痕 Planner 选拨结果与各阶段进展；结论区分事实 / 推断，引用证据编号。
4. **流式 A2A**
   `message/stream` 输出 task → status-update（研究计划、阶段进展）→ artifact-update（正文分块）→ 终态 status-update 的标准事件序列，评测方可实时观察智能体协作。
5. **工程稳态**
   服务器 systemd 守护（崩溃自愈 + 开机自启）、并发任务限流、请求体积/提示词长度限制、20 分钟内完成（实测研究型任务 ~90-150 秒）。

## 3. 技术架构（Architecture）

```
评测平台 / A2A 客户端
        │  A2A 0.3 (JSONRPC · message/send | message/stream SSE)
        ▼
┌───────────────────────────────────────────────┐
│  A2A 网关 (a2a-gateway/, 纯 Python 标准库)      │
│  Agent Card 发现 · JSON-RPC 路由 · SSE 流式     │
│  并发限流 · Bearer 鉴权(可选) · 错误边界        │
└───────────────┬───────────────────────────────┘
                ▼
┌───────────────────────────────────────────────┐
│  引擎层 (engine.py, 三级自动降级)               │
│  ① MultiAgentRuntime 多智能体编排（主路径）     │
│  ② DeepSeek 直答（运行时不可用时兜底）          │
│  ③ 离线演示（无凭据时最后兜底）                 │
└───────────────┬───────────────────────────────┘
                ▼
┌───────────────────────────────────────────────┐
│  MultiAgentRuntime (finance_god.orchestration) │
│  Planner ──选拨──► 44-Agent 治理目录            │
│    ├─ Fundamentals Analyst（基本面）            │
│    ├─ Market Analyst（行情）                    │
│    ├─ Sentiment / News Analyst（情绪/新闻）     │
│    ├─ Bull / Bear Researcher（多空研究员）      │
│    └─ Research Manager（综合结论与分歧）        │
│  research_runtime 编排框架（langgraph）         │
│  数据情报员：背景简报采集（标注非实时行情）      │
└───────────────┬───────────────────────────────┘
                ▼
        DeepSeek V4 Pro（底座模型）
```

- **主系统**（本仓库 backend/frontend）：FastAPI + React 的完整投研/仿真交易产品，集成 PandaData 行情（`/api/market/*`：快照、K 线、指数等）与仿真撮合。
- **A2A 网关**：零第三方依赖的独立进程，通过 `sys.path` 复用主系统的编排层与 vendor 框架源码，部署脚本见 `deploy/a2a-gateway/`。
- **诚实性设计**：网关背景简报明确标注「模型知识库，非实时行情」；Skills 描述与系统真实工作流一一对应。

## 4. Skills 调用方式

Agent Card 声明 7 个 skill，均可通过统一的 A2A 接口以自然语言触发（平台按 Card 自动识别）：

| Skill ID | 名称 | 触发示例 |
|---|---|---|
| `multi-agent-research` | 多智能体协作研究 | 「分析新能源行业的投资逻辑和主要风险」 |
| `market-context` | 市场环境解读 | 「最近A股市场整体环境怎么样？」 |
| `company-research` | 公司深度研究 | 「帮我研究一下贵州茅台的基本面」 |
| `portfolio-stress` | 组合压力与风险讲解 | 「讲讲组合压力测试怎么做」 |
| `trade-plan-simulation` | 仿真交易计划讲解 | 「帮我生成一份教学交易计划」 |
| `post-trade-review` | 交易复盘 | 「复盘一下我上周的仿真交易」 |
| `investment-qa` | 投资概念问答 | 「什么是夏普比率？」 |

**同步调用（message/send）：**

```bash
curl -X POST http://124.221.77.214:8000/a2a \
  -H "content-type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": "1", "method": "message/send",
    "params": {"message": {"messageId": "m1", "role": "user",
      "parts": [{"kind": "text", "text": "分析一下白酒行业的投资机会与风险"}]}}
  }'
```

**流式调用（message/stream，SSE）**：同一 endpoint，`method` 改为 `message/stream`，返回 `text/event-stream`，事件序列 `task(working) → status-update(研究计划/进展) → artifact-update(正文) → status-update(final, completed)`。

## 5. 示例问题与预期输出（已实测）

### 示例 1：行业研究（多智能体协作，实测 92 秒）

**问题**：`分析一下白酒行业的投资机会与风险`

**实际输出**（节选，全文约 5000 字）：

```markdown
# 多智能体研究报告
任务：分析一下白酒行业的投资机会与风险

## 背景简报（模型知识库，非实时行情）
- 子赛道分层：超高端（茅台）、高端（五粮液、国窖）、次高端……
- 竞争壁垒：品牌护城河是核心……CR5 持续提升，挤压式增长是常态。

（基本面 / 行情 / 消息面 / 多空观点 各角色分析正文……）

- 长期风险：年轻一代消费偏好变化，构成行业长期需求的根本性隐忧。

---
风险提示：以上内容基于公开信息与模型推理，仅供投研教育与仿真演示，
不构成任何投资建议；历史规律不代表未来表现，市场有风险，决策需独立判断。

## 执行过程
- 数据情报员正在收集背景素材……
- 研究计划已生成：Planner 选拨 4 个智能体 —— Fundamentals Analyst、
  Market Analyst、News Analyst、Support Researcher（capability route matched）
- 各角色分析完成，研究经理正在综合结论……
```

### 示例 2：公司深度研究

**问题**：`研究一下贵州茅台的基本面、估值水平和主要风险`

**预期输出**：多智能体研究报告结构同上；Planner 选拨基本面分析师、多空研究员等角色，输出盈利能力 / 现金流 / 估值分位 / 多空论点对照与风险清单，附执行过程与风险提示。

### 示例 3：投资概念问答（直答路径，秒级响应）

**问题**：`什么是夏普比率？一句话`

**实际输出**：

> 夏普比率衡量的是每承担一单位总风险，能获得多少超过无风险收益的超额回报，数值越高代表风险调整后的表现越好。

## 6. 结果展示与评测记录

- **A2A 合规评测（agent-check）全项通过**：card-input / card-validation / call / stream 四项 `passed`，`streamingOk: true`（对公网地址分别以 card-url 与 service-url 两种发现模式实测）。
- **协议边界行为**：非法 JSON → `-32700`；非法 RPC → `-32600`；未知方法 → `-32601`；空 parts → `-32602`，均符合 JSON-RPC 2.0。
- **性能**：概念直答 5-15 秒；多智能体研究 90-150 秒（赛道上限 20 分钟）。
- **稳定性**：systemd `Restart=always` + 开机自启，评审期间持续在线。

## 7. 使用的数据 Skills / 投研 Skills

- **数据能力**：主系统集成 PandaData 行情数据（股票快照、K 线、指数行情，`backend/finance_god/market_data/`）；A2A 网关研究流程中的背景简报来自模型知识库并如实标注「非实时行情」，不访问任何未授权数据源。
- **投研能力（系统内置）**：多角色研究编排、多空论点对照、组合压力测试讲解（回撤/集中度/流动性维度）、仿真交易计划与执行复核、交易复盘归因、投研报告生成（本次 A2A 提交的核心展示能力）。

## 8. 合规声明

- 输出仅用于投研教育与仿真演示，**不构成投资建议**，每份报告结尾附风险提示。
- 不执行真实券商交易；交易相关能力均为仿真环境演示。
- 未使用未授权数据、接口或第三方服务；模型调用使用 DeepSeek 官方 API。
- Agent 凭据不写入公开 Agent Card。

## 9. 团队信息

团队：Finance-God Team

| 成员 | 院校/专业/年级 | 分工 |
|---|---|---|
| 蔡锦万 | 东南大学 / 网络信息安全 / 研二 | 产品定义、演示设计、项目统筹与答辩 |
| 李耘辉 | 河南大学 / 软件工程 / 大三 | 全栈开发、风险规则、Agent 部署 |
| 徐浩博 | 计算机科学与技术 / 大二 | 全栈开发、画像流程、数据部署与测试 |
| 赖郑倬 | 西南交通大学 / 安全工程 / 大二 | 项目统筹、产品设计 |

## 10. 本地复现与部署

```bash
# 本地运行 A2A 网关（Python ≥ 3.11）
cd a2a-gateway && python3 server.py
# Agent Card: http://localhost:4176/.well-known/agent-card.json

# 服务器部署（幂等脚本：venv + 依赖 + systemd）
bash deploy/a2a-gateway/deploy.sh
```

详见 [`a2a-gateway/README.md`](../a2a-gateway/README.md) 与 [`deploy/a2a-gateway/`](../deploy/a2a-gateway/)。
