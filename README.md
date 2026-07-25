# Finance-God

[![CI/CD](https://github.com/Xustalis/Finance-God/actions/workflows/deploy.yml/badge.svg)](https://github.com/Xustalis/Finance-God/actions/workflows/deploy.yml)

Finance-God 是一个中文优先的开源投资研究与交易训练工作台。它把投资目标采集、风险画像、行情观察、研究工作流、组合管理、下单训练和成交复盘放在同一套桌面工作区中。

本项目不连接真实券商，也不会执行真实证券交易。账户、持仓、订单、成交和执行流程均为仿真业务；行情由服务端接入 PandaData。项目内容不构成投资建议。

## 主要能力

- 账户注册、登录、投资目标采集与教育型风险画像
- 文本与语音辅助访谈、画像报告和投资方向选择
- PandaData 行情、K 线、市场状态与数据新鲜度展示
- 自选分组、组合持仓、交易计划、订单草稿和风险校验
- 单用户单活动工作流、任务队列与 Agent 上下文协作
- 仿真下单、成交记录、不可变决策上下文和交易复盘
- 管理端模型配置、审计信息与生产就绪检查

交易台入口为 `/desk`，并支持以下可直接访问的工作区：

- `/desk/portfolio`
- `/desk/watchlist`
- `/desk/trading`
- `/desk/review`

## 技术架构

| 层 | 技术与职责 |
| --- | --- |
| Web | Vue 3、TypeScript、Vite、Pinia、Vue Router、Lightweight Charts |
| API | FastAPI、Pydantic、SQLAlchemy 2 |
| 数据 | PostgreSQL 16、Alembic |
| 行情 | PandaData 服务端适配器、统一轮询与缓存 |
| AI | DeepSeek、StepFun、ARK 的服务端适配器 |
| 交付 | Docker Compose、Nginx、GitHub Actions |

浏览器通过同源 `/api` 访问后端。PandaData 与模型凭据只保存在服务端，前端构建不会接收这些密钥。应用由 `backend/app/main.py` 统一装配：认证与画像接口位于 `/api/v1/*`，行情、工作区和仿真交易接口位于 `/api/*`。

## 环境要求

- Python 3.12
- Node.js 20
- PostgreSQL 16，或支持 Docker Compose 的 Docker 环境

## 安装

```bash
git clone https://github.com/Xustalis/Finance-God.git
cd Finance-God
cp .env.example .env

cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e ".[dev]"

cd ../frontend
npm ci
cd ..
```

启动 PostgreSQL 并升级数据库：

```bash
docker compose up -d db
cd backend
.venv/bin/alembic upgrade head
cd ..
```

如需本地开发账户，在根 `.env` 中设置 `DEV_TEST_USER_PASSWORD` 和 `DEV_ADMIN_PASSWORD`，然后执行：

```bash
make seed-dev-accounts
```

## 配置

根目录 `.env` 是本地运行的配置入口，不要提交真实密钥。生产环境使用 `deploy/.env.production`。

| 变量 | 用途 |
| --- | --- |
| `APP_ENV` | 运行环境，生产必须设为 `production` |
| `DATABASE_URL` | 应用使用的异步 PostgreSQL 连接 |
| `DATABASE_URL_SYNC` | Alembic 使用的同步 PostgreSQL 连接 |
| `SECRET_KEY` | JWT 签名密钥，生产必须使用高强度随机值 |
| `CORS_ORIGINS` | 允许访问 API 的前端来源 |
| `PANDA_DATA_USERNAME` / `PANDA_DATA_PASSWORD` | PandaData 服务端凭据 |
| `DEEPSEEK_API_KEY` | DeepSeek 服务端凭据 |
| `STEPFUN_API_KEY` | StepFun 文本与实时语音服务端凭据 |
| `ARK_API_KEY` / `ARK_MODEL` | ARK 服务端凭据与模型标识 |
| `VITE_WORKBENCH_ORIGIN` | 画像完成后的浏览器交接目标 |

生产环境会校验数据库密码、JWT 密钥、行情凭据和所需模型配置。配置缺失时服务会明确报告未就绪，不会把不可用状态伪装为成功。

## 本地运行

分别启动后端和前端：

```bash
# 终端 1
make backend

# 终端 2
make frontend
```

默认地址：

- Web：`http://localhost:3000`
- API：`http://localhost:8000`
- OpenAPI：`http://localhost:8000/docs`
- 存活检查：`http://localhost:8000/health`
- 就绪检查：`http://localhost:8000/api/ready`

也可以通过容器运行完整开发环境：

```bash
docker compose up --build
```

## 测试与质量检查

后端：

```bash
cd backend
.venv/bin/ruff check app finance_god scripts tests
.venv/bin/python -m compileall -q app finance_god scripts
.venv/bin/pytest -q
.venv/bin/alembic upgrade head --sql >/tmp/finance-god-alembic.sql
```

前端：

```bash
cd frontend
npm test
npm run type-check
npm run lint -- --max-warnings 0
npm run build
```

PostgreSQL 迁移往返测试只允许使用名为 `finance_god_test` 的测试数据库：

```bash
cd backend
FINANCE_GOD_POSTGRES_TEST_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/finance_god_test \
  .venv/bin/pytest tests/integration/test_postgres_migrations.py -q
```

## 生产部署

准备并校验生产配置：

```bash
cp deploy/production.env.example deploy/.env.production
# 填写 deploy/.env.production

deploy/check-production-config.sh deploy/.env.production
docker compose --env-file deploy/.env.production \
  -f deploy/docker-compose.prod.yml config --quiet
```

仓库使用单一 GitHub Actions 工作流。Pull Request 和 `main` 推送都会执行边界检查、后端静态检查、四分片测试、PostgreSQL 迁移往返测试，以及前端测试、类型检查、零警告 lint 和生产构建。只有全部质量门禁成功后，`main` 才能进入生产部署；手动部署同样不能绕过门禁。

生产环境还需要在 GitHub Actions 中配置 `PRODUCTION_SMOKE_EMAIL`、`PRODUCTION_SMOKE_PASSWORD` 两项 secret，以及 `PRODUCTION_SMOKE_SYMBOL`、`PRODUCTION_SMOKE_QUANTITY` 两项 repository variable，用于受控的登录、交易台和仿真下单烟测。凭据应对应已建立且资金充足的独立仿真账户；任一配置缺失或烟测失败都会阻止部署成功。

部署完成后会验证容器状态、`/healthz`、`/api/ready`、页面深链、登录、仿真下单和公共 API。生产容器也可在服务器上直接启动：

```bash
docker compose --env-file deploy/.env.production \
  -f deploy/docker-compose.prod.yml up -d --build
```

## 安全与数据边界

- 不要把 `.env`、`deploy/.env.production`、数据库备份或凭据缓存提交到仓库。
- 行情与交易状态异常会在界面中显示错误或过期状态；交易关键事实不会被编造值替代。
- 订单请求需要幂等键；交易决策上下文会在提交时固化，并随真实仿真成交生成复盘快照。
- 用户身份来自已验证的 Bearer JWT，客户端不能通过自定义请求头选择数据所有者。
- 语音与模型调用由后端建立安全上下文，浏览器不会获得服务端密钥。

## 许可证

Finance-God 的第一方代码使用 [MIT License](LICENSE)，版权归 `2026 Xustalis` 所有。

`backend/vendor/` 包含随运行时分发的第三方代码与材料，它们继续适用各自目录中的许可证、NOTICE 和版权声明，不受根目录 MIT License 替代。
