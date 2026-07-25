# Bridge API（v1）

Base URL：`http://127.0.0.1:18081`。Bridge 只面向 Injective Testnet，首版只执行动态解析到的 `INJ/USDT` 现货市场的 GTC 限价单；不支持主网、市价单、永续、杠杆、资金划转或自动改单。

## 鉴权与幂等

所有 **写接口** 都必须带：

```http
Authorization: Bearer <BRIDGE_ADMIN_TOKEN>
Idempotency-Key: <1-160 个字符的调用方唯一键>
Content-Type: application/json
```

`/live`、`/ready` 与两个读取接口不要求管理员令牌。令牌错误返回 `401`。同一操作以相同 `Idempotency-Key` 和相同请求体重试，会返回第一次保存的结果；相同键配不同请求体返回 `409 IDEMPOTENCY_CONFLICT`。请求仍在处理中时返回 `409 IDEMPOTENCY_IN_PROGRESS`。

金额、价格、数量及成交量全部是 **十进制字符串**，例如 `"12.34"`、`"0.1"`。客户端不得传 JSON 浮点数，也不应依赖浮点计算；服务端使用 `Decimal`。所有值必须是有限正数（成交量可为 `"0"`）。

## 健康检查

### `GET /live`

只表示进程仍可响应：

```json
{"status":"live"}
```

### `GET /ready`

检查独立数据库/配置及 Testnet 市场解析，不访问 Finance-God。成功：

```json
{"status":"ready"}
```

不可就绪时返回 `503`，例如：

```json
{"detail":{"error":{"code":"NOT_READY","message":"..."}}}
```

## Finance-God 上下文快照

### `POST /v1/source-snapshots/finance-god`

这是唯一会访问 Finance-God 的接口；需管理员令牌与幂等键。

请求：

```json
{"plan_id":"plan-..."}
```

响应（字段可能为 `null`）：

```json
{
  "id":"b8b0...",
  "source_plan_id":"plan-...",
  "source_plan_version":"3",
  "source_plan_status":"approved",
  "classification":"context_only",
  "asset_domain":"non_executable_asset_domain",
  "normalized_hash":"<sha256>",
  "created_at":"2026-07-25T00:00:00+00:00"
}
```

只有 `FINANCE_GOD_SYNC_ENABLED=true` 且已提供读令牌时才能调用。Bridge 仅使用该令牌发出一次用户指定计划的以下 GET：

- `GET /api/finance/trade-plans/{plan_id}`
- 当计划含草稿 ID 时，`GET /api/finance/simulation/drafts/{draft_id}`

Bridge 不登录、不刷新令牌、不轮询、不调用 bootstrap、不写回、也不连接 Finance-God 数据库。仅保留白名单投影、标准化 hash、版本/状态/过期信息和草稿确认状态；不保存 JWT、用户资料、自由文本或原始响应。快照永久标记为 `context_only`，只能作为审计关联，绝不能授权或映射为链上订单。

## 计划

### `POST /v1/plans`

创建独立 Injective 交易计划；需管理员令牌与幂等键。

```json
{
  "side":"buy",
  "price":"12.34",
  "quantity":"0.1",
  "source_snapshot_id":"b8b0..."
}
```

`source_snapshot_id` 可省略，存在时仅用于上下文审计。响应计划示例：

```json
{
  "id":"PLAN_ID",
  "market_id":"0x...",
  "ticker":"INJ/USDT",
  "side":"buy",
  "order_type":"limit",
  "time_in_force":"gtc",
  "price":"12.340000000000000000",
  "quantity":"0.100000000000000000",
  "status":"draft",
  "revision":1,
  "expires_at":"2026-07-25T00:05:00+00:00"
}
```

### `POST /v1/plans/{id}/review`

需管理员令牌与幂等键。读取当前市场元数据、订单簿和独立钱包余额，执行价格/数量步长、最大名义额（默认 25 USDT）、中间价偏离（默认 100 bps）、活跃订单数、余额、市场状态和有效期等确定性检查。通过则计划变为 `reviewed`，否则变为 `rejected`；响应为更新后的计划，`risk_report` 保存于计划记录中。

