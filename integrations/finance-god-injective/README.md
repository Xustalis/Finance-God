# Finance-God Injective Bridge

Finance-God 的独立 Injective Testnet 交易桥接子项目，基于
[`InjectiveLabs/sdk-python`](https://github.com/InjectiveLabs/sdk-python)
与精确锁定的 `injective-py==1.13.1` 实现。

它不修改 Finance-God 前端、后端、数据库或业务状态。两者之间唯一允许的连接，是用户主动调用快照接口后，Bridge 使用预先配置的只读令牌请求一次 Finance-God HTTP API；导入的数据永久标记为 `context_only`，不能授权或自动生成链上订单。

完整接口合同与请求示例见 [docs/API.md](docs/API.md)。

## 当前能力

- 网络固定为 Injective Testnet，Mainnet 配置会拒绝启动。
- 动态解析一个 `INJ/USDT` 现货市场及其价格、数量步长。
- 支持 GTC 现货限价买入、卖出和撤单。
- 读取订单簿、子账户余额、当前订单并持续对账链上状态。
- 独立交易计划、风险复核、显式确认、后台串行签名和广播。
- PostgreSQL 持久化计划、订单、事件、广播尝试和幂等结果。
- 可选导入 Finance-God 交易计划的白名单审计快照。

不支持主网、市价单、永续、杠杆、资金划转、自动改单，也不会把 Finance-God 的 A 股计划映射成链上订单。

## 目录与运行隔离

本项目位于主仓库的 `integrations/finance-god-injective/`，但运行时保持独立：

- Compose project：`finance-god-injective`
- Bridge API：容器内 `8080`，宿主机仅监听 `127.0.0.1:18081`
- PostgreSQL：数据库 `finance_god_injective`，用户 `injective_bridge`
- 数据卷：`finance_god_injective_postgres_data`
- 网络：`finance_god_injective_internal`
- 调试数据库端口：仅通过 override 映射 `127.0.0.1:15433`

Bridge 不加入 Finance-God 的 Compose 网络，不挂载 Finance-God 目录，不读取主项目 `.env`，也不连接主项目数据库。`/ready` 和启动过程均不访问 Finance-God。

## 执行流程

```text
创建计划 draft
  → 读取市场、订单簿与余额并复核 reviewed
  → 携带 expected_revision 显式确认 confirmed
  → Worker 串行签名与广播 submitted
  → 根据 Indexer/链上结果对账 open / partially_filled / filled / cancelled
```

获得交易 `tx_hash` 只代表广播已返回，不代表订单已被交易所接受。Bridge 会继续查询订单并保存 `order_hash` 与真实链上状态。

默认风险限制：

- 单笔最大名义金额：`25 USDT`
- 相对订单簿中间价最大偏离：`100 bps`
- 计划有效期：`300 秒`
- 同一钱包最多一个活动订单
- 仅允许配置市场、`buy | sell`、GTC limit

## 快速启动

要求：Docker、Compose，以及一个专用的 Injective Testnet 钱包。没有私钥时，市场读取与健康检查仍可使用，但确认下单会明确失败。

```bash
cd integrations/finance-god-injective
cp .env.example .env
```

编辑 `.env`，至少替换：

```dotenv
BRIDGE_ADMIN_TOKEN=<足够长的随机管理令牌>
INJECTIVE_DB_PASSWORD=<独立数据库密码>

# 只有执行 Testnet 订单时才配置；不得提交到 Git。
INJECTIVE_PRIVATE_KEY_HEX=<专用测试钱包私钥>
```

启动：

```bash
docker compose up --build
curl http://127.0.0.1:18081/live
curl http://127.0.0.1:18081/ready
```

数据库默认不暴露给宿主机。仅在本地调试数据库时使用：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.debug.yml \
  up --build
```

停止并删除 Bridge 容器与网络：

```bash
docker compose down
```

如需同时删除 Bridge 自己的 PostgreSQL 数据卷，必须显式执行 `docker compose down -v`；该命令不会访问 Finance-God 的卷。

## 主要配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BRIDGE_ADMIN_TOKEN` | 开发占位值 | 写接口 Bearer Token，部署前必须替换 |
| `BRIDGE_NETWORK` | `testnet` | 只接受 `testnet` |
| `BRIDGE_MARKET_TICKER` | `INJ/USDT` | v1 只接受该市场 |
| `BRIDGE_MAX_NOTIONAL` | `25` | 单笔最大 USDT 名义金额 |
| `BRIDGE_MAX_PRICE_DEVIATION_BPS` | `100` | 相对中间价最大偏离 |
| `BRIDGE_PLAN_TTL_SECONDS` | `300` | 计划有效期 |
| `BRIDGE_MAX_ACTIVE_ORDERS` | `1` | 同一钱包活动订单上限 |
| `INJECTIVE_PRIVATE_KEY_HEX` | 空 | 专用 Testnet 私钥，仅从 Secret/环境变量读取 |
| `INJECTIVE_SUBACCOUNT_INDEX` | `0` | Injective 子账户索引 |
| `FINANCE_GOD_SYNC_ENABLED` | `false` | 是否允许显式导入只读快照 |
| `FINANCE_GOD_BASE_URL` | `http://host.docker.internal:8000` | Finance-God HTTP 地址 |
| `FINANCE_GOD_READ_TOKEN` | 空 | 现有登录流程签发的只读 Bearer Token |

完整配置模板见 [.env.example](.env.example)。私钥、令牌和 `.env` 不进入数据库、日志、API 响应或 Git。

## API 使用顺序

所有写接口必须同时携带：

```http
Authorization: Bearer <BRIDGE_ADMIN_TOKEN>
Idempotency-Key: <调用方生成的唯一键>
Content-Type: application/json
```

创建独立 Injective 计划：

```bash
curl -X POST http://127.0.0.1:18081/v1/plans \
  -H "Authorization: Bearer $BRIDGE_ADMIN_TOKEN" \
  -H "Idempotency-Key: plan-001" \
  -H "Content-Type: application/json" \
  -d '{"side":"buy","price":"12.34","quantity":"0.1"}'
```

风险复核并确认：

```bash
curl -X POST http://127.0.0.1:18081/v1/plans/PLAN_ID/review \
  -H "Authorization: Bearer $BRIDGE_ADMIN_TOKEN" \
  -H "Idempotency-Key: review-001"

curl -X POST http://127.0.0.1:18081/v1/plans/PLAN_ID/confirm \
  -H "Authorization: Bearer $BRIDGE_ADMIN_TOKEN" \
  -H "Idempotency-Key: confirm-001" \
  -H "Content-Type: application/json" \
  -d '{"expected_revision":2}'
```

所有价格、数量、金额和成交量均使用 JSON 字符串表示的十进制数，禁止传浮点数。完整路由、响应、错误码、撤单与 Finance-God 快照示例见 [API 文档](docs/API.md)。

## Finance-God 只读边界

只有在 `FINANCE_GOD_SYNC_ENABLED=true` 且用户显式调用快照接口时，Bridge 才可能请求：

- `GET /api/finance/trade-plans/{plan_id}`
- `GET /api/finance/simulation/drafts/{draft_id}`

Bridge 不登录、不刷新令牌、不轮询计划、不调用 `/api/desk/bootstrap`、不写回，也不保存 JWT、用户画像、自由文本证据或完整响应。

## 本地开发与验证

项目要求 Python 3.11：

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
ruff format --check .
```

验证数据库迁移：

```bash
alembic upgrade head
```

验证 Compose 隔离配置：

```bash
./scripts/verify_isolation.sh
```

真实 Testnet 下单必须使用独立测试钱包与测试资金。未配置私钥或余额不足时，Bridge 不会伪造成功结果。
