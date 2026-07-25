# Agent 可研究候选接入 Context Map

## Context Map

### Files to Modify

| File | Purpose | Changes Needed |
|---|---|---|
| `backend/finance_god/agents/contracts.py` | 正式工作流键 | 增加可研究候选工作流键 |
| `backend/finance_god/agents/catalog.py` | Agent 治理矩阵 | 将新工作流纳入完整矩阵；仅 Planner 必选 |
| `backend/finance_god/orchestration/workflow_registry.py` | 版本化工作流注册表 | 注册画像候选评分与最终 Evidence 产物节点 |
| `backend/finance_god/api/workflow_routes.py` | 交易台服务端意图路由 | 将“推荐股票/可研究候选”等意图路由到新工作流 |
| `backend/finance_god/application/candidate_service.py` | 候选评分唯一业务实现 | 接收画像方向与版本，生成可审计候选 Evidence 内容 |
| `backend/finance_god/application/workflow_worker.py` | Worker 节点执行 | 接入候选评分服务并持久化确定性最终产物 |
| `backend/finance_god/application/evidence_service.py` | Evidence 持久化 | 支持记录确定性候选产物，不伪装成 AgentRun |
| `backend/server.py` | API 进程生产装配 | 向 Worker 注入画像、候选评分与 Evidence 记录端口 |
| `backend/scripts/run_workflow_worker.py` | 独立 Worker 装配 | 与 API 进程使用同一候选服务和画像投影 |
| `frontend/src/stores/tradingDesk.ts` | 交易台共享状态 | 候选工作流完成后刷新现有候选区 |
| `docs/page-design/02_前后端职责与数据合同.md` | 前后端合同 | 记录候选工作流、画像门禁和 Evidence 合同 |
| `docs/page-design/pages/交易台.md` | `/desk` 页面规范 | 记录完成后的候选区刷新行为 |

### Dependencies (may need updates)

| File | Relationship |
|---|---|
| `backend/finance_god/orchestration/task_plans.py` | 从注册表生成并校验正式 TaskPlan，无需新增并行实现 |
| `backend/finance_god/api/workspace_routes.py` | 继续复用同一个 `CandidateScoringService`，候选列表仍是唯一展示合同 |
| `frontend/src/components/desk/DeskAgentPanel.vue` | 已能渲染通用事实、推断、未知项和来源，无需新增候选专用组件 |
| `frontend/src/components/desk/WatchlistWorkspace.vue` | 已能展示候选五维解释、反方证据和未知项 |

### Test Files

| Test | Coverage |
|---|---|
| `backend/tests/api/test_workflow_routes.py` | 中文推荐意图由服务端选择新工作流 |
| `backend/tests/api/test_candidate_routes.py` | 画像方向筛选、画像版本和无支持方向 |
| `backend/tests/workflows/test_registry_and_plans.py` | 新工作流注册表、节点与治理边界 |
| `backend/tests/workflows/test_workflow_worker.py` | 候选服务执行、确定性 Evidence、失败显式化 |
| `frontend/src/tests/rebuilding.spec.ts` | 工作流完成后刷新候选列表并展示 Evidence |

### Reference Patterns

| File | Pattern |
|---|---|
| `backend/finance_god/application/trade_plan_service.py` | 通过协议注入候选读取端口 |
| `backend/finance_god/application/evidence_service.py` | 不可变 Evidence bundle 与分层读取 |
| `backend/finance_god/application/workflow_worker.py` | 短事务节点执行和显式未接服务失败 |
| `frontend/src/stores/tradingDesk.ts` | 终态后按 `final_artifact` 读取 Evidence |

### Risk Assessment

- [x] Breaking changes to public API：新增 `research_candidates` 工作流键；现有候选响应只增加可选语义字段，不删除字段。
- [ ] Database migrations needed
- [ ] Configuration changes required
- [x] Shared routing/contract change：必须由服务端单点识别候选意图。
- [x] Data-integrity boundary：画像不可用、教育模式或行情缺失必须显式呈现，不得回退为虚构推荐。

## 结论

这是结构性修复，不是把“推荐股票”关键词改到现有公司研究的局部热修。应新增一个正式、只读、确定性的候选工作流，并复用现有 `CandidateScoringService`；候选不会生成订单，也不输出买入评级或综合分。
