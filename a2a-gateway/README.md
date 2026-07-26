# Finance-God A2A 网关

Finance-God 系统的标准 A2A（Agent-to-Agent）协议接口，
以 A2A 0.3 / JSON-RPC binding 对外暴露系统的 agent 编排能力，
可被任何 A2A 兼容客户端发现与调用。

## 快速开始（零依赖）

```bash
python3 a2a-gateway/server.py
```

- Agent Card：`http://localhost:4176/.well-known/agent-card.json`
- A2A 端点：`POST http://localhost:4176/a2a`（`message/send` / `message/stream`）

A2A 客户端以服务地址 `http://localhost:4176` 即可自动发现 Agent Card。

## 任务编排

- **研究型任务**（分析/研究/多空/因子/回测等语义）→ 多智能体编排流水线：
  数据情报员背景简报（证据 E2）→ Planner 从 44-Agent 目录选拨分析师团队 →
  各角色并行研究（结论区分事实/推断并引用证据编号）→ 研究经理综合观点与分歧；
  流式模式下实时推送研究计划与阶段进展（status-update 事件）
- **概念型问题**（什么是/解释等前缀）→ 直答引擎（秒级响应）
- 研究中途失败自动降级直答，任何情况下终态保持 completed

## 回答引擎（自动降级）

| 优先级 | 引擎 | 条件 | 说明 |
| --- | --- | --- | --- |
| 1 | `runtime` | 后端依赖已装 + ARK 凭据 | 进程内复用 `MultiAgentRuntime`（与 /desk Agent 面板同一编排入口） |
| 2 | `deepseek` | `DEEPSEEK_API_KEY` | 直连 DeepSeek V4 Pro，复用 desk 直答提示词约束 |
| 3 | `demo` | 无 | 确定性教学演示（复用 desk_intent 路由语义，回答中明确标注演示模式） |

用 `A2A_ENGINE=runtime|deepseek|demo` 可强制指定。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `A2A_GATEWAY_HOST` / `A2A_GATEWAY_PORT` | `localhost` / `4176` | 监听地址（localhost 自动双栈监听 IPv4+IPv6） |
| `A2A_PUBLIC_BASE_URL` | `http://HOST:PORT` | 对外发布时写入 Card 的接口地址 |
| `A2A_GATEWAY_TOKEN` | 空（无鉴权） | 设置后启用 Bearer 鉴权 |
| `A2A_ENGINE` | `auto` | 强制引擎 |
| `A2A_RESEARCH` | `auto` | `off` 关闭多智能体研究模式 |
| `A2A_MAX_AGENTS` | `4` | 单次研究选拨的智能体上限（1-43） |
| `A2A_TASK_TIMEOUT_S` | `1000` | 多智能体执行阶段超时（秒） |
| `A2A_MAX_CONCURRENT_TASKS` | `3` | 同时处理的任务数上限 |

## 协议实现要点（A2A 0.3）

- `message/send` → `result.kind="message"`、`role="agent"`、非空 `messageId` 与 `parts`
- `message/stream` → SSE 事件序列：`task(working)` → `artifact-update*` → `status-update(final=true, completed)`，每个事件均为与请求 id 一致的完整 JSON-RPC envelope
- 错误统一走 JSON-RPC error 分支（-32700 / -32600 / -32601 / -32602 / -32603）
- 请求体同时支持 `Content-Length` 与 `Transfer-Encoding: chunked`
