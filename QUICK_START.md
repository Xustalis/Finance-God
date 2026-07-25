# Finance-God 快速上手指南

> 面向新加入项目的开发者
> 
> 最后更新：2026-07-25

## 📋 5分钟了解项目

**Finance-God** 是一个**中文优先的 Agent 主控仿真交易工作台**。

### 核心特点
- 🎯 **桌面端交易台**：左侧工作区（行情/持仓/交易），右侧常驻 AI Agent
- 📊 **真实行情**：通过 PandaData 提供实时市场数据
- 🎮 **仿真交易**：所有交易数据明确标记为仿真，不连接真实券商
- 🤖 **AI 编排**：内置 Agent 工作流，协调投资决策和交易执行

### 技术栈速览
- **前端**：Vue 3 + TypeScript + Vite + Pinia
- **后端**：FastAPI + SQLAlchemy 2 + PostgreSQL 16
- **AI**：DeepSeek / StepFun / ARK (OpenAI 兼容)

## 🚀 10分钟启动开发环境

### 前置要求
```bash
python --version    # 需要 3.11+
node --version      # 需要 20+
psql --version      # 需要 PostgreSQL 16
```

### 快速安装
```bash
# 1. 克隆并进入项目
cd Finance-God

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少设置 DATABASE_URL 和 DEV_ADMIN_PASSWORD

# 3. 安装后端依赖
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 4. 安装前端依赖
cd ../frontend
npm install

# 5. 启动数据库
cd ..
docker compose up -d db

# 6. 执行数据库迁移
cd backend
.venv/bin/alembic upgrade head
cd ..
make seed-dev-accounts
make seed-dev-workspace

# 7. 启动服务（本机进程方式，开三个终端）
# 终端1：后端
make backend

# 终端2：前端
cd frontend
npm run dev

# 终端3：Agent 持续自学习 Worker
cd backend
.venv/bin/python -m scripts.run_self_iteration_loop
```

也可以在项目根目录执行 `docker compose up -d --build`，一次启动数据库、后端、
前端和 Agent 持续自学习 Worker。Worker 默认每 900 秒执行一轮，并通过共享知识卷
向后端只读提供已验证学习成果。

### 访问应用
- 🌐 **前端**：http://localhost:3000
- 🔧 **API 文档**：http://localhost:8000/docs
- 👤 **管理后台**：http://localhost:3000/admin/login

## 📚 必读文档（按顺序）

### 第一天：了解全局
1. **项目总览**：[README.md](README.md) - 安装、配置、架构
2. **结构索引**：[docs/项目索引.md](docs/项目索引.md) - 目录、路由、API、数据库
3. **文档中心**：[docs/README.md](docs/README.md) - 文档层级和优先级规则

### 前端开发者必读
4. **开发规范**：[AGENTS.md](AGENTS.md) - 前端工作流和强制要求
5. **设计规范**：[docs/page-design/01_前端统一设计规范.md](docs/page-design/01_前端统一设计规范.md)
6. **数据合同**：[docs/page-design/02_前后端职责与数据合同.md](docs/page-design/02_前后端职责与数据合同.md)

### 后端开发者必读
7. **后端架构**：[backend/docs/architecture-overview.md](backend/docs/architecture-overview.md)
8. **API 规范**：[backend/docs/finance-api-reference.md](backend/docs/finance-api-reference.md)

### 产品/测试必读
9. **产品需求**：[docs/prd/Finance-God_Agent主控交易台_PRD_v2.0.md](docs/prd/Finance-God_Agent主控交易台_PRD_v2.0.md)

## 🔄 日常开发工作流

### 前端开发流程（必须遵守！）
```
1. 阅读设计规范
   ↓
2. 写设计简报（使用模板）
   ├─ docs/page-design/templates/前端设计简报模板.md
   └─ 存放到 docs/page-design/briefs/
   ↓
3. 实现功能
   ↓
4. 自检验收（使用模板）
   ├─ docs/page-design/templates/前端设计验收模板.md
   └─ 存放到 docs/page-design/acceptance/
   ↓
5. 提交代码
```

**⚠️ 重要**：前端任务必须先写设计简报，实现后写验收报告。这是强制流程！

