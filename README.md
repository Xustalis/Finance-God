# Finance-God

心智驱动的 AI 投资顾问 — 黑客松 MVP。

后端：FastAPI + SQLAlchemy 2 + PostgreSQL  
前端：React 18 + TypeScript + Vite + Ant Design  
能力：插件化数据源/LLM/Agent/风控，仿真交易闭环

## 快速开始

### 1. 环境准备

- Python 3.11+
- Node.js 20+
- Docker（用于 PostgreSQL，可选）

```bash
# 复制环境变量
cp .env.example .env

# 后端依赖（建议使用 venv）
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd ..

# 前端依赖
cd frontend && npm install && cd ..
```

### 2. 启动数据库

```bash
docker compose up -d db
# 或 make db
```

### 3. 数据库迁移

```bash
cd backend
# 确保 DATABASE_URL_SYNC 指向本机 Postgres（见 .env.example）
alembic upgrade head
cd ..
```

### 4. 启动开发服务

分两个终端：

```bash
# 后端 http://localhost:8000
make backend
# API 文档: http://localhost:8000/docs

# 前端 http://localhost:3000
make frontend
```

或使用：

```bash
make install   # 安装前后端依赖
make db        # 启动 Postgres
make migrate   # 迁移
make backend   # 另开终端
make frontend  # 另开终端
```

### 5. 健康检查

```bash
curl http://localhost:8000/health
# {"status":"healthy"}
```

## 项目结构

```
Finance-God/
├── backend/           # FastAPI 应用
│   ├── app/
│   │   ├── api/v1/    # REST 路由
│   │   ├── agents/    # Agent 插件
│   │   ├── models/    # ORM
│   │   ├── services/  # 业务服务
│   │   ├── plugins/   # 数据源/LLM/费用/滑点
│   │   ├── risk/      # 风控规则引擎
│   │   └── evolution/ # 自进化
│   └── alembic/       # 迁移
├── frontend/          # React 前端
├── docs/              # PRD / 实现计划
├── docker-compose.yml
└── Makefile
```

## 配置说明

关键环境变量见 `.env.example`：

| 变量 | 说明 | 默认 |
|------|------|------|
| `DATABASE_URL` | 异步库连接 | localhost Postgres |
| `LLM_PROVIDER` | `mock` / `deepseek` / `volcengine` | `mock` |
| `DATA_PROVIDER` | `mock` / `pandaai` | `mock` |
| `SECRET_KEY` | JWT 密钥 | 开发占位，生产必须更换 |

开发默认使用 **mock** LLM 与数据源，无需真实 API Key 即可联调。

## 当前状态（MVP）

- [x] 后端骨架：认证、画像、授权、订单/仿真、Agent 插件
- [x] 初始数据库迁移
- [ ] 前端业务页面（目前多为占位）
- [ ] 完整风控规则与自动化测试

## 文档

- [MVP PRD](docs/prd/Finance-God_MVP_PRD_v1.0.md)
- [黑客松实现计划](docs/superpowers/plans/2026-07-23-hackathon-implementation-plan.md)