### `POST /v1/plans/{id}/confirm`

需管理员令牌与幂等键。请求：

```json
{"expected_revision":2}
```

版本必须等于审核后的当前版本，否则返回 `409 REVISION_CONFLICT`。确认成功立即返回状态为 `confirmed` 的计划，后台 Worker 随后串行签名和广播；调用方应轮询计划/订单读取接口观察最终执行结果，不可将确认响应视为成交或链上接受。

### `GET /v1/plans/{id}`

返回独立计划、当前 revision、风险报告、过期时间和提交状态。不存在返回 `404 NOT_FOUND`。

## 订单

### `GET /v1/orders/{id}`

返回订单的 `tx_hash`、`order_hash`、`status`、`quantity`、`filled_quantity` 和链上投影。拿到 `tx_hash` 仅表示广播阶段已返回，不等于交易已经被接受或订单已打开。

### `POST /v1/orders/{id}/cancel`

需管理员令牌与幂等键。仅可对尚可撤销、且已具备 `order_hash` 的订单调用。成功响应是更新后的订单：

```json
{"id":"ORDER_ID","status":"cancelled","tx_hash":"...","order_hash":"...","filled_quantity":"0.000000000000000000"}
```

已成交、被拒绝、未知或尚未得到 order hash 的订单会显式失败，绝不伪造撤单成功。

## 状态机

计划：

```text
draft → reviewed → confirmed → submitted
  └────→ rejected
draft/reviewed/confirmed → expired
confirmed → submission_failed
```

订单：

```text
broadcasting → broadcast → open → partially_filled → filled
                      └──────────────────────────→ cancelled
broadcasting/broadcast/open/partially_filled → rejected | unknown
unknown → broadcast | open | partially_filled | filled | cancelled | rejected
```

广播超时或结果不确定时，订单进入 `unknown`，必须先按交易/订单 hash 对账，未确认链上不存在前禁止再次广播。事件按至少一次投递处理，并按链上事件标识与 payload hash 去重。

## 错误格式

业务错误的主体为：

```json
{"detail":{"error":{"code":"REQUEST_FAILED","message":"具体原因"}}}
```

常见 HTTP 状态：`400 REQUEST_FAILED`（参数、状态、风险、适配器或余额失败）、`401 UNAUTHORIZED`、`404 NOT_FOUND`、`409 REVISION_CONFLICT`、`409 IDEMPOTENCY_CONFLICT`、`409 IDEMPOTENCY_IN_PROGRESS`、`503 NOT_READY`。FastAPI 的请求体校验错误可能使用标准 `422` 格式。错误均为显式失败；SDK、RPC 与 Finance-God 读取失败不产生模拟成功或静默降级。

## 完整 curl 流程

```bash
export BASE=http://127.0.0.1:18081
export AUTH="Authorization: Bearer $BRIDGE_ADMIN_TOKEN"

curl "$BASE/live"
curl "$BASE/ready"

# 可选：显式拉取一次只读上下文
curl -X POST "$BASE/v1/source-snapshots/finance-god" -H "$AUTH" \
  -H 'Idempotency-Key: snapshot-001' -H 'Content-Type: application/json' \
  -d '{"plan_id":"plan-..."}'

curl -X POST "$BASE/v1/plans" -H "$AUTH" \
  -H 'Idempotency-Key: plan-001' -H 'Content-Type: application/json' \
  -d '{"side":"buy","price":"12.34","quantity":"0.1"}'

curl -X POST "$BASE/v1/plans/PLAN_ID/review" -H "$AUTH" \
  -H 'Idempotency-Key: review-001'

curl -X POST "$BASE/v1/plans/PLAN_ID/confirm" -H "$AUTH" \
  -H 'Idempotency-Key: confirm-001' -H 'Content-Type: application/json' \
  -d '{"expected_revision":2}'

curl "$BASE/v1/plans/PLAN_ID"
curl "$BASE/v1/orders/ORDER_ID"

curl -X POST "$BASE/v1/orders/ORDER_ID/cancel" -H "$AUTH" \
  -H 'Idempotency-Key: cancel-001'
```
