# Agent 主控交易台用户旅程：Context Map

> 日期：2026-07-25
> 任务：审计现有后端，分析双栏 Agent 主控交易台用户旅程，给出可运行、可观测的分阶段规划，并在隔离目录交付简单前端原型。

## Files to Modify

| 文件 | 用途 | 本次变更 |
|---|---|---|
| `docs/architecture/2026-07-25_Agent主控交易台用户旅程与Phase规划.md` | 本次需求、用户旅程、后端差距和 Phase 计划 | 新增 |
| `docs/page-design/briefs/2026-07-25_Agent主控交易台用户旅程原型设计简报.md` | 原型实施前设计简报 | 新增 |
| `docs/page-design/acceptance/2026-07-25_Agent主控交易台用户旅程原型验收.md` | 原型逐项验收与证据 | 新增 |
| `frontend/prototypes/journey-desk/*` | 与生产路由隔离的 Vue 交互原型 | 新增 |

本次不修改 `frontend/src/*`、`backend/*` 和数据库迁移；这些目录只作为现状证据。

## Dependencies

| 文件 | 关系 |
|---|---|
| `docs/page-design/01_前端统一设计规范.md` | 原型视觉、双栏、导航、快捷指令和隐私边界的规范来源 |
| `docs/page-design/02_前后端职责与数据合同.md` | 行情、工作流、提醒和语义 UI 动作合同来源 |
| `docs/page-design/pages/交易台.md` | `/desk` 页面专属规范 |
| `backend/server.py` | 当前 API 组合、行情轮询启动、行情快照与全局告警端点 |
| `backend/finance_god/application/market_poller.py` | 当前服务端行情轮询流程 |
| `backend/finance_god/market_data/monitor.py` | 当前重大涨跌阈值检测 |
| `backend/finance_god/api/workflow_routes.py` | 当前工作流创建、查询与进度快照 |
| `backend/finance_god/api/agent_routes.py` | 当前一次性研究 Agent 运行模型 |
| `backend/finance_god/api/workspace_routes.py` | 当前自选、候选、未读通知与通知偏好 |
| `frontend/src/views/TradingDeskView.vue` | 生产双栏与提醒/我的入口参考 |
| `frontend/src/components/desk/DeskAgentPanel.vue` | 生产三条快捷指令与真实工作流回执参考 |

## Test Files

| 测试 | 覆盖 |
|---|---|
| `backend/tests/market_data/test_market_poller.py` | 行情快照落库、阈值跨越去重、上游失败循环 |
| `backend/tests/market_data/test_market_monitor.py` | 重大涨跌纯规则 |
| `backend/tests/market_data/test_market_monitor_routes.py` | 行情快照和全局告警读取 |
| `backend/tests/api/test_workflow_routes.py` | 工作流 HTTP 创建/读取/进度合同 |
| `backend/tests/workflow_persistence/*` | 工作流幂等、CAS、事件与持久化 |
| `frontend/src/tests/rebuilding.spec.ts` | 生产交易台布局、Agent、提醒、仿真交易交互 |
| `frontend/prototypes/journey-desk/src/model.spec.ts` | 本次原型的动态快捷指令、动作白名单和敏感操作拒绝 |

## Reference Patterns

| 文件 | 可复用模式 |
|---|---|
| `frontend/src/composables/useDeskLayoutPreference.ts` | Agent 展开/收起和浏览器偏好 |
| `frontend/src/stores/tradingDesk.ts` | 单一行情轮询控制器、页面隐藏暂停 |
| `frontend/src/services/tradingDesk.ts` | 类型化交易台 API 适配 |
| `frontend/prototypes/agent-workbench/*` | 隔离 Vite 原型的运行方式；视觉和信息架构不直接沿用 |

## Risk Assessment

- [x] 生产 API 尚未统一：FastAPI `/api/v1` 包络与挂载 Starlette 裸 JSON 并存。
- [x] 数据库后续需要结构变更：行情 observation/fetch run、用户告警投影、对话消息、UI 动作审计。
- [x] 配置需要扩展：交易日历、分层采集间隔、告警规则版本、Worker 租约和 SSE。
- [x] 当前行情轮询运行在 API 进程，横向扩容会重复执行。
- [x] 当前 `market_alerts` 是全局记录，尚未进入用户通知的读取/关闭/处理闭环。
- [x] 当前已有进程内/独立 Workflow Worker；仍缺公开取消、事件流和多 Worker 租约恢复。
- [x] 当前 Agent 一次性研究运行与 `WorkflowRun` 分离，画像读取和证据落库存在静默 best-effort。
- [ ] 本次原型不会改变生产 API、数据库或权限。

## Review Decision

这是结构性改造，不适合在现有组件上增加若干条件分支。规划应先统一四个不变量：行情事实唯一来源、正式任务唯一 `WorkflowRun`、提醒状态与显示状态分离、Agent 只执行版本化语义动作。隔离原型只验证用户旅程和交互合同，不伪造行情或后端工作流完成。

复核更新：同一工作区的后续代码已经增加 Desk Bootstrap、UI 动作回执、Workflow Worker 和通知历史。规划与原型缺口矩阵必须以这些代码和对应测试为准，不能继续把它们标成“未实现”。
