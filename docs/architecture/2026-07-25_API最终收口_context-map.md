# API 最终收口 Context Map

## Context Map

### Files to Modify

| File | Purpose | Changes Needed |
|---|---|---|
| `backend/finance_god/api/workspace_routes.py` | 自选、候选与提醒写接口 | 为前端已经发送幂等键的 7 个 workspace 命令接入同一持久化执行边界 |
| `backend/finance_god/api/simulation.py` | 模拟账户、草稿、成交写接口 | 核对所有命令的幂等读取、重放响应与修订门禁 |
| `backend/finance_god/api/desk_routes.py` | UI action 与 Agent 交易台命令 | 收口命令头、错误包络与上下文修订校验 |
| `backend/finance_god/api/workflow_routes.py` | 工作流创建、取消、重试 | 统一幂等键和稳定错误合同 |
| `backend/finance_god/infrastructure/persistence/models.py` | 共享 `idempotency_records` 模型 | 在现有唯一事实源上增加可重放 JSON 响应，不新建第二套收据表 |
| `backend/finance_god/infrastructure/persistence/repositories.py` | 共享幂等仓储 | 读写请求哈希、结果引用和完整响应 |
| `backend/finance_god/infrastructure/persistence/workspace_uow.py` | workspace 事务边界 | 注入共享幂等仓储和 owner 事务锁 |
| `backend/finance_god/infrastructure/persistence/simulation_uow.py` | 模拟执行事务边界 | 让复核、确认、撮合、取消与命令收据同事务 |
| `backend/finance_god/infrastructure/persistence/trade_plan_uow.py` | 计划事务边界 | 原子保存计划版本与收据，并串行化草稿恢复 |
| `backend/finance_god/infrastructure/persistence/workflow_uow.py` | 工作流事务边界 | 原子保存取消状态与命令收据 |
| `backend/finance_god/infrastructure/persistence/locks.py` | 聚合事务锁 | 从 simulation UOW 提取并复用 owner/account 锁，避免重复并发逻辑 |
| `backend/alembic/versions/20260725_0023_idempotency_response.py` | 数据库迁移 | 为 `idempotency_records` 增加可空 JSON 响应列，兼容现有账本收据 |
| `frontend/src/services/tradingDesk.ts` | Finance API 与流式客户端 | 仅在服务端合同存在时发送幂等键；统一裸 JSON/包络解析；修正流式终止与超时生命周期 |
| `frontend/src/api/client.ts` | `/api/v1` 包络客户端 | 保持唯一包络解包与稳定验证错误展示 |
| `deploy/deploy-now.sh`、`.github/workflows/deploy.yml` | Fast Deploy | 保持用户指定的快速发布，不恢复全量 CI；只保留发布必需健康检查 |

### Dependencies (may need updates)

| File | Relationship |
|---|---|
| `backend/server.py` | 挂载 Finance API 路由并注入服务/仓储 |
| `backend/app/main.py` | `/api/v1` 挂载、CORS 与统一异常处理 |
| `backend/finance_god/infrastructure/persistence/workspace_repository.py` | workspace 业务写入，必须和命令收据处于同一事务 |
| `backend/finance_god/infrastructure/persistence/uow.py` | simulation UOW 当前定义 owner/account 锁，提取后保持调用合同 |
| `backend/finance_god/application/ports.py` | 账本幂等仓储协议，需要兼容可空响应字段 |
| `backend/finance_god/application/idempotency.py` | 共享规范请求哈希和稳定服务端幂等键 |
| `backend/finance_god/application/trade_plan_service.py` | 计划修订/确认/草稿生成 | 先重放收据再做 revision 校验；稳定草稿键恢复半完成状态 |
| `backend/finance_god/execution/service.py` | 模拟草稿与订单状态机 | 将复核、软风险确认、确认、撮合、取消和响应收据原子提交 |
| `backend/finance_god/infrastructure/simulation_wiring.py` | 模拟写命令处理器与持久化装配 |
| `frontend/src/stores/tradingDesk.ts` | 所有交易台写命令、请求取消与状态回写 |
| `frontend/src/services/notificationStream.ts` | SSE 鉴权、重连与 AbortSignal 参考实现 |

### Test Files

| Test | Coverage |
|---|---|
| `backend/tests/workspace/` | 自选、候选与交易计划写入/修订/幂等 |
| `backend/tests/api/test_simulation_*.py` | 模拟账户、草稿、成交与时钟 HTTP 合同 |
| `backend/tests/api/test_workflow_routes.py` | 工作流命令与错误包络 |
| `backend/tests/api/test_notification_routes.py` | 提醒已读 |
| `frontend/src/tests/core-behavior.spec.ts` | v1 包络、Agent 流与超时 |
| `frontend/src/tests/rebuilding.spec.ts` | 交易台读写链路与错误状态 |
| `deploy/verify-public-api.py` | 生产只读行情、能力边界与资讯合同（保留为手动核验工具） |

### Reference Patterns

| File | Pattern |
|---|---|
| `backend/finance_god/application/ledger_service.py` | 现有 `scope + owner + key + request_hash` 重放不变量 |
| `backend/finance_god/infrastructure/persistence/workflow_repository.py` | 唯一键并发获胜后重新读取并重放的参考 |
| `backend/finance_god/api/simulation.py` | `Idempotency-Key` 校验与规范请求哈希参考 |
| `frontend/src/api/client.ts` | `/api/v1` 统一 `ApiEnvelope<T>` 解包 |
| `frontend/src/services/notificationStream.ts` | 正确覆盖整个流生命周期的 AbortSignal |
| `backend/finance_god/crawler/service.py` | 显式 fresh/stale/error 边界，不把失败伪装为空成功 |

### Risk Assessment

- [x] Breaking changes to public API：若统一错误/成功包络，必须同步所有前端消费者，不能双格式长期并存
- [x] Database migrations needed：仅当现有幂等记录无法覆盖 workspace 命令时；优先复用现有表
- [x] Configuration changes required：HTTPS/实时语音仍依赖可用域名与证书，不能以代码 mock 代替

## 审阅结论

这是结构性收口，不应继续为单个按钮添加局部 fallback。审阅确认现有
`idempotency_records` 已是账本唯一事实源；新增独立 `command_receipts` 会造成重复逻辑，
因此扩展现有记录为“结果引用 + 可空 JSON 响应”，旧账本调用保持兼容。workspace 命令在
同一事务内取得 owner 锁、核对请求哈希、完成业务写入并保存响应；重复同 payload 返回
原响应，同 key 异 payload 明确 409。

当前前端生产调用已集中在
`api/index.ts`、`tradingDesk.ts` 与 `notificationStream.ts`；剩余风险主要是服务端写命令
没有统一消费客户端幂等键，以及流式/包络边界多源。本次收口覆盖 workspace 七个命令、
simulation 六个状态命令、trade-plan revise/confirm-generate 和 workflow cancel；计划草稿
键由服务端业务身份派生，不再拼接可能超过数据库长度的客户端 key。行情、估值、交易、
Agent 证据继续禁止 mock。
