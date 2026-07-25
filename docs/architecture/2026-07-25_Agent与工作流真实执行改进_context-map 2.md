# Agent 与工作流真实执行改进：Context Map

> 日期：2026-07-25  
> 任务：研究并改进生产 `/desk` 的 Agent 与工作流前后端闭环，消除假完成、跨用户领取和无产物可读的问题。

## Context Map

### Files to Modify

| File | Purpose | Changes Needed |
|---|---|---|
| `backend/finance_god/application/workflow_worker.py` | queued Run 的执行入口与节点 Runner | 以真实 Multi-Agent runtime 执行 Agent 节点；未接入的确定性服务显式失败；完成前保存真实证据产物 |
| `backend/finance_god/orchestration/multi_agent.py` | 统一 Agent runtime 适配 | 暴露真实可用资源，避免按目录声明不存在的能力 |
| `backend/finance_god/orchestration/workflow_registry.py` | 正式工作流节点与预算 | 按顺序执行的 Agent 组使用总预算，避免把单 Agent 超时误当整组超时 |
| `backend/finance_god/api/workflow_routes.py` | 工作流创建、读取与进度 API | 新增交易台专用创建合同并在服务端选择工作流；移除普通用户可调用的跨用户 `claim` |
| `backend/finance_god/api/desk_routes.py` | 交易台 bootstrap 能力 | 领取能力固定关闭；Worker 能力反映实际配置 |
| `backend/server.py` | 生产依赖装配 | 给 Worker 注入真实 Agent runtime、画像投影和证据记录器 |
| `backend/scripts/run_workflow_worker.py` | 独立 Worker 入口 | 与进程内 Worker 使用同一真实 runtime 和 Evidence 记录器 |
| `backend/vendor/verifolio-unified-agents-0.2.0/agent_framework/src/research_runtime/adapters.py` | 结构化研究提示合同 | 示例使用真实 evidence ID；研究声明规则与严格校验保持一致 |
| `backend/tests/workflows/test_workflow_worker.py` | Worker 行为测试 | 验证真实 runtime 调用、证据记录、runtime 失败不完成、未接服务不伪造 |
| `backend/tests/api/test_workflow_routes.py` | HTTP 合同测试 | 验证交易台意图路由、幂等、进度和领取接口不可公开 |
| `backend/tests/api/test_desk_bootstrap.py` | bootstrap 能力测试 | 验证 `workflow_claim=false` 与 Worker 配置透传 |
| `backend/vendor/verifolio-unified-agents-0.2.0/agent_framework/tests/test_runner.py` | 统一 Agent 提示测试 | 验证提示使用存在的证据 ID，且研究声明不可为空 |
| `frontend/src/services/tradingDesk.ts` | 交易台类型化 API 适配 | 使用 `/workflows/desk`；增加真实 progress 与 evidence 读取合同 |
| `frontend/src/stores/tradingDesk.ts` | Agent/工作流唯一客户端状态 | 去掉浏览器工作流分类；保存 intent/progress/evidence/submitting；恢复活动任务；隐藏页暂停、恢复立即刷新 |
| `frontend/src/components/desk/DeskAgentPanel.vue` | 右侧常驻 Agent | 展示输入意图、真实节点进度、终态错误和结构化产物；活动任务期间阻止覆盖 |
| `frontend/src/styles.css` | Agent 线程与产物排版 | 使用规则线、列表和报刊式层级承载进度/产物，不新增卡片或强调色 |
| `frontend/src/tests/rebuilding.spec.ts` | 生产交易台交互测试 | 覆盖创建、轮询、真实进度、产物、失败与恰好三条快捷指令 |
| `docs/page-design/briefs/2026-07-25_Agent与工作流真实执行改进设计简报.md` | 实施前设计简报 | 记录用户任务、信息层级、数据状态、操作条件、宽度和视觉论点 |
| `docs/page-design/pages/交易台.md` | `/desk` 规范 | 更新 Agent 真实进度、产物和活动任务约束 |
| `docs/page-design/02_前后端职责与数据合同.md` | 前后端合同 | 更新交易台创建入口、产物读取、Worker 真实性与领取边界 |
| `docs/page-design/acceptance/2026-07-25_Agent与工作流真实执行改进验收.md` | 实施后验收 | 逐项记录通过/失败/不适用与证据 |

