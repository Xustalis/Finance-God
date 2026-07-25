# 前端 API 演示故障 Context Map

## Context Map

### Files to Modify

| File | Purpose | Changes Needed |
|---|---|---|
| `frontend/src/services/apiBase.ts` | 两类 API 根路径的唯一解析入口 | 新建 onboarding `/api/v1` 与交易域 `/api` 的独立解析，禁止一个环境变量同时改写两类路径 |
| `frontend/src/api/client.ts` | 认证、访谈、画像、管理 API 客户端 | 使用 v1 API 根路径 |
| `frontend/src/services/tradingDesk.ts` | 交易台 REST 与流式 Agent 客户端 | 使用 finance API 根路径；保持裸 JSON 与包络端点的显式分流 |
| `frontend/src/services/notificationStream.ts` | 交易台提醒 SSE | 从错误的默认 `/api/v1/events` 改为 finance `/api/events` |
| `frontend/src/composables/useRealtimeVoice.ts` | v1 实时语音 WebSocket | 使用 v1 API 根路径，不受交易域地址影响 |
| `frontend/src/stores/tradingDesk.ts` | API 调度、轮询与页面状态 | 历史演示中不请求现实资讯、融资事实和现实研究候选；清除对应真实错误状态 |
| `frontend/src/components/desk/OverviewWorkspace.vue` | 总览事实区呈现 | 将历史演示的预期不可用与真实刷新错误分开呈现 |
| `frontend/src/views/TradingDeskView.vue` | 交易台装配 | 传递历史演示 notice，不再把预期边界塞入 error |

### Dependencies (may need updates)

| File | Relationship |
|---|---|
| `frontend/vite.config.ts` | `/api` 同源代理同时承载 `/api/v1` 与 finance `/api` |
| `backend/app/main.py` | 实际挂载：FastAPI v1 在 `/api/v1`，finance Starlette 在 `/api` |
| `backend/server.py` | finance `/events`、`/market`、`/desk`、`/simulation`、`/workspace` 路由来源 |
| `backend/app/api/v1/voice.py` | v1 `/voice/realtime` WebSocket 来源 |
| `frontend/src/views/TradingDeskView.vue` | 消费 store 状态并装配工作区 |

### Test Files

| Test | Coverage |
|---|---|
| `frontend/src/tests/core-behavior.spec.ts` | API 客户端、配置与错误包络 |
| `frontend/src/tests/notification-stream.spec.ts` | SSE URL、游标与错误 |
| `frontend/src/tests/realtime-voice.spec.ts` | v1 WebSocket URL |
| `frontend/src/tests/rebuilding.spec.ts` | 交易台工作区、历史演示状态与请求调度 |
| `frontend/src/tests/views.spec.ts` | 页面错误和空态 |

### Reference Patterns

| File | Pattern |
|---|---|
| `frontend/src/api/client.ts` | v1 包络统一解包 |
| `frontend/src/services/tradingDesk.ts` | finance 裸 JSON `request` 与包络 `envelopedRequest` 明确区分 |
| `frontend/src/components/desk/WatchlistWorkspace.vue` | `candidateNotice` 与 `candidateError` 分离 |

### Risk Assessment

- [x] Breaking changes to public API：不改服务端公开 API；前端环境变量解析改为双根路径并保留旧变量的 v1 语义
- [ ] Database migrations needed
- [x] Configuration changes required：新增可选 `VITE_FINANCE_API_BASE_URL`，默认同源 `/api`

## 审阅结论

这是结构性问题，不是单个文案热修。根因有两类：

1. `VITE_API_BASE_URL` 同时被 v1 API 和 finance API 使用，而两者实际挂载分别为
   `/api/v1` 与 `/api`；提醒 SSE 默认值已经因此请求了不存在的 `/api/v1/events`。
2. 历史演示仍发起现实资讯、融资事实和现实候选请求，并把预期的信息隔离作为
   `error` 传给组件，导致页面出现成组“刷新失败/读取失败”。

采用统一根路径解析 + 状态语义分离的根因修复；不增加静默 fallback，也不伪造数据。
