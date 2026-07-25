# API 全链路落地 Context Map

## Context Map

### Files to Modify

| File | Purpose | Changes Needed |
|---|---|---|
| `backend/app/main.py` | FastAPI 总入口与 CORS | 放行浏览器实际发送的 `Idempotency-Key` |
| `backend/server.py` | Finance API 组合与市场 HTTP 合同 | 恢复 PandaData 事实端点；保持显式错误/部分成功；移除浏览器驱动的 K 线截断 |
| `backend/finance_god/infrastructure/simulation_wiring.py` | 历史模拟成交 bar 适配 | 保持模拟时钟为唯一边界并更新过期测试装配 |
| `backend/alembic/versions/20260725_0019_trade_review_loop.py` | 交易复盘迁移 | 使 SQLite 离线 SQL 渲染不依赖反射 |
| `backend/finance_god/market_data/capabilities.py` | PandaData 能力授权事实源 | 撤销没有审计产物支持的 `get_index_min` 能力提升 |
| `backend/finance_god/market_data/resources/*.json` | 脱敏能力审计产物 | 同步当前 instrument master 版本 |
| `frontend/src/services/tradingDesk.ts` | Finance REST/NDJSON 客户端 | 使用 v1 画像客户端；流式 done/超时门禁；移除重复 401；K 线不传 limit；事实参数对齐 |
| `frontend/src/stores/tradingDesk.ts` | K 线请求调度 | 移除前端范围参数 |
| `docker-compose.yml` | 本地容器 API 运行环境 | workflow DB 改用 async driver；挂载行情缓存 |
| `deploy/docker-compose.prod.yml` | 生产容器 API 运行环境 | workflow DB 改用 async driver；挂载行情缓存持久卷 |
| `backend/Dockerfile` | 生产后端镜像 | 创建 appuser 可写的 `/app/data` |
| `docs/page-design/briefs/2026-07-25_API全链路落地设计简报.md` | 前端实施前简报 | 记录数据源、失败态和受影响路由 |
| `docs/page-design/acceptance/2026-07-25_API全链路落地验收.md` | 前端验收 | 逐项记录测试与烟测证据 |

### Dependencies (may need updates)

| File | Relationship |
|---|---|
| `backend/finance_god/orchestration/workflow_runtime.py` | 从 `FINANCE_GOD_DATABASE_URL` 创建 async engine |
| `backend/finance_god/market_data/service.py` | PandaData disclosure / margin facts 的正式实现 |
| `frontend/src/api/index.ts` | v1 画像包络客户端 |
| `frontend/src/services/apiBase.ts` | v1 与 Finance 两类根路径的唯一解析 |
| `frontend/nginx.conf`、`frontend/vite.config.ts` | 同源 `/api` 生产代理与开发代理 |

### Test Files

| Test | Coverage |
|---|---|
| `backend/tests/integration/test_route_mounting.py` | `/api/v1`、`/api/finance`、`/api` 挂载 |
| `backend/tests/market_data/test_server_api.py` | 市场错误、行情与事实 HTTP 合同 |
| `backend/tests/execution/test_market_data_bar_provider.py` | 模拟时钟后的第一根真实 bar |
| `backend/tests/ledger/test_migration.py` | SQLite/Postgres 迁移与离线 SQL |
| `backend/tests/workflows/test_runtime.py` | workflow runtime 数据库配置 |
| `frontend/src/tests/api-base.spec.ts` | 双 API base |
| `frontend/src/tests/core-behavior.spec.ts` | Finance 客户端、画像与 Agent stream |
| `frontend/src/tests/rebuilding.spec.ts` | 交易台请求调度与失败态 |

### Reference Patterns

| File | Pattern |
|---|---|
| `backend/finance_god/market_data/service.py` | 事实源校验、标准化和来源证据 |
| `frontend/src/api/client.ts` | v1 包络解包与统一 401 |
| `frontend/src/services/notificationStream.ts` | fetch 的鉴权、AbortSignal 与稳定错误 |
| `deploy/docker-compose.prod.yml` | same-origin API 与具名持久卷 |

### Risk Assessment

- [x] Breaking changes to public API：恢复已经写入规范与测试的事实合同；爬虫继续保留在独立 `/crawler/*`
- [ ] Database migrations needed
- [x] Configuration changes required：workflow URL 必须使用 asyncpg；行情缓存增加持久卷

## 审阅结论

这是结构性修复。所有浏览器路径均有对应路由，404 不是主要根因；生产阻断来自错误
数据库驱动和未部署现行镜像，浏览器阻断来自 CORS/双 base/流式终止语义，市场事实
阻断来自同名端点被另一数据源覆盖。修复应保持 PandaData、画像 v1 与 Finance API
三个事实边界，不增加静默 fallback。mock 只保留规范允许的非交易只读参考模块，并
且必须显式标记、整模块切换、真实恢复后自动退出。