### Dependencies (may need updates)

| File | Relationship |
|---|---|
| `backend/finance_god/orchestration/workflow_executor.py` | DAG、重试、质量门、节点产物和终态的唯一执行状态机 |
| `backend/finance_god/application/evidence_service.py` | 把真实 `AgentRun` 保存为可读、可追溯的 Evidence bundle |
| `backend/finance_god/infrastructure/persistence/workflow_repository.py` | FIFO queued 查询、CAS 和执行审计；不新增第二状态源 |
| `frontend/src/views/TradingDeskView.vue` | Agent 面板壳层和 `/desk` 生命周期 |
| `docs/page-design/01_前端统一设计规范.md` | 双栏、纸面/墨色、三条指令、真实状态和失败可见的规范来源 |

### Test Files

| Test | Coverage |
|---|---|
| `backend/tests/workflows/test_workflow_worker.py` | Worker 执行、失败、证据与批次 |
| `backend/tests/workflows/test_executor.py` | 工作流状态机、重试、质量门和产物记录 |
| `backend/tests/api/test_workflow_routes.py` | 创建、所有权、幂等、进度和 HTTP 边界 |
| `backend/tests/api/test_agent_routes.py` | 独立 Agent runtime、画像投影与证据输入 |
| `frontend/src/tests/rebuilding.spec.ts` | `/desk` Agent 面板与工作区联动 |
| `frontend/src/tests/core-behavior.spec.ts` | 认证、路由和基础客户端行为 |

### Reference Patterns

| File | Pattern |
|---|---|
| `backend/finance_god/api/agent_routes.py` | runtime 不可用/执行失败时显式错误，不生成默认答案 |
| `backend/finance_god/application/evidence_service.py` | AgentRun → 事实/推断/未知项/来源的只读投影 |
| `backend/finance_god/api/evidence_routes.py` | 用户所有权约束下的 evidence 查询 |
| `frontend/src/components/desk/OverviewWorkspace.vue` | 规则线、状态元数据、错误与刷新入口 |
| `frontend/src/composables/useDeskLayoutPreference.ts` | 浏览器持久化和显式重置 |

### Risk Assessment

- [x] Breaking changes to public API：移除未经 Worker 身份隔离的 `POST /workflows/claim`；交易台改用 `POST /workflows/desk`。
- [ ] Database migrations needed：复用现有 WorkflowRun、execution audit 和 evidence bundle。
- [x] Configuration changes required：Worker 只有在真实模型 runtime 可配置时才能完成 Agent 节点；失败会进入显式终态。
- [x] 真实模型调用存在延迟和费用；前端必须保留 running 状态、暂停隐藏页轮询并防止重复提交。
- [x] 现有工作树包含用户未提交改动；实施只做定向增量，不清理或回退无关文件。

## Review Decision

这是结构性修复。核心不变量为：

1. `completed` 必须有真实 AgentRun 衍生的可读 evidence bundle；
2. 未接入的确定性服务必须失败，不得生成“有效引用”伪装成功；
3. 工作流分类、所有权、领取与终态只由服务端决定；
4. 浏览器只显示服务端 Run、progress 和 evidence，不计算百分比、不生成研究结论；
5. 活动任务在同一 Agent 面板中可恢复、可刷新，不被下一次点击静默覆盖。
6. `queued → running` 的 CAS 是领取边界；模型调用期间不得持有数据库事务，每个状态与节点 revision 必须及时提交并对读取者可见。