### 后端开发流程
```bash
# 1. 创建功能分支
git checkout -b feat/your-feature

# 2. 开发功能（TDD推荐）
cd backend
.venv/bin/pytest tests/your_test.py -v

# 3. 运行完整测试
.venv/bin/pytest -q

# 4. 类型检查和编译
.venv/bin/python -m compileall -q finance_god tests

# 5. 提交
git add .
git commit -m "feat: your feature description"
```

### 数据库迁移流程
```bash
cd backend

# 创建新迁移
.venv/bin/alembic revision -m "description"

# 编辑生成的迁移文件
# alembic/versions/xxxxxx_description.py

# 应用迁移
.venv/bin/alembic upgrade head

# 查看迁移历史
.venv/bin/alembic history

# 回滚（谨慎！）
.venv/bin/alembic downgrade -1
```

## ✅ 代码质量检查

### 提交前必检项
```bash
# 前端
cd frontend
npm run type-check    # TypeScript 类型检查
npm run lint          # ESLint 检查
npm test              # 单元测试

# 后端
cd backend
.venv/bin/pytest -q   # 单元测试
.venv/bin/python -m compileall -q finance_god tests  # 编译检查
```

### 当前质量基线
- ✅ 前端类型检查：通过
- ✅ 前端测试：75 个测试全部通过
- ⚠️ 前端 Lint：9 个警告（`any` 类型使用），0 错误
- ✅ 后端编译检查：通过

## 🗂️ 项目结构速查

```
Finance-God/
├── backend/                  # 后端服务
│   ├── finance_god/         # 核心业务
│   │   ├── domain/         # 领域模型
│   │   ├── application/    # 应用服务
│   │   ├── execution/      # 订单引擎
│   │   ├── market_data/    # 行情适配
│   │   ├── orchestration/  # Agent 编排
│   │   └── api/           # HTTP 路由
│   ├── alembic/           # 数据库迁移
│   ├── tests/             # 测试
│   └── docs/              # 后端文档
│
├── frontend/               # 前端应用
│   ├── src/
│   │   ├── views/        # 页面（14个路由）
│   │   ├── components/   # 可复用组件
│   │   ├── stores/       # Pinia 状态
│   │   ├── services/     # 业务逻辑
│   │   └── api/         # API 客户端
│   └── public/          # 静态资源
│
└── docs/                 # 项目文档
    ├── prd/            # 产品需求
    ├── page-design/    # 前端规范
    ├── architecture/   # 架构设计
    └── research/       # 调研资料
```

## 🛣️ 前端路由清单

| 路由 | 状态 | 说明 |
|------|------|------|
| `/` | ✅ 完整 | 根据登录状态跳转 |
| `/login` | ✅ 完整 | 用户登录/注册 |
| `/app/exe` | ✅ 完整 | 投资画像问答 |
| `/app/profile-report` | ✅ 完整 | 画像报告 |
| `/overview` | 🟡 占位 | 交易总览 |
| `/markets` | ✅ 完整 | 行情浏览（PandaData） |
| `/desk` | 🟡 开发中 | 单标的交易台 |
| `/portfolio` | 🟡 占位 | 持仓组合 |
| `/orders` | 🟡 占位 | 订单管理 |
| `/reviews` | 🟡 占位 | 交易复盘 |
| `/data` | 🟡 占位 | 数据中心 |
| `/settings` | 🟡 占位 | 用户设置 |
| `/admin/login` | ✅ 完整 | 管理员登录 |
| `/admin/ai-settings` | ✅ 完整 | AI 配置 |

## 🔌 API 端点速查

### 认证相关
- `POST /api/v1/auth/login` - 用户登录
- `POST /api/v1/auth/register` - 用户注册
- `POST /api/v1/admin/login` - 管理员登录

### 画像相关
- `/api/v1/profile/*` - 投资画像接口

### Finance API（行情与交易）
- `GET /api/finance/health` - 健康检查
- `GET /api/finance/market/quotes` - 批量报价
- `GET /api/finance/market/bars` - K线数据
- `GET /api/finance/market/catalog` - 能力目录
- `/api/finance/workspace/*` - 工作区服务
- `/api/finance/simulation/*` - 仿真交易

