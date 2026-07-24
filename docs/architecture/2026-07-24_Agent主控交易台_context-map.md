# Agent 主控交易台分析与隔离原型 Context Map

> 任务：分析用户提出的 C/S、工作流、周期行情、重大行情提醒和双向 Agent 交易台需求；
> 在不修改生产前端与现有后端实现的前提下，交付完整 Phase 规划及隔离可运行原型。

## Context Map

### Files to Modify

本任务不修改现有生产代码。以下均为新增文件。

| File | Purpose | Changes Needed |
| --- | --- | --- |
| `docs/architecture/2026-07-24_Agent主控交易台规划.md` | 现状审计、需求修正、目标架构、合同和 Phase 规划 | 新增证据化规划文档 |
| `docs/page-design/briefs/2026-07-24_Agent主控交易台原型设计简报.md` | 实现前设计简报 | 新增原型范围、数据状态、动作边界和桌面布局 |
| `docs/page-design/acceptance/2026-07-24_Agent主控交易台原型验收.md` | 实现后逐项验收 | 新增通过/失败/不适用与复现证据 |
| `frontend/prototypes/agent-workbench/index.html` | 隔离原型入口 | 新增 Vite HTML 入口 |
| `frontend/prototypes/agent-workbench/package.json` | 原型运行命令 | 新增开发、构建、测试和类型检查命令 |
| `frontend/prototypes/agent-workbench/tsconfig.json` | 原型 TypeScript 配置 | 复用 Vue/Vite 类型能力 |
| `frontend/prototypes/agent-workbench/vite.config.ts` | 原型构建与 `/api` 代理 | 代理到现有后端，不保存凭据 |
| `frontend/prototypes/agent-workbench/src/main.ts` | Vue 启动入口 | 挂载隔离应用 |
| `frontend/prototypes/agent-workbench/src/App.vue` | 双区域交易台交互原型 | 左侧工作区、右侧 Agent、工作流状态、提醒记录与动作联动 |
| `frontend/prototypes/agent-workbench/src/styles.css` | 原型设计 Token 与桌面布局 | 暖米色报纸终端、无卡片墙、1024 px 边界 |
| `frontend/prototypes/agent-workbench/src/agentActions.ts` | Agent 可寻址 UI 动作合同 | 定义允许的导航、选择、表单填充动作；排除设置和交易提交 |
| `frontend/prototypes/agent-workbench/src/agentActions.spec.ts` | 动作合同单元测试 | 验证设置隔离、危险动作拒绝和自然语言路由 |
| `frontend/prototypes/agent-workbench/README.md` | 原型运行与边界说明 | 记录依赖、命令和非生产限制 |

### Dependencies (may need updates)

| File | Relationship |
| --- | --- |
| `frontend/package.json` | 提供 Vue 3、TypeScript、Vite、Vitest 与 Vue 插件；本任务不修改 |
| `frontend/src/styles.css` | 现有 Finance-God Token 与视觉语言的参考模式；不直接导入 |
| `frontend/src/components/desk/AiSidebar.vue` | 现有共享 AI 侧栏和证据呈现的参考实现 |
| `frontend/src/stores/aiContext.ts` | 现有 AI 上下文同步与折叠持久化参考 |
| `frontend/src/stores/market.ts` | 现有统一轮询、页面隐藏暂停和失败保留参考 |
| `frontend/src/api/desk.ts` | 现有 `/api/market/*`、工作区、通知和 Agent 请求合同参考 |
| `backend/finance_god/api/workspace_routes.py` | 已有自选、通知和通知偏好 API 证据 |
| `backend/finance_god/orchestration/` | 已有工作流注册表、执行器和持久化命令证据 |
| `backend/finance_god/market_data/` | PandaData 标准化、缓存、单飞与质量门证据 |
| `docs/page-design/01_前端统一设计规范.md` | 强制桌面布局、视觉、AI、行情和可访问性约束 |
| `docs/page-design/02_前后端职责与数据合同.md` | 强制 Page View、Command、错误和前后端职责边界 |
| `docs/page-design/pages/T03_AI辅助交易台.md` | 交易台页面专属任务和 AI/订单边界 |

### Test Files

| Test | Coverage |
| --- | --- |
| `frontend/prototypes/agent-workbench/src/agentActions.spec.ts` | Agent 可寻址动作、设置隔离、危险动作拒绝、上下文快捷指令 |
| `frontend/src/tests/ai-sidebar.spec.ts` | 现有共享 AI 侧栏上下文和折叠行为参考 |
| `frontend/src/tests/desktop-workspace.spec.ts` | 现有桌面宽度和工作区偏好参考 |
| `backend/tests/workflows/test_executor.py` | 工作流 DAG、状态、超时、重试和质量门 |
| `backend/tests/workflow_persistence/test_repository.py` | 工作流状态、事件、审计与 Outbox 持久化 |
| `backend/tests/market_data/test_coordinator.py` | 行情缓存、单飞、过期与失败状态 |
| `backend/tests/api/test_workspace_routes.py` | 自选、通知和通知偏好路由 |
| `backend/tests/api/test_agent_routes.py` | 当前工作区中尚未提交的 Agent API 变更；本任务不触碰 |

### Reference Patterns

| File | Pattern |
| --- | --- |
| `frontend/src/App.vue` | 认证桌面路由共享单例 AI 侧栏 |
| `frontend/src/components/desk/DeskLayout.vue` | 工作区面板显隐和本地偏好 |
| `frontend/src/components/desk/DecisionInbox.vue` | 订单异常与通知聚合、失败可见 |
| `frontend/src/stores/market.ts` | 共享轮询、隐藏暂停、恢复立即刷新、在途请求去重 |
| `backend/finance_god/orchestration/workflow_registry.py` | 15 条版本化工作流与节点权限白名单 |
| `backend/finance_god/infrastructure/persistence/workflow_models.py` | 运行、事件、审计、Outbox 的持久化模型 |
| `backend/finance_god/infrastructure/persistence/workspace_models.py` | 通知、已读回执和偏好模型 |

### Risk Assessment

- [ ] Breaking changes to public API
- [ ] Database migrations needed
- [ ] Configuration changes required
- [x] 原型会请求现有 `/api`，后端未运行或 PandaData 不可用时必须显示真实失败状态
- [x] 当前工作区已有未提交的 `backend/server.py`、`backend/finance_god/api/agent_routes.py`
  和 `backend/tests/api/test_agent_routes.py` 变更，必须保持不动

## Review Result

- 范围复核：通过。新增文件均位于文档目录和隔离原型目录。
- 架构复核：通过。原型不复制后端领域状态机，不创建第二行情事实源。
- 安全复核：通过。Agent 只可导航、刷新、选择、调整筛选和填充未提交表单；设置、最终复核、
  提交订单、撤单和账本写入不进入可寻址动作目录。
- 验证要求：必须完成原型单元测试、TypeScript 检查、Vite 构建和 1440/1024/900 px
  浏览器烟测后才能填写验收结论。
