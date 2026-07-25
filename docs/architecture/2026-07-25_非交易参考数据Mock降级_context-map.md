# 非交易参考数据 Mock 降级 Context Map

## Context Map

### Files to Modify

| File | Purpose | Changes Needed |
|---|---|---|
| `AGENTS.md` | 项目级工程约束 | 将“任何失败均禁 mock”细化为交易关键数据禁用、非交易参考模块显式降级 |
| `docs/page-design/01_前端统一设计规范.md` | 前端展示规范 | 定义 mock 披露、模块隔离和恢复行为 |
| `docs/page-design/02_前后端职责与数据合同.md` | 数据合同规范 | 定义触发条件、模式元数据、禁止流向和事实源边界 |
| `docs/page-design/pages/交易台.md` | `/desk` 页面规范 | 明确总览资讯/情绪可降级，行情不可降级 |
| `docs/page-design/templates/前端设计验收模板.md` | 通用验收门槛 | 增加 mock 边界与披露验收项 |

### Dependencies (may need updates)

| File | Relationship |
|---|---|
| `frontend/src/components/desk/OverviewWorkspace.vue` | 将来落地时消费 `data_mode` 并渲染披露 |
| `frontend/src/stores/tradingDesk.ts` | 将来落地时维护 real/mock/error 独立状态 |
| `frontend/src/services/tradingDesk.ts` | 将来落地时声明降级响应类型 |
| `backend/finance_god/api/desk_routes.py` | 将来落地时提供显式数据模式和失败原因 |

### Test Files

| Test | Coverage |
|---|---|
| `frontend/src/tests/views.spec.ts` | 总览真实、错误和降级展示 |
| `frontend/src/tests/market-quote.spec.ts` | 行情失败不得使用 mock |
| `backend/tests/market_data/test_server_api.py` | 数据模式、来源和交易资格合同 |

### Reference Patterns

| File | Pattern |
|---|---|
| `frontend/src/components/desk/ReviewWorkspace.vue` | 现有显式演示数据披露与真实数据优先模式 |
| `frontend/src/tests/review-workspace.spec.ts` | mock 启用条件、披露和真实数据优先测试 |

### Risk Assessment

- [ ] Breaking changes to public API
- [ ] Database migrations needed
- [x] Configuration changes required when implementation enables `mock_fallback`

本次只补充规范，没有修改运行时 API 或前端实现。后续实现必须先确定允许降级的端点清单，
不得用一个全局开关把 mock 扩散到交易关键链路。