## 🎯 常见任务快速指南

### 添加新的前端页面
```bash
# 1. 写设计简报
# 2. 创建 Vue 组件
frontend/src/views/YourPageView.vue

# 3. 添加路由
# 编辑 frontend/src/router.ts

# 4. 添加状态管理（如需要）
frontend/src/stores/yourFeature.ts

# 5. 添加测试
frontend/src/tests/your-feature.spec.ts

# 6. 写验收报告
```

### 添加新的 API 端点
```bash
# 1. 定义 Pydantic 模型
backend/finance_god/api/schemas/your_feature.py

# 2. 添加路由
backend/finance_god/api/your_feature.py

# 3. 注册路由
# 编辑 backend/server.py 或 backend/app/main.py

# 4. 添加测试
backend/tests/api/test_your_feature.py

# 5. 更新 API 文档
# 编辑 backend/docs/finance-api-reference.md
```

### 添加数据库表
```bash
# 1. 创建迁移
cd backend
.venv/bin/alembic revision -m "add your_table"

# 2. 编辑迁移文件
# 定义 upgrade() 和 downgrade()

# 3. 应用迁移
.venv/bin/alembic upgrade head

# 4. 更新领域模型（如需要）
# backend/finance_god/domain/models.py

# 5. 更新持久化层
# backend/finance_god/infrastructure/persistence/
```

## 🐛 常见问题排查

### 前端启动失败
```bash
# 检查 Node 版本
node --version  # 需要 20+

# 清理并重装依赖
rm -rf node_modules package-lock.json
npm install

# 检查端口占用
lsof -i :3000
```

### 后端启动失败
```bash
# 检查 Python 版本
python --version  # 需要 3.11+

# 重建虚拟环境
cd backend
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 检查端口占用
lsof -i :8000

# 检查数据库连接
psql $DATABASE_URL
```

### 数据库连接失败
```bash
# 检查 PostgreSQL 是否运行
docker compose ps

# 启动数据库
docker compose up -d db

# 查看日志
docker compose logs db

# 检查环境变量
echo $DATABASE_URL
```

### PandaData 行情无数据
```bash
# 检查环境变量
echo $PANDA_DATA_USERNAME
echo $PANDA_DATA_PASSWORD

# 查看健康检查
curl http://localhost:8000/api/finance/health

# 查看后端日志
# 应该显示 PandaData 连接状态
```

## 📞 获取帮助

### 代码问题
1. 先查看相关文档（见"必读文档"章节）
2. 搜索现有代码中的类似实现
3. 查看测试用例作为使用示例

### 规范问题
- 前端规范：`docs/page-design/01_前端统一设计规范.md`
- 后端架构：`backend/docs/architecture-overview.md`
- API 合同：`backend/docs/finance-api-reference.md`

### 文档冲突
按优先级顺序：
1. 安全和数据完整性
2. 最新 PRD 和前端强制规范
3. 页面专项规格
4. 研究和实施计划

## 🎓 进阶学习

### 深入了解架构
- Agent 编排机制：`docs/architecture/agent-swarm-technical.md`
- 工作流实验：`docs/experiments/workflow-experiments.md`
- 市场分析：`docs/market-analysis/Finance-God_市场分析报告.md`

### 掌握核心概念
- **领域驱动设计**：查看 `backend/finance_god/domain/`
- **事件溯源**：查看 `backend/finance_god/application/ledger_service.py`
- **仿真撮合**：查看 `backend/finance_god/execution/matcher.py`
- **Agent 运行时**：查看 `backend/finance_god/orchestration/`

## 📊 项目统计

- 📝 **代码文件**：13,812 个
- 🧪 **测试覆盖**：75 个前端测试
- 📄 **文档页面**：50+ 个
- 🗄️ **数据库表**：4 个迁移链
- 🛣️ **前端路由**：14 个
- 🔌 **API 端点**：20+ 个

---

**欢迎加入 Finance-God！** 🚀

有问题随时查阅项目文档或询问团队成员。记住：代码和测试是最终的真相，文档是导航地图。
