## Context Map

### Files to Modify
| File | Purpose | Changes Needed |
|------|---------|----------------|
| `backend/finance_god/api/desk_routes.py` | 交易台安全语义动作目录与参数校验 | 增加 `add_to_watchlist`，仅接受规范标的代码 |
| `backend/finance_god/api/agent_routes.py` | Agent 显式操作识别与动作提议校验 | 识别“加入自选”等明确意图 |
| `backend/finance_god/orchestration/multi_agent.py` | Agent 结构化动作提示 | 声明加入自选参数与边界 |
| `backend/finance_god/application/candidate_service.py` | 可研究候选唯一业务实现 | 只返回具备真实 PandaData 快照的候选；全量缺失时显式不可用 |
| `frontend/src/stores/tradingDesk.ts` | 已批准语义动作的客户端执行器 | 将标的加入当前/首个自选分组并刷新真实状态 |
| `docs/page-design/02_前后端职责与数据合同.md` | 动作与候选数据合同 | 固化 AI 添加自选和真实候选不变量 |
| `docs/page-design/pages/交易台.md` | `/desk` 页面规范 | 更新自选与候选验收条件 |

### Dependencies (may need updates)
| File | Relationship |
|------|--------------|
| `backend/finance_god/api/agent_routes.py` | 导入 `SAFE_UI_ACTIONS` 与 `validate_action_parameters` |
| `backend/finance_god/application/workflow_worker.py` | 复用 `CandidateScoringService` 输出生成 Evidence |
| `backend/finance_god/api/workspace_routes.py` | `/workspace/candidates` 复用候选服务 |
| `frontend/src/services/tradingDesk.ts` | 提供正式 UI action 与自选写入 API |
| `frontend/src/views/TradingDeskView.vue` | 将 store 自选状态投影到页面 |

### Test Files
| Test | Coverage |
|------|----------|
| `backend/tests/api/test_desk_bootstrap.py` | 动作目录与参数策略 |
| `backend/tests/api/test_agent_routes.py` | Agent 明确意图产生安全动作 |
| `backend/tests/api/test_candidate_routes.py` | 真实行情、部分失败与全量失败候选 |
| `backend/tests/workflows/test_workflow_worker.py` | 候选工作流 Evidence |
| `frontend/src/tests/rebuilding.spec.ts` | 已批准动作写入自选与前端状态 |

### Reference Patterns
| File | Pattern |
|------|---------|
| `backend/finance_god/api/desk_routes.py` | `select_symbol` / `fill_trade_draft` 的目录与参数白名单 |
| `frontend/src/stores/tradingDesk.ts` | `applyUiAction()` 仅在正式 `applied` 回执后执行副作用 |
| `backend/finance_god/application/candidate_service.py` | `MARKET_DATA_UNAVAILABLE` 显式失败与 PandaData 来源字段 |

### Risk Assessment
- [x] Breaking changes to public API：候选数组不再包含缺少真实行情的占位标的
- [ ] Database migrations needed
- [ ] Configuration changes required
- [x] 写操作风险：AI 仅可加入自选，不可删除分组、移除标的或提交订单
