## Context Map

### Files to Modify
| File | Purpose | Changes Needed |
|------|---------|----------------|
| `frontend/src/components/desk/OverviewWorkspace.vue` | `/desk` 总览事实展示 | 将 PandaData 原始事实转换为可读展示：排除结构字段、优先非空披露指标、格式化融资金额 |
| `frontend/src/tests/overview-facts.spec.ts` | 总览事实呈现回归 | 覆盖融资字段、空财报字段与有效财报字段 |
| `docs/page-design/briefs/2026-07-25_PandaData事实展示修复设计简报.md` | 实施前设计简报 | 记录数据边界、失败态与受影响路由 |
| `docs/page-design/acceptance/2026-07-25_PandaData事实展示修复验收.md` | 实施后验收 | 按统一模板记录验证证据 |

### Dependencies (may need updates)
| File | Relationship |
|------|--------------|
| `frontend/src/services/tradingDesk.ts` | 定义 `DeskFactBatch` 原始事实合同；本次保持不变 |
| `frontend/src/stores/tradingDesk.ts` | 加载并按标的隔离两类事实；本次保持不变 |
| `backend/finance_god/market_data/adapter.py` | 规范化 PandaData 原始事实与来源证据；本次保持不变 |
| `backend/finance_god/market_data/service.py` | 暴露只读事实批次；本次保持不变 |
| `docs/page-design/pages/交易台.md` | `/desk` 页面规范，已经要求融资原始观察值与财报原始事实 |

### Test Files
| Test | Coverage |
|------|----------|
| `frontend/src/tests/overview-facts.spec.ts` | 新增事实字段筛选、标签与格式化回归 |
| `frontend/src/tests/rebuilding.spec.ts` | 已覆盖跨标的隔离、错误可见与 mock 披露 |
| `backend/tests/market_data/test_service.py` | 已覆盖公司披露与融资余额原始合同 |

### Reference Patterns
| File | Pattern |
|------|---------|
| `frontend/src/components/desk/OverviewWorkspace.vue` | 现有 `field`、`time` 展示适配函数 |
| `frontend/src/components/desk/MarketChart.vue` | 行情元数据在展示层格式化、服务端事实保持不变 |

### Risk Assessment
- [ ] Breaking changes to public API
- [ ] Database migrations needed
- [ ] Configuration changes required
- [x] 仅改变 `/desk` 原始事实的可视化选择与格式化，不改变事实值、来源或失败状态
