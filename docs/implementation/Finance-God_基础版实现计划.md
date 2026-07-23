# Flinance-God 基础版系统实现计划

> 创建时间：2026年7月 | 状态：待评审 | 版本：v2.0

---

## 一、项目概述与范围

### 1.1 实现目标

基于 PRD v1.0 定义的"阶段A + 阶段B"范围，实现一个完整的仿真交易闭环系统。本基础版覆盖 PRD 中全部 P0 需求，但不包含实盘交易能力（P1）。

### 1.2 核心技术约束（来源：PRD 6.1 不可违反的业务规则）

| 约束ID | 约束内容                       | 对实现的影响                                                    |
| ------ | ------------------------------ | --------------------------------------------------------------- |
| BR-03  | 全链路版本追溯                 | 每个核心对象必须有 version 字段，所有关联通过版本号串联         |
| BR-04  | Agent 不得修改画像/授权/硬约束 | Agent 输出只能建议，不能直接写入 UserProfile/InvestmentMandate  |
| BR-15  | 心智状态只能触发提示/冷静期    | 心智状态信号有独立的处理路径，不能流入策略生成管线              |
| RK-01  | 三段风控校验                   | 组合生成、订单创建、订单提交三个阶段各有独立的风控检查点        |
| AG-07  | 编排优先级固定                 | 用户暂停 > 硬风控 > 心智冷静期 > 数据异常 > 策略机会 > 定期维护 |

### 1.3 技术选型

| 层级       | 选型                    | 版本要求  | 选择理由                                  |
| ---------- | ----------------------- | --------- | ----------------------------------------- |
| 后端框架   | FastAPI                 | 0.110+    | 异步原生、OpenAPI 自动生成、Pydantic 校验 |
| ORM        | SQLAlchemy 2.0          | 2.0+      | 声明式模型、异步支持、类型安全            |
| 数据库迁移 | Alembic                 | 1.13+     | SQLAlchemy 生态标准、版本化迁移           |
| 前端框架   | React + TypeScript      | React 18+ | 生态成熟、组件丰富                        |
| 构建工具   | Vite                    | 5+        | 快速开发体验                              |
| UI 组件    | Ant Design              | 5+        | 企业级组件、表单和表格能力强              |
| Agent 框架 | LangGraph               | 0.2+      | 状态图编排、与 LangChain 集成             |
| LLM        | OpenAI API (GPT-4o)     | -         | 研究 Agent 和策略解释需要高质量推理       |
| 数据库     | PostgreSQL              | 16+       | JSONB 支持、分区表、强一致性              |
| 缓存       | Redis                   | 7+        | 会话缓存、市场数据快照、限流              |
| 市场数据   | AKShare + yfinance      | -         | 免费、覆盖 A 股/美股/港股 ETF             |
| 容器化     | Docker + docker-compose | -         | 开发环境一致性                            |

### 1.4 项目目录结构

```
finance-god/
├── docker-compose.yml
├── .env.example
├── Makefile
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   ├── core/
│   │   │   ├── security.py          # JWT 认证
│   │   │   ├── exceptions.py        # 全局异常处理
│   │   │   ├── events.py            # 领域事件总线
│   │   │   ├── versioning.py        # 版本化工具
│   │   │   ├── audit.py             # 审计事件写入
│   │   │   └── pagination.py        # 统一分页
│   │   ├── models/                  # SQLAlchemy ORM (16张表)
│   │   ├── schemas/                 # Pydantic 请求/响应 Schema
│   │   ├── api/v1/                  # REST API 路由层
│   │   ├── services/                # 业务服务层
│   │   ├── agents/                  # LangGraph Agent 系统
│   │   │   ├── graph.py             # 主编排图
│   │   │   ├── state.py             # Agent 全局状态
│   │   │   ├── user_state_agent.py
│   │   │   ├── market_agent.py
│   │   │   ├── research_agent.py
│   │   │   ├── strategy_agent.py
│   │   │   ├── portfolio_agent.py
│   │   │   ├── execution_agent.py
│   │   │   ├── risk_agent.py
│   │   │   └── tools/
│   │   ├── data/providers/          # 市场数据接入
│   │   └── db/repositories/         # 数据访问仓库
│   └── tests/
└── frontend/
    └── src/
        ├── api/
        ├── hooks/
        ├── stores/                  # Zustand
        ├── pages/
        │   ├── Home/
        │   ├── Profile/
        │   ├── Mandate/
        │   ├── Portfolio/
        │   ├── AgentCenter/
        │   ├── Trading/
        │   └── Review/
        └── components/
```

---

## 二、完整数据对象定义

### 2.1 通用设计原则

- 所有表使用 **UUID 主键**（`uuid4`）
- 所有表包含 `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` 和 `updated_at TIMESTAMPTZ`
- 需要版本化的表包含 `version INTEGER NOT NULL DEFAULT 1`
- 灵活属性使用 **JSONB** 类型
- 金额字段使用 `NUMERIC(18,4)`，比例字段使用 `NUMERIC(8,6)`
- 枚举字段使用 `VARCHAR(32)` + Python `StrEnum`，不使用数据库级 ENUM（便于迁移）
- 软删除使用 `deleted_at TIMESTAMPTZ NULL`

### 2.2 表定义：users（用户账户）

| 字段            | 类型         | 约束             | 默认值   | 说明                      |
| --------------- | ------------ | ---------------- | -------- | ------------------------- |
| id              | UUID         | PK               | uuid4    | 用户唯一ID                |
| email           | VARCHAR(255) | UNIQUE, NOT NULL | -        | 登录邮箱                  |
| hashed_password | VARCHAR(255) | NOT NULL         | -        | bcrypt 哈希               |
| display_name    | VARCHAR(100) | NULLABLE         | -        | 显示名称                  |
| base_currency   | VARCHAR(3)   | NOT NULL         | 'CNY'    | 本位币 ISO 4217           |
| region          | VARCHAR(10)  | NOT NULL         | 'CN'     | 用户地区 ISO 3166-1       |
| status          | VARCHAR(32)  | NOT NULL         | 'active' | active / frozen / deleted |
| last_login_at   | TIMESTAMPTZ  | NULLABLE         | -        | 最后登录时间              |
| created_at      | TIMESTAMPTZ  | NOT NULL         | now()    | 创建时间                  |
| updated_at      | TIMESTAMPTZ  | NULLABLE         | -        | 更新时间                  |

### 2.3 表定义：user_profiles（量化用户画像）

对应 PRD 对象：`UserProfile`

| 字段                  | 类型         | 约束                  | 默认值  | 说明                                                                                                     |
| --------------------- | ------------ | --------------------- | ------- | -------------------------------------------------------------------------------------------------------- |
| id                    | UUID         | PK                    | uuid4   |                                                                                                          |
| user_id               | UUID         | FK→users.id, NOT NULL | -       | 所属用户                                                                                                 |
| version               | INTEGER      | NOT NULL              | 1       | 画像版本号，递增                                                                                         |
| goals                 | JSONB        | NOT NULL              | '[]'    | 目标列表：`[{name, target_amount, target_date, priority}]`                                               |
| financial_constraints | JSONB        | NOT NULL              | '{}'    | `{base_currency, investable_amount, emergency_fund, near_term_cash_needs, major_liabilities}`            |
| stated_risk           | JSONB        | NOT NULL              | '{}'    | `{loss_tolerance, volatility_tolerance, experience_years, preference, source, confidence, collected_at}` |
| revealed_risk         | JSONB        | NOT NULL              | '{}'    | `{inferred_tolerance, behavioral_signals, source, confidence, collected_at}`                             |
| behavioral_prefs      | JSONB        | NOT NULL              | '{}'    | `{review_frequency, drawdown_reaction, autonomy_preference, info_preference}`                            |
| restrictions          | JSONB        | NOT NULL              | '{}'    | `{regions, product_exclusions, concentration_limits, esg_preference, compliance_restrictions}`           |
| completeness          | NUMERIC(5,4) | NOT NULL              | 0       | 完整度 0~1，由系统计算                                                                                   |
| confidence            | NUMERIC(5,4) | NOT NULL              | 0       | 整体置信度 0~1，由系统计算                                                                               |
| status                | VARCHAR(32)  | NOT NULL              | 'draft' | draft / confirmed / superseded                                                                           |
| confirmed_at          | TIMESTAMPTZ  | NULLABLE              | -       | 用户确认时间                                                                                             |
| created_at            | TIMESTAMPTZ  | NOT NULL              | now()   |                                                                                                          |
| updated_at            | TIMESTAMPTZ  | NULLABLE              | -       |                                                                                                          |

**唯一约束**：`UNIQUE(user_id, version)`

**completeness 计算规则**：

- goals（至少1个）= 20%
- financial_constraints（5个子字段）= 20%
- stated_risk（4个子字段）= 20%
- behavioral_prefs（2个子字段）= 10%
- restrictions（至少1个非空）= 10%
- revealed_risk（有行为数据）= 20%

**confidence 计算规则**：

- 各维度的 source_confidence 加权平均
- 用户确认（status=confirmed）→ confidence += 0.2（上限1.0）
- 数据新鲜度衰减：超过90天 → confidence × 0.8

### 2.4 表定义：user_state_snapshots（用户心智状态快照）

对应 PRD 对象：`UserStateSnapshot`

| 字段              | 类型         | 约束                  | 默认值    | 说明                                                                                                                          |
| ----------------- | ------------ | --------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------- |
| id                | UUID         | PK                    | uuid4     |                                                                                                                               |
| user_id           | UUID         | FK→users.id, NOT NULL | -         |                                                                                                                               |
| version           | INTEGER      | NOT NULL              | 1         |                                                                                                                               |
| mental_state      | JSONB        | NOT NULL              | '{}'      | `{anxiety_level, greed_level, impulsivity, confidence_level, mood_trend}` — 每个值0~1                                         |
| cognitive_biases  | JSONB        | NOT NULL              | '[]'      | `[{bias_type, severity, evidence, detected_at}]` bias_type: loss_aversion/overconfidence/herding/anchoring/disposition_effect |
| signal_sources    | JSONB        | NOT NULL              | '[]'      | `[{source_type, source_id, collected_at}]` source_type: app_behavior/dialog_feedback/user_diary                               |
| consent_scope     | VARCHAR(255) | NOT NULL              | -         | 采集同意范围描述                                                                                                              |
| confidence        | NUMERIC(5,4) | NOT NULL              | 0         | 状态置信度                                                                                                                    |
| expires_at        | TIMESTAMPTZ  | NOT NULL              | -         | 状态有效期（默认24h）                                                                                                         |
| user_confirmation | VARCHAR(32)  | NOT NULL              | 'pending' | pending / confirmed / corrected / rejected                                                                                    |
| user_feedback     | TEXT         | NULLABLE              | -         | 用户修正说明                                                                                                                  |
| created_at        | TIMESTAMPTZ  | NOT NULL              | now()     |                                                                                                                               |

**唯一约束**：`UNIQUE(user_id, version)`

### 2.5 表定义：investment_mandates（投资授权书）

对应 PRD 对象：`InvestmentMandate`

| 字段                    | 类型          | 约束                  | 默认值      | 说明                                                                             |
| ----------------------- | ------------- | --------------------- | ----------- | -------------------------------------------------------------------------------- |
| id                      | UUID          | PK                    | uuid4       |                                                                                  |
| user_id                 | UUID          | FK→users.id, NOT NULL | -           |                                                                                  |
| version                 | INTEGER       | NOT NULL              | 1           |                                                                                  |
| profile_version         | INTEGER       | NOT NULL              | -           | 引用的画像版本                                                                   |
| goal_priorities         | JSONB         | NOT NULL              | '[]'        | `[{goal_name, priority_rank}]`                                                   |
| risk_budget             | JSONB         | NOT NULL              | '{}'        | `{max_drawdown, volatility_cap, loss_tolerance_annual}` — 全为 NUMERIC           |
| cash_boundary           | JSONB         | NOT NULL              | '{}'        | `{min_cash_ratio, emergency_reserve, near_term_reserve}`                         |
| asset_scope             | JSONB         | NOT NULL              | '{}'        | `{allowed_asset_types, allowed_markets, excluded_instruments, excluded_sectors}` |
| concentration_limits    | JSONB         | NOT NULL              | '{}'        | `{max_single_asset, max_sector, max_region, max_country}`                        |
| rebalance_frequency     | VARCHAR(32)   | NOT NULL              | 'quarterly' | quarterly / monthly / threshold_based / manual                                   |
| rebalance_threshold     | NUMERIC(5,4)  | NOT NULL              | 0.05        | 偏离超过此值触发再平衡                                                           |
| autonomy_level          | VARCHAR(4)    | NOT NULL              | 'L0'        | L0 / L1 / L2 / L3                                                                |
| max_single_order_amount | NUMERIC(18,4) | NULLABLE              | -           | 单笔订单限额                                                                     |
| valid_from              | TIMESTAMPTZ   | NOT NULL              | -           | 有效期开始                                                                       |
| valid_until             | TIMESTAMPTZ   | NULLABLE              | -           | 有效期结束（NULL=永久）                                                          |
| status                  | VARCHAR(32)   | NOT NULL              | 'draft'     | draft / active / paused / revoked / expired / superseded                         |
| revoked_at              | TIMESTAMPTZ   | NULLABLE              | -           | 撤销时间                                                                         |
| revoke_reason           | TEXT          | NULLABLE              | -           | 撤销原因                                                                         |
| created_at              | TIMESTAMPTZ   | NOT NULL              | now()       |                                                                                  |
| updated_at              | TIMESTAMPTZ   | NULLABLE              | -           |                                                                                  |

**唯一约束**：`UNIQUE(user_id, version)`
**索引**：`(user_id, status)` — 快速查找 active 授权

### 2.6 表定义：holding_snapshots（持仓快照）

对应 PRD 对象：`HoldingSnapshot`

| 字段                 | 类型          | 约束                  | 默认值   | 说明                                                                            |
| -------------------- | ------------- | --------------------- | -------- | ------------------------------------------------------------------------------- |
| id                   | UUID          | PK                    | uuid4    |                                                                                 |
| user_id              | UUID          | FK→users.id, NOT NULL | -        |                                                                                 |
| version              | INTEGER       | NOT NULL              | 1        |                                                                                 |
| source_type          | VARCHAR(32)   | NOT NULL              | 'manual' | manual / csv_import / broker_sync                                               |
| positions            | JSONB         | NOT NULL              | '[]'     | `[{instrument_id, symbol, quantity, avg_cost, market_value, currency, weight}]` |
| unresolved_positions | JSONB         | NOT NULL              | '[]'     | `[{raw_name, raw_symbol, quantity, estimated_value, match_candidates}]`         |
| unresolved_weight    | NUMERIC(5,4)  | NOT NULL              | 0        | 未解析持仓占比                                                                  |
| total_market_value   | NUMERIC(18,4) | NOT NULL              | 0        | 总市值                                                                          |
| total_cost_basis     | NUMERIC(18,4) | NOT NULL              | 0        | 总成本                                                                          |
| cash_balance         | NUMERIC(18,4) | NOT NULL              | 0        | 现金余额                                                                        |
| valuation_as_of      | TIMESTAMPTZ   | NOT NULL              | -        | 估值时点                                                                        |
| created_at           | TIMESTAMPTZ   | NOT NULL              | now()    |                                                                                 |

**唯一约束**：`UNIQUE(user_id, version)`
**业务规则**：`unresolved_weight > 0.15`（可配置阈值）时，组合构造返回不可构造

### 2.7 表定义：instruments（资产主数据）

对应 PRD 对象：`Instrument`

| 字段               | 类型          | 约束             | 默认值   | 说明                                                     |
| ------------------ | ------------- | ---------------- | -------- | -------------------------------------------------------- |
| id                 | UUID          | PK               | uuid4    |                                                          |
| symbol             | VARCHAR(32)   | UNIQUE, NOT NULL | -        | 标准代码（如 510300.SH）                                 |
| name               | VARCHAR(255)  | NOT NULL         | -        | 资产名称                                                 |
| asset_type         | VARCHAR(32)   | NOT NULL         | -        | etf / mutual_fund                                        |
| market             | VARCHAR(32)   | NOT NULL         | -        | a_shares / us_stocks / hk_stocks                         |
| currency           | VARCHAR(3)    | NOT NULL         | -        | 计价币种                                                 |
| exchange           | VARCHAR(32)   | NULLABLE         | -        | 交易所代码                                               |
| min_trade_unit     | NUMERIC(18,4) | NOT NULL         | 1        | 最小交易单位                                             |
| expense_ratio      | NUMERIC(8,6)  | NULLABLE         | -        | 管理费率                                                 |
| sector             | VARCHAR(100)  | NULLABLE         | -        | 行业/板块                                                |
| benchmark          | VARCHAR(100)  | NULLABLE         | -        | 基准指数                                                 |
| trading_attributes | JSONB         | NOT NULL         | '{}'     | `{lot_size, tick_size, trading_hours, settlement_cycle}` |
| available_regions  | JSONB         | NOT NULL         | '[]'     | 可用地区列表                                             |
| status             | VARCHAR(32)   | NOT NULL         | 'active' | active / suspended / delisted                            |
| data_as_of         | TIMESTAMPTZ   | NOT NULL         | -        | 数据时点                                                 |
| created_at         | TIMESTAMPTZ   | NOT NULL         | now()    |                                                          |
| updated_at         | TIMESTAMPTZ   | NULLABLE         | -        |                                                          |

**索引**：`UNIQUE(symbol)`, `(market, asset_type, status)`

### 2.8 表定义：research_memos（研究备忘录）

对应 PRD 对象：`ResearchMemo`

| 字段          | 类型        | 约束                        | 默认值        | 说明                                                       |
| ------------- | ----------- | --------------------------- | ------------- | ---------------------------------------------------------- |
| id            | UUID        | PK                          | uuid4         |                                                            |
| instrument_id | UUID        | FK→instruments.id, NOT NULL | -             | 研究标的                                                   |
| version       | INTEGER     | NOT NULL                    | 1             |                                                            |
| evidence      | JSONB       | NOT NULL                    | '[]'          | `[{source, url, published_at, summary, reliability}]`      |
| facts         | JSONB       | NOT NULL                    | '[]'          | `[{statement, source_id, verified}]`                       |
| inferences    | JSONB       | NOT NULL                    | '[]'          | `[{statement, model_or_rule, confidence, assumptions}]`    |
| bull_case     | JSONB       | NOT NULL                    | '{}'          | `{thesis, key_drivers, probability, risks_to_case}`        |
| bear_case     | JSONB       | NOT NULL                    | '{}'          | `{thesis, key_drivers, probability, risks_to_case}`        |
| base_case     | JSONB       | NOT NULL                    | '{}'          | `{thesis, expected_return_range, confidence}`              |
| risks         | JSONB       | NOT NULL                    | '[]'          | `[{description, likelihood, impact, mitigants}]`           |
| unknowns      | JSONB       | NOT NULL                    | '[]'          | `[description]` — 明确列出已知不知道的                     |
| status        | VARCHAR(32) | NOT NULL                    | 'in_progress' | in_progress / usable / insufficient / expired / superseded |
| model_version | VARCHAR(64) | NULLABLE                    | -             | 使用的LLM/规则版本                                         |
| expires_at    | TIMESTAMPTZ | NOT NULL                    | -             | 研究时效（默认7天）                                        |
| created_at    | TIMESTAMPTZ | NOT NULL                    | now()         |                                                            |
| updated_at    | TIMESTAMPTZ | NULLABLE                    | -             |                                                            |

**业务规则（BR-06）**：`status = usable` 要求 facts 非空 AND bear_case.thesis 非空 AND risks 非空 AND expires_at > now()

### 2.9 表定义：market_contexts（市场环境快照）

对应 PRD 对象：`MarketContext`

| 字段                   | 类型         | 约束     | 默认值   | 说明                                                                                                                      |
| ---------------------- | ------------ | -------- | -------- | ------------------------------------------------------------------------------------------------------------------------- |
| id                     | UUID         | PK       | uuid4    |                                                                                                                           |
| version                | INTEGER      | NOT NULL | 1        |                                                                                                                           |
| markets                | JSONB        | NOT NULL | '{}'     | `{a_shares: {sentiment_score, trend, key_events[]}, us_stocks: {...}, hk_stocks: {...}}` — 每个市场的sentiment_score为0~1 |
| overall_sentiment      | NUMERIC(5,4) | NOT NULL | 0.5      | 综合情绪分数                                                                                                              |
| events_summary         | JSONB        | NOT NULL | '[]'     | `[{event_type, description, market, impact_assessment, source}]`                                                          |
| data_quality           | JSONB        | NOT NULL | '{}'     | `{completeness, freshness, source_count, conflicts[]}`                                                                    |
| sources                | JSONB        | NOT NULL | '[]'     | `[{provider, data_type, as_of, url}]`                                                                                     |
| applicable_markets     | JSONB        | NOT NULL | '[]'     | 适用范围                                                                                                                  |
| applicable_instruments | JSONB        | NOT NULL | '[]'     | 适用资产范围                                                                                                              |
| confidence             | NUMERIC(5,4) | NOT NULL | 0        |                                                                                                                           |
| usable_status          | VARCHAR(32)  | NOT NULL | 'usable' | usable / stale / conflicting / insufficient                                                                               |
| data_as_of             | TIMESTAMPTZ  | NOT NULL | -        | 数据时点                                                                                                                  |
| expires_at             | TIMESTAMPTZ  | NOT NULL | -        | 有效期（默认4小时）                                                                                                       |
| created_at             | TIMESTAMPTZ  | NOT NULL | now()    |                                                                                                                           |

**业务规则（BR-07）**：`usable_status != usable` 时，策略生成和订单提交必须显式失败

### 2.10 表定义：strategy_proposals（策略方案）

对应 PRD 对象：`StrategyProposal`

| 字段                     | 类型        | 约束                  | 默认值      | 说明                                                                                  |
| ------------------------ | ----------- | --------------------- | ----------- | ------------------------------------------------------------------------------------- |
| id                       | UUID        | PK                    | uuid4       |                                                                                       |
| version                  | INTEGER     | NOT NULL              | 1           |                                                                                       |
| user_id                  | UUID        | FK→users.id, NOT NULL | -           |                                                                                       |
| mandate_version          | INTEGER     | NOT NULL              | -           | 引用的授权书版本                                                                      |
| market_context_id        | UUID        | FK→market_contexts.id | -           | 使用的市场环境                                                                        |
| research_memo_ids        | JSONB       | NOT NULL              | '[]'        | 引用的研究ID列表                                                                      |
| global_allocation        | JSONB       | NOT NULL              | '{}'        | `{cash_ratio, equity_ratio, bond_ratio, commodity_ratio, alternative_ratio}`          |
| market_allocation        | JSONB       | NOT NULL              | '{}'        | `{a_shares: {weight, sub_allocations[]}, us_stocks: {...}, hk_stocks: {...}}`         |
| mental_adaptations       | JSONB       | NOT NULL              | '{}'        | `{adaptations_applied[], explanation, user_state_snapshot_id}` — 仅描述性，不修改约束 |
| risk_scenarios           | JSONB       | NOT NULL              | '[]'        | `[{scenario_name, expected_return, expected_volatility, max_drawdown, probability}]`  |
| assumptions              | JSONB       | NOT NULL              | '[]'        | `[description]`                                                                       |
| applicable_mandate_scope | JSONB       | NOT NULL              | '{}'        | 声明适用的授权范围                                                                    |
| invalidation_conditions  | JSONB       | NOT NULL              | '[]'        | 失效条件列表                                                                          |
| model_version            | VARCHAR(64) | NULLABLE              | -           | 使用的模型/规则版本                                                                   |
| status                   | VARCHAR(32) | NOT NULL              | 'candidate' | candidate / accepted / rejected / superseded / invalid                                |
| created_at               | TIMESTAMPTZ | NOT NULL              | now()       |                                                                                       |

**业务规则（BR-05）**：`assumptions` 与 `facts` 必须明确区分，不能混合

### 2.11 表定义：target_portfolios（目标组合）

对应 PRD 对象：`TargetPortfolio`

| 字段                     | 类型          | 约束                               | 默认值  | 说明                                                                                                       |
| ------------------------ | ------------- | ---------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------- |
| id                       | UUID          | PK                                 | uuid4   |                                                                                                            |
| version                  | INTEGER       | NOT NULL                           | 1       |                                                                                                            |
| user_id                  | UUID          | FK→users.id, NOT NULL              | -       |                                                                                                            |
| strategy_proposal_id     | UUID          | FK→strategy_proposals.id, NOT NULL | -       |                                                                                                            |
| mandate_version          | INTEGER       | NOT NULL                           | -       |                                                                                                            |
| profile_version          | INTEGER       | NOT NULL                           | -       |                                                                                                            |
| holding_snapshot_version | INTEGER       | NOT NULL                           | -       |                                                                                                            |
| market_context_id        | UUID          | FK→market_contexts.id, NOT NULL    | -       |                                                                                                            |
| target_weights           | JSONB         | NOT NULL                           | '[]'    | `[{instrument_id, symbol, weight, target_value, current_weight, delta}]`                                   |
| constraint_report        | JSONB         | NOT NULL                           | '{}'    | `{passed: [{rule, value, limit}], failed: [{rule, value, limit, severity, explanation}], warnings: [...]}` |
| risk_metrics             | JSONB         | NOT NULL                           | '{}'    | `{expected_return, expected_volatility, sharpe_ratio, max_drawdown, var_95, concentration_index}`          |
| rebalance_plan           | JSONB         | NOT NULL                           | '[]'    | `[{instrument_id, symbol, action(buy/sell), quantity, estimated_value, priority, reason}]`                 |
| total_expected_cost      | NUMERIC(18,4) | NOT NULL                           | 0       | 预估交易费用                                                                                               |
| total_expected_slippage  | NUMERIC(18,4) | NOT NULL                           | 0       | 预估滑点                                                                                                   |
| constructible            | BOOLEAN       | NOT NULL                           | true    | 是否可构造                                                                                                 |
| constructible_reason     | TEXT          | NULLABLE                           | -       | 不可构造时的原因                                                                                           |
| data_coverage            | NUMERIC(5,4)  | NOT NULL                           | 1       | 数据覆盖率                                                                                                 |
| computed_at              | TIMESTAMPTZ   | NOT NULL                           | now()   | 计算时间                                                                                                   |
| status                   | VARCHAR(32)   | NOT NULL                           | 'draft' | draft / confirmed / executing / executed / invalid                                                         |
| created_at               | TIMESTAMPTZ   | NOT NULL                           | now()   |                                                                                                            |

### 2.12 表定义：order_intents（订单意图）

对应 PRD 对象：`OrderIntent`

| 字段              | 类型          | 约束                        | 默认值       | 说明                                                 |
| ----------------- | ------------- | --------------------------- | ------------ | ---------------------------------------------------- |
| id                | UUID          | PK                          | uuid4        |                                                      |
| idempotency_key   | VARCHAR(128)  | UNIQUE, NOT NULL            | uuid4        | 幂等键                                               |
| user_id           | UUID          | FK→users.id, NOT NULL       | -            |                                                      |
| account_type      | VARCHAR(32)   | NOT NULL                    | 'simulation' | simulation / live（P0仅simulation）                  |
| instrument_id     | UUID          | FK→instruments.id, NOT NULL | -            |                                                      |
| symbol            | VARCHAR(32)   | NOT NULL                    | -            | 冗余，便于查询                                       |
| direction         | VARCHAR(8)    | NOT NULL                    | -            | buy / sell                                           |
| quantity          | NUMERIC(18,4) | NOT NULL                    | -            | 委托数量                                             |
| price_limit       | NUMERIC(18,4) | NULLABLE                    | -            | 限价（NULL=市价）                                    |
| price_protection  | JSONB         | NOT NULL                    | '{}'         | `{max_deviation, reference_price, reference_source}` |
| mandate_version   | INTEGER       | NOT NULL                    | -            | 引用的授权书版本                                     |
| portfolio_version | INTEGER       | NULLABLE                    | -            | 引用的组合版本                                       |
| strategy_version  | INTEGER       | NULLABLE                    | -            | 引用的策略版本                                       |
| risk_check_1      | JSONB         | NOT NULL                    | '{}'         | 组合生成阶段校验：`{passed, checks[], blocked_by}`   |
| risk_check_2      | JSONB         | NOT NULL                    | '{}'         | 订单创建阶段校验                                     |
| risk_check_3      | JSONB         | NOT NULL                    | '{}'         | 订单提交阶段校验                                     |
| status            | VARCHAR(32)   | NOT NULL                    | 'pending'    | 状态机（见下方）                                     |
| expires_at        | TIMESTAMPTZ   | NOT NULL                    | -            | 过期时间                                             |
| cancel_reason     | TEXT          | NULLABLE                    | -            | 取消原因                                             |
| blocked_by        | JSONB         | NULLABLE                    | -            | 阻断详情                                             |
| created_at        | TIMESTAMPTZ   | NOT NULL                    | now()        |                                                      |
| updated_at        | TIMESTAMPTZ   | NULLABLE                    | -            |                                                      |

**订单状态机**：

```
pending → approved → queued → submitted → partial_fill → filled
                                    ↓                        ↓
                                 rejected                 cancelled
                                    ↓
                                cancelled
         ↓ (任意阶段风控阻断)
       blocked
```

状态转换规则：

- `pending → approved`：risk_check_1 + risk_check_2 全部通过
- `approved → queued`：加入执行队列
- `queued → submitted`：risk_check_3 通过，提交到市场
- `submitted → partial_fill`：部分成交
- `partial_fill → filled`：完全成交
- `任意状态 → blocked`：风控阻断
- `queued/submitted → cancelled`：用户取消或暂停
- `任意状态 → rejected`：校验失败

### 2.13 表定义：execution_records（执行记录）

对应 PRD 对象：`ExecutionRecord`

| 字段                  | 类型          | 约束                          | 默认值       | 说明                                                                            |
| --------------------- | ------------- | ----------------------------- | ------------ | ------------------------------------------------------------------------------- |
| id                    | UUID          | PK                            | uuid4        |                                                                                 |
| order_intent_id       | UUID          | FK→order_intents.id, NOT NULL | -            |                                                                                 |
| user_id               | UUID          | FK→users.id, NOT NULL         | -            |                                                                                 |
| account_type          | VARCHAR(32)   | NOT NULL                      | 'simulation' |                                                                                 |
| fills                 | JSONB         | NOT NULL                      | '[]'         | `[{fill_price, fill_quantity, fill_time, fee, slippage, market_price_at_fill}]` |
| total_filled_quantity | NUMERIC(18,4) | NOT NULL                      | 0            |                                                                                 |
| total_fee             | NUMERIC(18,4) | NOT NULL                      | 0            |                                                                                 |
| total_slippage        | NUMERIC(18,4) | NOT NULL                      | 0            |                                                                                 |
| avg_fill_price        | NUMERIC(18,4) | NOT NULL                      | 0            |                                                                                 |
| status_history        | JSONB         | NOT NULL                      | '[]'         | `[{from_status, to_status, at, reason, actor}]`                                 |
| rejection_reason      | TEXT          | NULLABLE                      | -            |                                                                                 |
| cancel_reason         | TEXT          | NULLABLE                      | -            |                                                                                 |
| data_as_of            | TIMESTAMPTZ   | NOT NULL                      | -            | 使用的市场数据时点                                                              |
| fee_model             | VARCHAR(64)   | NOT NULL                      | 'flat'       | 费用模型名称                                                                    |
| slippage_model        | VARCHAR(64)   | NOT NULL                      | 'fixed_bps'  | 滑点模型名称                                                                    |
| status                | VARCHAR(32)   | NOT NULL                      | 'pending'    | 与 order_intent 状态同步                                                        |
| created_at            | TIMESTAMPTZ   | NOT NULL                      | now()        |                                                                                 |
| updated_at            | TIMESTAMPTZ   | NULLABLE                      | -            |                                                                                 |

### 2.14 表定义：risk_events（风险事件）

对应 PRD 对象：`RiskEvent`

| 字段                | 类型        | 约束                  | 默认值 | 说明                                                                                   |
| ------------------- | ----------- | --------------------- | ------ | -------------------------------------------------------------------------------------- |
| id                  | UUID        | PK                    | uuid4  |                                                                                        |
| user_id             | UUID        | FK→users.id, NOT NULL | -      |                                                                                        |
| rule_id             | VARCHAR(64) | NOT NULL              | -      | 触发的规则ID                                                                           |
| severity            | VARCHAR(32) | NOT NULL              | -      | critical / high / medium / low                                                         |
| category            | VARCHAR(32) | NOT NULL              | -      | authorization / user_state / fund_order / portfolio_risk / market_data / agent_runtime |
| description         | TEXT        | NOT NULL              | -      | 人可读的事件描述                                                                       |
| input_snapshot      | JSONB       | NOT NULL              | '{}'   | 触发时的输入快照                                                                       |
| affected_objects    | JSONB       | NOT NULL              | '[]'   | `[{type, id, version}]` — 受影响的对象                                                 |
| disposition         | VARCHAR(32) | NOT NULL              | 'open' | open / acknowledged / resolved / escalated                                             |
| resolution          | TEXT        | NULLABLE              | -      | 处置说明                                                                               |
| resolved_at         | TIMESTAMPTZ | NULLABLE              | -      |                                                                                        |
| resolved_by         | UUID        | NULLABLE              | -      | 操作人                                                                                 |
| recovery_conditions | JSONB       | NULLABLE              | -      | 恢复条件                                                                               |
| created_at          | TIMESTAMPTZ | NOT NULL              | now()  |                                                                                        |

**索引**：`(user_id, severity, created_at DESC)`

### 2.15 表定义：audit_events（审计事件）

对应 PRD 对象：`AuditEvent`

| 字段                   | 类型        | 约束                  | 默认值   | 说明                                                          |
| ---------------------- | ----------- | --------------------- | -------- | ------------------------------------------------------------- |
| id                     | UUID        | PK                    | uuid4    |                                                               |
| event_type             | VARCHAR(64) | NOT NULL              | -        | 事件类型（对应PRD 7.1的14个事件）                             |
| user_id                | UUID        | FK→users.id, NOT NULL | -        |                                                               |
| subject_type           | VARCHAR(64) | NOT NULL              | -        | 主体类型：profile/mandate/strategy/portfolio/order/risk_event |
| subject_id             | UUID        | NOT NULL              | -        | 主体ID                                                        |
| before_version         | INTEGER     | NULLABLE              | -        | 变更前版本                                                    |
| after_version          | INTEGER     | NULLABLE              | -        | 变更后版本                                                    |
| request_correlation_id | UUID        | NULLABLE              | -        | 请求关联ID（串联一次完整操作链）                              |
| payload                | JSONB       | NOT NULL              | '{}'     | 事件详情                                                      |
| actor                  | VARCHAR(64) | NOT NULL              | 'system' | user / system / agent_name                                    |
| ip_address             | VARCHAR(45) | NULLABLE              | -        |                                                               |
| created_at             | TIMESTAMPTZ | NOT NULL              | now()    |                                                               |

**索引**：`(subject_type, subject_id)`, `(request_correlation_id)`, `(user_id, created_at DESC)`

### 2.16 辅助表：consent_records（同意记录）

| 字段              | 类型        | 约束                  | 默认值 | 说明                                                             |
| ----------------- | ----------- | --------------------- | ------ | ---------------------------------------------------------------- |
| id                | UUID        | PK                    | uuid4  |                                                                  |
| user_id           | UUID        | FK→users.id, NOT NULL | -      |                                                                  |
| consent_type      | VARCHAR(64) | NOT NULL              | -      | behavioral_tracking / dialog_analysis / user_diary / device_data |
| granted           | BOOLEAN     | NOT NULL              | true   |                                                                  |
| scope_description | TEXT        | NOT NULL              | -      | 同意范围说明                                                     |
| granted_at        | TIMESTAMPTZ | NOT NULL              | now()  |                                                                  |
| revoked_at        | TIMESTAMPTZ | NULLABLE              | -      | 撤回时间                                                         |
| revoke_reason     | TEXT        | NULLABLE              | -      |                                                                  |
| created_at        | TIMESTAMPTZ | NOT NULL              | now()  |                                                                  |

**业务规则（BR-14）**：撤回同意后，对应数据不得用于新的推断或交易流程

### 2.17 辅助表：cooldown_periods（冷静期）

| 字段                      | 类型        | 约束                       | 默认值   | 说明                                                                           |
| ------------------------- | ----------- | -------------------------- | -------- | ------------------------------------------------------------------------------ |
| id                        | UUID        | PK                         | uuid4    |                                                                                |
| user_id                   | UUID        | FK→users.id, NOT NULL      | -        |                                                                                |
| trigger_state_snapshot_id | UUID        | FK→user_state_snapshots.id | -        | 触发时的状态快照                                                               |
| trigger_reason            | TEXT        | NOT NULL                   | -        | 触发原因                                                                       |
| cooldown_type             | VARCHAR(32) | NOT NULL                   | -        | anxiety / impulsivity / user_requested / risk_circuit_breaker                  |
| affected_scope            | JSONB       | NOT NULL                   | '{}'     | `{new_orders: false, strategy_generation: false, review_required: true}`       |
| recovery_conditions       | JSONB       | NOT NULL                   | '{}'     | `{user_confirmation: true, review_completed: false, waiting_period_hours: 24}` |
| status                    | VARCHAR(32) | NOT NULL                   | 'active' | active / resolved / expired                                                    |
| started_at                | TIMESTAMPTZ | NOT NULL                   | now()    |                                                                                |
| resolved_at               | TIMESTAMPTZ | NULLABLE                   | -        |                                                                                |
| resolved_by               | VARCHAR(64) | NULLABLE                   | -        | user_confirmation / review_completion / expiry                                 |
| created_at                | TIMESTAMPTZ | NOT NULL                   | now()    |                                                                                |

**业务规则（BR-15, RK-06）**：冷静期内新订单被暂停，但目标配置和授权保持不变

### 2.18 辅助表：simulated_accounts（仿真账户）

| 字段               | 类型          | 约束                          | 默认值   | 说明                                                                          |
| ------------------ | ------------- | ----------------------------- | -------- | ----------------------------------------------------------------------------- |
| id                 | UUID          | PK                            | uuid4    |                                                                               |
| user_id            | UUID          | FK→users.id, UNIQUE, NOT NULL | -        | 每用户一个仿真账户                                                            |
| cash_balance       | NUMERIC(18,4) | NOT NULL                      | 1000000  | 初始100万                                                                     |
| total_market_value | NUMERIC(18,4) | NOT NULL                      | 0        | 持仓市值                                                                      |
| total_value        | NUMERIC(18,4) | NOT NULL                      | 1000000  | 总资产                                                                        |
| positions          | JSONB         | NOT NULL                      | '[]'     | `[{instrument_id, symbol, quantity, avg_cost, market_value, unrealized_pnl}]` |
| total_fee_paid     | NUMERIC(18,4) | NOT NULL                      | 0        | 累计费用                                                                      |
| total_slippage     | NUMERIC(18,4) | NOT NULL                      | 0        | 累计滑点                                                                      |
| status             | VARCHAR(32)   | NOT NULL                      | 'active' | active / paused / closed                                                      |
| created_at         | TIMESTAMPTZ   | NOT NULL                      | now()    |                                                                               |
| updated_at         | TIMESTAMPTZ   | NULLABLE                      | -        |                                                                               |

---

## 三、API 完整规格

### 3.1 统一响应格式

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-23T10:00:00Z"
  }
}
```

分页响应：

```json
{
  "success": true,
  "data": { "items": [...], "total": 100, "page": 1, "page_size": 20 }
}
```

错误响应：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "MANDATE_NOT_ACTIVE",
    "message": "当前无有效授权书",
    "details": {
      "mandate_status": "draft",
      "required_action": "activate_mandate"
    }
  }
}
```

### 3.2 POST /v1/profiles — 保存画像

**请求**：

```json
{
  "base_currency": "CNY",
  "region": "CN",
  "goals": [
    {
      "name": "退休储备",
      "target_amount": 2000000,
      "target_date": "2055-01-01",
      "priority": 1
    },
    {
      "name": "子女教育",
      "target_amount": 500000,
      "target_date": "2040-09-01",
      "priority": 2
    }
  ],
  "financial_constraints": {
    "investable_amount": 500000,
    "emergency_fund": 100000,
    "near_term_cash_needs": 50000,
    "major_liabilities": {
      "mortgage_remaining": 1200000,
      "monthly_payment": 8000
    }
  },
  "stated_risk": {
    "loss_tolerance": 0.15,
    "volatility_tolerance": 0.2,
    "experience_years": 3,
    "preference": "moderate"
  },
  "behavioral_prefs": {
    "review_frequency": "monthly",
    "drawdown_reaction": "concerned_but_hold",
    "autonomy_preference": "guided",
    "info_preference": "summary"
  },
  "restrictions": {
    "regions": ["CN", "US"],
    "product_exclusions": ["leveraged_etf", "crypto"],
    "concentration_limits": { "max_single_asset": 0.1 },
    "esg_preference": null,
    "compliance_restrictions": []
  }
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "version": 1,
    "completeness": 0.80,
    "confidence": 0.65,
    "status": "draft",
    "goals": [ ... ],
    "missing_fields": ["revealed_risk"],
    "conflict_warnings": [],
    "next_actions": ["confirm_profile", "add_behavioral_data"]
  }
}
```

### 3.3 POST /v1/user-states/confirmations — 确认心智状态

**请求**：

```json
{
  "state_snapshot_id": "uuid",
  "action": "confirm",
  "feedback": null
}
```

action 可选：`confirm` / `correct` / `reject`
当 action=correct 时，feedback 必填。

**响应**：

```json
{
  "success": true,
  "data": {
    "state_snapshot_id": "uuid",
    "user_confirmation": "confirmed",
    "cooldown_triggered": false,
    "affected_scope": null
  }
}
```

### 3.4 POST /v1/mandates — 创建/激活授权书

**请求**：

```json
{
  "profile_version": 1,
  "action": "activate",
  "goal_priorities": [{ "goal_name": "退休储备", "priority_rank": 1 }],
  "risk_budget": {
    "max_drawdown": 0.2,
    "volatility_cap": 0.18,
    "loss_tolerance_annual": 0.15
  },
  "cash_boundary": {
    "min_cash_ratio": 0.05,
    "emergency_reserve": 100000,
    "near_term_reserve": 50000
  },
  "asset_scope": {
    "allowed_asset_types": ["etf", "mutual_fund"],
    "allowed_markets": ["a_shares", "us_stocks"],
    "excluded_instruments": [],
    "excluded_sectors": []
  },
  "concentration_limits": {
    "max_single_asset": 0.1,
    "max_sector": 0.3,
    "max_region": 0.6
  },
  "rebalance_frequency": "quarterly",
  "rebalance_threshold": 0.05,
  "autonomy_level": "L2",
  "max_single_order_amount": 100000,
  "valid_until": null
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "version": 1,
    "status": "active",
    "autonomy_level": "L2",
    "valid_from": "2026-07-23T10:00:00Z",
    "profile_version": 1,
    "risk_budget": { ... },
    "warnings": []
  }
}
```

### 3.5 POST /v1/holdings/imports — 导入持仓

**请求**：`multipart/form-data`，字段 `file`（CSV文件）

**响应**：

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "version": 1,
    "positions": [
      {
        "symbol": "510300.SH",
        "name": "沪深300ETF",
        "quantity": 1000,
        "avg_cost": 4.2,
        "market_value": 4350,
        "resolved": true
      }
    ],
    "unresolved_positions": [
      {
        "raw_name": "华夏回报混合A",
        "raw_symbol": null,
        "quantity": 5000,
        "estimated_value": 6200,
        "match_candidates": [
          { "symbol": "002001.OF", "name": "华夏回报混合A", "confidence": 0.95 }
        ]
      }
    ],
    "unresolved_weight": 0.08,
    "total_market_value": 560000,
    "valuation_as_of": "2026-07-23T00:00:00Z"
  }
}
```

### 3.6 POST /v1/research-runs — 创建研究任务

**请求**：

```json
{
  "instrument_ids": ["uuid1", "uuid2"],
  "force_refresh": false
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "task_id": "uuid",
    "status": "in_progress",
    "instruments": [
      {
        "instrument_id": "uuid1",
        "symbol": "510300.SH",
        "status": "in_progress"
      }
    ],
    "estimated_completion_seconds": 30
  }
}
```

### 3.7 POST /v1/strategy-proposals — 生成策略

**请求**：

```json
{
  "mandate_id": "uuid",
  "force_new_market_context": false
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "version": 1,
    "status": "candidate",
    "global_allocation": {
      "cash_ratio": 0.1,
      "equity_ratio": 0.6,
      "bond_ratio": 0.3
    },
    "market_allocation": {
      "a_shares": { "weight": 0.4 },
      "us_stocks": { "weight": 0.2 }
    },
    "risk_scenarios": [
      {
        "scenario_name": "基准",
        "expected_return": 0.08,
        "expected_volatility": 0.12,
        "max_drawdown": -0.15,
        "probability": 0.5
      },
      {
        "scenario_name": "乐观",
        "expected_return": 0.15,
        "expected_volatility": 0.14,
        "max_drawdown": -0.1,
        "probability": 0.25
      },
      {
        "scenario_name": "悲观",
        "expected_return": -0.05,
        "expected_volatility": 0.18,
        "max_drawdown": -0.25,
        "probability": 0.25
      }
    ],
    "assumptions": ["市场情绪中性", "无重大政策变化"],
    "mental_adaptations": {
      "adaptations_applied": [],
      "explanation": "当前心智状态正常，无额外调整"
    },
    "explanation": "基于您的风险偏好（中等）和目标期限（29年），建议60%权益+30%债券+10%现金的配置..."
  }
}
```

### 3.8 POST /v1/target-portfolios — 生成目标组合

**请求**：

```json
{
  "strategy_proposal_id": "uuid"
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "version": 1,
    "constructible": true,
    "target_weights": [
      {
        "instrument_id": "uuid",
        "symbol": "510300.SH",
        "weight": 0.25,
        "target_value": 140000,
        "current_weight": 0.2,
        "delta": 0.05
      },
      {
        "instrument_id": "uuid",
        "symbol": "510500.SH",
        "weight": 0.15,
        "target_value": 84000,
        "current_weight": 0.1,
        "delta": 0.05
      },
      {
        "instrument_id": "uuid",
        "symbol": "511010.SH",
        "weight": 0.3,
        "target_value": 168000,
        "current_weight": 0.35,
        "delta": -0.05
      }
    ],
    "constraint_report": {
      "passed": [
        {
          "rule": "max_single_asset",
          "value": 0.25,
          "limit": 0.1,
          "note": "需调仓后满足"
        }
      ],
      "failed": [],
      "warnings": [
        {
          "rule": "sector_concentration",
          "value": 0.28,
          "limit": 0.3,
          "note": "接近上限"
        }
      ]
    },
    "risk_metrics": {
      "expected_return": 0.082,
      "expected_volatility": 0.118,
      "sharpe_ratio": 0.69,
      "max_drawdown": -0.148,
      "var_95": -0.019
    },
    "rebalance_plan": [
      {
        "instrument_id": "uuid",
        "symbol": "510300.SH",
        "action": "buy",
        "quantity": 6500,
        "estimated_value": 28000,
        "priority": 1,
        "reason": "增加沪深300配置至目标权重"
      }
    ],
    "total_expected_cost": 42.5,
    "total_expected_slippage": 85.0,
    "data_coverage": 0.95,
    "explanation": "本次调仓主要增加沪深300ETF配置..."
  }
}
```

### 3.9 POST /v1/order-intents — 创建订单意图

**请求**：

```json
{
  "portfolio_id": "uuid",
  "rebalance_plan_item_index": 0
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "idempotency_key": "uuid",
    "symbol": "510300.SH",
    "direction": "buy",
    "quantity": 6500,
    "status": "approved",
    "risk_check_1": {
      "passed": true,
      "checks": [
        { "rule": "asset_scope", "passed": true },
        { "rule": "concentration", "passed": true }
      ]
    },
    "risk_check_2": {
      "passed": true,
      "checks": [
        { "rule": "mandate_active", "passed": true },
        { "rule": "autonomy_level", "passed": true },
        { "rule": "no_cooldown", "passed": true }
      ]
    },
    "mandate_version": 1,
    "expires_at": "2026-07-23T18:00:00Z"
  }
}
```

### 3.10 POST /v1/simulated-orders — 提交仿真订单

**请求**：

```json
{
  "order_intent_id": "uuid"
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "execution_id": "uuid",
    "order_intent_id": "uuid",
    "status": "submitted",
    "risk_check_3": {
      "passed": true,
      "checks": [
        { "rule": "cash_sufficient", "passed": true },
        { "rule": "price_protection", "passed": true },
        { "rule": "market_available", "passed": true }
      ]
    }
  }
}
```

### 3.11 POST /v1/strategies/pause — 暂停策略

**请求**：

```json
{
  "scope": "all",
  "reason": "用户主动暂停"
}
```

scope 可选：`all` / `{ strategy_id: "uuid" }` / `{ order_ids: ["uuid"] }`

### 3.12 POST /v1/reviews — 创建/完成复盘

**请求**：

```json
{
  "type": "periodic",
  "period": "2026-07"
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "type": "periodic",
    "period": "2026-07",
    "profile_changes": { "version_from": 1, "version_to": 2, "changes": [...] },
    "portfolio_deviation": { "current_vs_target_deviation": 0.035, "largest_deviations": [...] },
    "strategy_performance": { "return_actual": 0.023, "return_expected": 0.020, "tracking_error": 0.003 },
    "execution_quality": { "avg_slippage_bps": 4.2, "fill_rate": 0.98 },
    "risk_events_summary": { "total": 2, "critical": 0, "resolved": 2 },
    "mental_state_trend": { "anxiety_trend": "stable", "confidence_trend": "improving" },
    "recommendations": ["建议保持当前配置", "下月关注美联储利率决议影响"],
    "actions_required": []
  }
}
```

### 3.13 补充查询接口

| 端点                   | 方法 | 关键参数                                        | 响应关键字段                |
| ---------------------- | ---- | ----------------------------------------------- | --------------------------- |
| `/v1/profiles/me`      | GET  | -                                               | 最新confirmed版本的完整画像 |
| `/v1/mandates/active`  | GET  | -                                               | 当前active授权书            |
| `/v1/holdings/current` | GET  | -                                               | 最新持仓快照                |
| `/v1/instruments`      | GET  | `?market=a_shares&asset_type=etf&status=active` | 资产池列表                  |
| `/v1/agents/status`    | GET  | -                                               | 8个Agent状态卡              |
| `/v1/orders`           | GET  | `?status=pending&page=1&page_size=20`           | 订单分页列表                |
| `/v1/audit-events`     | GET  | `?subject_type=order&subject_id=uuid&page=1`    | 审计日志                    |
| `/v1/risk-events`      | GET  | `?severity=critical&status=open`                | 风险事件                    |
| `/v1/reviews`          | GET  | `?period=2026-07`                               | 复盘记录                    |

---

## 四、Agent 系统设计

### 4.1 LangGraph 全局状态定义

```python
from typing import TypedDict, Optional, Literal

class AgentGraphState(TypedDict):
    # 请求信息
    request_id: str
    user_id: str

    # 用户输入
    profile_version: int
    mandate_version: int
    holding_snapshot_version: int

    # Agent 1: 用户状态
    user_state_snapshot_id: Optional[str]
    mental_state: Optional[dict]          # {anxiety_level, greed_level, ...}
    cognitive_biases: Optional[list]
    cooldown_active: bool
    cooldown_id: Optional[str]

    # Agent 2: 市场环境
    market_context_id: Optional[str]
    market_usable: bool
    overall_sentiment: Optional[float]
    market_events: Optional[list]

    # Agent 3: 研究
    research_memo_ids: Optional[list]
    research_status: Optional[str]        # usable / insufficient / failed

    # Agent 4: 策略
    strategy_proposal_id: Optional[str]
    global_allocation: Optional[dict]
    market_allocation: Optional[dict]
    strategy_status: Optional[str]

    # Agent 5: 组合
    target_portfolio_id: Optional[str]
    target_weights: Optional[list]
    constraint_report: Optional[dict]
    rebalance_plan: Optional[list]
    constructible: bool

    # Agent 6: 执行
    order_intent_ids: Optional[list]
    execution_record_ids: Optional[list]

    # Agent 7: 风控
    risk_check_1_result: Optional[dict]
    risk_check_2_result: Optional[dict]
    risk_check_3_result: Optional[dict]
    risk_events: Optional[list]

    # 编排
    pipeline_status: Literal["running", "paused", "blocked", "completed", "failed"]
    blocked_by: Optional[str]
    error_message: Optional[str]
    trace_versions: dict                   # 全链路版本追溯
```

### 4.2 编排图（LangGraph StateGraph）

```
start_node
  → pre_check (校验画像/授权/持仓是否就绪)
  → parallel_fanout:
      → user_state_agent (并行)
      → market_agent (并行)
      → research_agent (并行)
  → merge_node (合并并行结果)
  → mental_state_gate (心智状态检查：冷静期→暂停)
  → strategy_agent
  → portfolio_agent
  → risk_check_1 (组合生成阶段风控)
  → execution_agent
  → risk_check_2 (订单创建阶段风控)
  → sim_submit
  → risk_check_3 (订单提交阶段风控)
  → end_node
```

**条件边（conditional edges）**：

- `pre_check` → 不满足前置条件 → `end_node`（pipeline_status=failed）
- `mental_state_gate` → cooldown_active=True → `end_node`（pipeline_status=paused）
- `risk_check_1/2/3` → 硬约束失败 → `end_node`（pipeline_status=blocked）
- `research_agent` → status=insufficient → `end_node`（pipeline_status=failed）

### 4.3 各 Agent 基础版实现详情

#### Agent 1: 用户状态 Agent

```python
class UserStateAgent:
    """规则引擎：基于行为信号判定心智状态"""

    def run(self, state: AgentGraphState) -> dict:
        # 1. 获取最近的行为信号（已同意范围内）
        # 2. 计算 anxiety_level = weighted_avg(最近7天行为指标)
        # 3. 计算 greed_level = weighted_avg(交易频率变化、追涨行为)
        # 4. 检测认知偏差（5类）
        # 5. 判定是否需要冷静期

        ANXIETY_THRESHOLD = 0.7  # 高于此触发冷静期
        GREED_THRESHOLD = 0.7
        IMPULSIVITY_THRESHOLD = 0.8

        # 输出：mental_state, cognitive_biases, cooldown_active
```

**认知偏差检测器**（基础版规则）：

| 偏差类型 | 检测信号                           | 基础版规则                                      |
| -------- | ---------------------------------- | ----------------------------------------------- |
| 损失厌恶 | 亏损持仓长期不卖、盈利持仓过早卖出 | 亏损持仓平均持有天数 / 盈利持仓平均持有天数 > 3 |
| 过度自信 | 交易频率异常高、单笔金额递增       | 月交易次数 > 20 且 金额趋势递增                 |
| 从众行为 | 跟随热门资产买入                   | 买入时间与热门资产涨幅高度相关                  |
| 锚定效应 | 以买入价作为决策锚点               | 卖出决策与买入价偏离度强相关                    |
| 处置效应 | 过早止盈过晚止损                   | 盈利卖出时间 < 亏损卖出时间                     |

#### Agent 2: 市场环境 Agent

```python
class MarketAgent:
    """AKShare/yfinance + 规则情绪评分 + LLM摘要"""

    def run(self, state: AgentGraphState) -> dict:
        # 1. 调用 AKShare 获取 A 股指数数据（沪深300、中证500等）
        # 2. 调用 yfinance 获取美股/港股 ETF 数据
        # 3. 计算情绪分数：
        #    - 5日涨跌幅 → 短期情绪
        #    - 20日波动率 → 市场稳定性
        #    - 成交量变化 → 市场活跃度
        # 4. 加权综合 → overall_sentiment
        # 5. LLM 生成事件摘要（最近新闻）
        # 6. 评估数据质量和可用状态
```

#### Agent 3: 研究 Agent

```python
class ResearchAgent:
    """LLM 生成 + 结构化校验"""

    def run(self, state: AgentGraphState) -> dict:
        # 1. 对每个目标资产，调用 LLM 生成研究备忘
        # 2. 强制结构化：facts/inferences/bull_case/bear_case/risks/unknowns
        # 3. 校验规则：
        #    - facts 必须非空
        #    - bear_case.thesis 必须非空（BR-06）
        #    - risks 必须非空
        #    - 每个 fact 必须有 source
        # 4. 不通过 → status = insufficient

    SYSTEM_PROMPT = """你是一位专业的ETF/基金研究分析师。
    请对以下资产进行结构化研究分析，输出必须包含：
    1. 事实（facts）：每条必须有来源
    2. 推断（inferences）：标注模型或规则来源
    3. 看多理由（bull_case）
    4. 看空理由（bear_case）— 必须提供
    5. 风险（risks）
    6. 未知项（unknowns）— 明确说明还不知道什么"""
```

#### Agent 4: 策略 Agent

```python
class StrategyAgent:
    """规则引擎（授权书约束映射）+ LLM 解释"""

    def run(self, state: AgentGraphState) -> dict:
        # 1. 读取授权书约束
        # 2. 基于风险预算计算大类资产配比：
        #    - max_drawdown ≤ 0.10 → 保守（股票≤30%）
        #    - max_drawdown ≤ 0.20 → 稳健（股票≤60%）
        #    - max_drawdown > 0.20 → 积极（股票≤80%）
        # 3. 基于市场情绪微调（±5%，不突破约束）
        # 4. 生成 risk_scenarios（基准/乐观/悲观）
        # 5. LLM 生成解释文本
```

#### Agent 5: 组合 Agent

```python
class PortfolioAgent:
    """规则权重分配 + 约束校验"""

    def run(self, state: AgentGraphState) -> dict:
        # 1. 将大类配比映射到具体 ETF
        # 2. 考虑当前持仓，计算 delta
        # 3. 生成 rebalance_plan（最小必要调仓）
        # 4. 运行约束校验：
        #    - max_single_asset ≤ 授权书限制
        #    - max_sector ≤ 授权书限制
        #    - cash_ratio ≥ min_cash_ratio
        #    - unresolved_weight ≤ 阈值
        # 5. 任一硬约束不满足 → constructible = false
        # 6. 计算 risk_metrics（简化版：加权平均）
```

#### Agent 6: 执行 Agent

```python
class ExecutionAgent:
    """订单意图生成 + 仿真状态机"""

    def run(self, state: AgentGraphState) -> dict:
        # 1. 根据 rebalance_plan 生成 order_intents
        # 2. 每个 intent 设置幂等键
        # 3. 仿真提交：
        #    - 获取最新收盘价
        #    - 应用费用模型：flat_fee = max(5, quantity * price * 0.0003)
        #    - 应用滑点模型：slippage = price * 0.0005 (5bps)
        #    - 更新 simulated_account
        # 4. 记录执行状态历史
```

#### Agent 7: 风控 Agent

```python
class RiskAgent:
    """三段规则引擎（20+条规则）"""

    def check_stage_1(self, state) -> dict:
        """组合生成阶段校验"""
        # 见下方风控规则表

    def check_stage_2(self, state) -> dict:
        """订单创建阶段校验"""

    def check_stage_3(self, state) -> dict:
        """订单提交阶段校验"""
```

### 4.4 风控三段校验完整规则

#### 阶段一：组合生成校验（portfolio_agent 调用 risk_agent.check_stage_1）

| 规则ID | 规则名       | 类型   | 检查逻辑                                                                                         | 失败处置 |
| ------ | ------------ | ------ | ------------------------------------------------------------------------------------------------ | -------- |
| R1-01  | 授权有效性   | 硬约束 | mandate.status == 'active' AND now() BETWEEN valid_from AND valid_until                          | 阻断     |
| R1-02  | 画像最低门槛 | 硬约束 | profile.completeness ≥ 0.6 AND profile.status == 'confirmed'                                     | 阻断     |
| R1-03  | 资产范围     | 硬约束 | 所有 target_weights 中的 instrument 在 asset_scope.allowed_asset_types 和 allowed_markets 范围内 | 阻断     |
| R1-04  | 集中度上限   | 硬约束 | 每个 asset.weight ≤ concentration_limits.max_single_asset                                        | 阻断     |
| R1-05  | 现金边界     | 硬约束 | cash_ratio ≥ cash_boundary.min_cash_ratio                                                        | 阻断     |
| R1-06  | 未解析持仓   | 硬约束 | holding.unresolved_weight ≤ 0.15（可配置）                                                       | 阻断     |
| R1-07  | 行业集中     | 软阈值 | sector_weight ≤ max_sector × 0.9                                                                 | 告警     |
| R1-08  | 目标偏离     | 软阈值 | 任一 asset 的 delta > 0.10                                                                       | 告警     |

#### 阶段二：订单创建校验（execution_agent 调用 risk_agent.check_stage_2）

| 规则ID | 规则名     | 类型   | 检查逻辑                                            | 失败处置  |
| ------ | ---------- | ------ | --------------------------------------------------- | --------- |
| R2-01  | 授权仍有效 | 硬约束 | 再次检查 mandate.status 和有效期                    | 阻断      |
| R2-02  | 自主级别   | 硬约束 | L0→不允许创建订单；L1→需用户确认；L2/L3→允许        | 阻断      |
| R2-03  | 冷静期     | 硬约束 | 无 active cooldown_periods                          | 阻断      |
| R2-04  | 用户未暂停 | 硬约束 | 无 active strategy_pause                            | 阻断      |
| R2-05  | 单笔限额   | 软阈值 | quantity × price ≤ max_single_order_amount          | 告警+暂停 |
| R2-06  | 幂等检查   | 硬约束 | idempotency_key 不存在重复的 pending/submitted 订单 | 阻断      |

#### 阶段三：订单提交校验（sim_submit 调用 risk_agent.check_stage_3）

| 规则ID | 规则名     | 类型   | 检查逻辑                                                               | 失败处置 |
| ------ | ---------- | ------ | ---------------------------------------------------------------------- | -------- |
| R3-01  | 现金充足   | 硬约束 | simulated_account.cash_balance ≥ quantity × price + estimated_fee      | 阻断     |
| R3-02  | 价格保护   | 硬约束 | abs(current_price - reference_price) / reference_price ≤ max_deviation | 阻断     |
| R3-03  | 市场可用   | 硬约束 | market_context.usable_status == 'usable' AND data_as_of 未过期         | 阻断     |
| R3-04  | 用户未暂停 | 硬约束 | 再次检查暂停状态                                                       | 阻断     |
| R3-05  | 重复订单   | 软阈值 | 同一 instrument + direction 在24h内无类似订单                          | 告警     |
| R3-06  | 滑点异常   | 软阈值 | estimated_slippage ≤ 正常范围 × 2                                      | 告警     |

---

## 五、前端页面详细设计

### 5.1 全局布局

```
┌─────────────────────────────────────────────────┐
│ 顶栏：Logo | 用户头像 | 通知铃铛(待确认数) | 设置   │
├────────┬────────────────────────────────────────┤
│        │                                         │
│ 侧导航  │           主内容区                      │
│        │                                         │
│ ·首页   │  ┌─────────────────────────────────┐    │
│ ·认识我  │  │ 面包屑导航                       │    │
│ ·我的授权│  │                                   │    │
│ ·我的组合│  │                                   │    │
│ ·Agent  │  │                                   │    │
│ ·交易   │  │                                   │    │
│ ·复盘   │  │                                   │    │
│        │  └─────────────────────────────────┘    │
└────────┴─────────────────────────────────────────┘
```

**侧导航组件**：Ant Design `<Menu>` 组件，模式 `inline`
**顶栏**：Ant Design `<Layout.Header>`
**响应式**：侧导航在 <768px 时折叠为底部 Tab Bar

### 5.2 页面 P0-1：建档向导（Profile/OnboardingWizard）

**路径**：`/profile/onboarding`

**交互流程**：

```
Step 1: 基础信息（本位币、地区）
  → Step 2: 投资目标（可添加多个，每个含名称/金额/日期/优先级）
  → Step 3: 财务状况（可投资金额/应急资金/现金需求/负债）
  → Step 4: 风险偏好（损失容忍度滑块/波动容忍度/投资经验/偏好标签）
  → Step 5: 行为偏好（复盘频率/回撤反应/自主偏好/信息偏好）
  → Step 6: 限制条件（地区/产品禁忌/集中度/ESG）
  → Step 7: 预览与确认
```

**组件规格**：

| 组件       | Ant Design 组件          | 配置                                    |
| ---------- | ------------------------ | --------------------------------------- |
| 步骤条     | `<Steps>`                | current={step}, size="small", 顶部固定  |
| 本位币选择 | `<Select>`               | options: CNY/USD/HKD, 默认CNY           |
| 目标列表   | `<Form.List>` + `<Card>` | 动态添加/删除，每个含4个字段            |
| 金额输入   | `<InputNumber>`          | formatter: 千分位, min=0                |
| 日期选择   | `<DatePicker>`           | picker="year" 或具体日期                |
| 风险滑块   | `<Slider>`               | 0~100%, marks: [0, 5, 10, 20, 50]       |
| 偏好选择   | `<Radio.Group>`          | 预设选项                                |
| 完成度指示 | `<Progress>`             | percent={completeness}, status="active" |
| 预览       | `<Descriptions>`         | 全部字段展示，可跳转修改                |

**实时完整度计算**：前端同步计算并显示在步骤条右侧
**验证规则**：Step 7 之前，`goals` 至少1个、`base_currency` 必填、`near_term_cash_needs` 必填

### 5.3 页面 P0-2：画像详情（Profile/Detail）

**路径**：`/profile`

**布局**：

```
┌──────────────────────────────────────────────┐
│ 画像概览卡                                     │
│ 版本号: v1 | 完整度: 80% | 置信度: 65% | 状态:已确认│
├──────────────────────────────────────────────┤
│ ┌────────────┐ ┌────────────┐ ┌────────────┐ │
│ │ 目标维度    │ │ 财务约束    │ │ 陈述风险    │ │
│ │ 来源:用户输入│ │ 来源:用户输入│ │ 来源:问卷   │ │
│ │ 置信度:高   │ │ 置信度:高   │ │ 置信度:中   │ │
│ │ [确认][修正] │ │ [确认][修正] │ │ [确认][修正] │ │
│ └────────────┘ └────────────┘ └────────────┘ │
│ ┌────────────┐ ┌────────────┐ ┌────────────┐ │
│ │ 行为揭示风险│ │ 行为偏好    │ │ 限制条件    │ │
│ │ 来源:行为数据│ │ 来源:用户输入│ │ 来源:用户输入│ │
│ │ 置信度:低   │ │ 置信度:高   │ │ 置信度:高   │ │
│ │ [确认][修正] │ │ [确认][修正] │ │ [确认][修正] │ │
│ └────────────┘ └────────────┘ └────────────┘ │
├──────────────────────────────────────────────┤
│ 冲突警告（如有）                                │
│ ⚠️ 陈述风险偏好"积极"但现金需求紧张，系统采用审慎边界│
├──────────────────────────────────────────────┤
│ 心智状态卡（独立区域）                           │
│ 焦虑:低 | 贪婪:低 | 冲动:低 | 有效期:还剩18h    │
│ [确认状态] [修正] [拒绝]                        │
│ 认知偏差提示：无                                │
└──────────────────────────────────────────────┘
```

**关键组件**：

| 组件               | 说明                                                         |
| ------------------ | ------------------------------------------------------------ |
| `ConfidenceBadge`  | 置信度可视化：≥0.8 绿色"高"、0.5~0.8 橙色"中"、<0.5 红色"低" |
| `VersionTag`       | `<Tag>v1 · 2026-07-23 10:00</Tag>`                           |
| `DimensionCard`    | 每个画像维度的卡片，含值展示、来源、置信度、操作按钮         |
| `ConflictAlert`    | `<Alert type="warning">` 展示维度间冲突                      |
| `MentalStatePanel` | 心智状态面板，含情绪仪表盘和认知偏差列表                     |
| `CorrectionDrawer` | `<Drawer>` 修正表单，提交后生成新版本                        |

### 5.4 页面 P0-3：授权书（Mandate/Index）

**路径**：`/mandate`

**布局**：

```
┌──────────────────────────────────────────────┐
│ 当前授权书 v1 | 状态:生效中 | 自主级别:L2       │
│ 生效时间: 2026-07-23 | 有效期至: 永久           │
├──────────────────────────────────────────────┤
│ ┌─ 目标优先级 ──────────────────────────────┐ │
│ │ 1. 退休储备 (优先级: 1)                     │ │
│ │ 2. 子女教育 (优先级: 2)                     │ │
│ └──────────────────────────────────────────┘ │
│ ┌─ 风险预算 ────────────────────────────────┐ │
│ │ 最大回撤: 20% | 波动上限: 18% | 年亏损容忍: 15%│ │
│ └──────────────────────────────────────────┘ │
│ ┌─ 资产范围 ────────────────────────────────┐ │
│ │ 类型: ETF, 公募基金 | 市场: A股, 美股       │ │
│ └──────────────────────────────────────────┘ │
│ ┌─ 集中度限制 ──────────────────────────────┐ │
│ │ 单资产: ≤10% | 行业: ≤30% | 地区: ≤60%    │ │
│ └──────────────────────────────────────────┘ │
│ ┌─ 自主级别 ────────────────────────────────┐ │
│ │ ○ L0 观察  ○ L1 建议  ● L2 仿真  ○ L3 实盘│ │
│ │ [修改级别]（需重新确认）                      │ │
│ └──────────────────────────────────────────┘ │
├──────────────────────────────────────────────┤
│ [暂停授权] [撤销授权] [创建新版本]              │
└──────────────────────────────────────────────┘
```

**自主级别选择器**：`<Radio.Group>` + 每个级别的说明卡片
**操作确认**：暂停/撤销使用 `<Modal>` 二次确认，说明影响范围
**版本历史**：底部 `<Timeline>` 展示历史版本变更

### 5.5 页面 P0-4：持仓导入（Portfolio/HoldingImport）

**路径**：`/portfolio/holdings/import`

**交互流程**：

```
1. 上传区域：<Dragger> 拖拽上传 CSV
2. 解析中：显示 <Spin> + "正在解析持仓..."
3. 预览表格：<Table> 展示解析结果
   - 已解析行：绿色行背景
   - 未解析行：红色行背景 + "手动匹配" 按钮
4. 未解析项处理：<Modal> 中搜索/选择匹配资产
5. 确认导入：<Button> "保存持仓快照"
```

**CSV 模板**：

```csv
资产名称,代码,数量,成本价,买入日期
沪深300ETF,510300,1000,4.20,2025-01-15
中证500ETF,510500,800,5.80,2025-03-20
```

**解析结果表格列**：

| 列名     | 组件        | 说明                                         |
| -------- | ----------- | -------------------------------------------- |
| 资产名称 | Text        | 原始名称或匹配后名称                         |
| 代码     | Tag         | 匹配后代码，未匹配显示红色"未识别"           |
| 数量     | InputNumber | 可修正                                       |
| 成本价   | InputNumber | 可修正                                       |
| 市值     | Text        | 系统计算                                     |
| 状态     | Badge       | 已匹配(green) / 待匹配(red) / 多候选(orange) |
| 操作     | Button      | 手动匹配 / 跳过                              |

### 5.6 页面 P0-5：目标组合（Portfolio/Target）

**路径**：`/portfolio/target`

**布局**：

```
┌──────────────────────────────────────────────┐
│ 目标组合 v1 | 策略: 稳健增长 | 计算时间: 10:30   │
│ 可构造: ✅ | 数据覆盖率: 95%                     │
├──────────────────────────────────────────────┤
│ ┌─ 目标权重 ───────────────────────────────┐  │
│ │ 饼图（ECharts / AntV）                    │  │
│ │ 沪深300ETF 25% | 中证500ETF 15% | ...    │  │
│ └──────────────────────────────────────────┘  │
│ ┌─ 约束报告 ──────────────────────────────┐   │
│ │ ✅ 资产范围：全部通过                      │   │
│ │ ✅ 集中度：全部满足                        │   │
│ │ ⚠️ 行业集中度：科技28%，接近30%上限        │   │
│ │ ✅ 现金比例：10% ≥ 5%                     │   │
│ └──────────────────────────────────────────┘  │
│ ┌─ 风险指标 ──────────────────────────────┐   │
│ │ 预期收益: 8.2% | 波动率: 11.8%            │   │
│ │ 夏普比率: 0.69 | 最大回撤: -14.8%         │   │
│ │ VaR(95%): -1.9%                           │   │
│ └──────────────────────────────────────────┘  │
│ ┌─ 风险情景 ──────────────────────────────┐   │
│ │ 基准(50%): +8.0%, 回撤-15%               │   │
│ │ 乐观(25%): +15.0%, 回撤-10%              │   │
│ │ 悲观(25%): -5.0%, 回撤-25%               │   │
│ └──────────────────────────────────────────┘  │
│ ┌─ 调仓计划 ──────────────────────────────┐   │
│ │ #1 买入 510300 6500股 ≈¥28,000  优先级:1  │   │
│ │ #2 买入 510500 3200股 ≈¥18,500  优先级:2  │   │
│ │ #3 卖出 511010 1500份 ≈¥16,800  优先级:1  │   │
│ │ 预估费用: ¥42.5 | 预估滑点: ¥85           │   │
│ │ [执行调仓]                                 │   │
│ └──────────────────────────────────────────┘  │
│ ┌─ 版本追溯 ──────────────────────────────┐   │
│ │ 画像v1 → 授权v1 → 策略v1 → 市场ctx-v3    │   │
│ └──────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

**关键组件**：

- `AllocationPieChart`：基于 AntV G2 或 ECharts 的饼图/环形图
- `ConstraintReport`：约束满足/违反列表，通过=绿色 ✅，失败=红色 ❌，告警=橙色 ⚠️
- `RiskScenarioTable`：三行情景表
- `RebalancePlanTable`：调仓计划表，含"执行调仓"按钮
- `VersionTraceChain`：`<Tag>` 链式展示版本追溯
- `ExplanationPanel`：可折叠的 AI 解释面板

### 5.7 页面 P0-6：仿真交易（Trading/Simulation）

**路径**：`/trading`

**布局**：

```
┌──────────────────────────────────────────────┐
│ 仿真账户                                      │
│ 总资产: ¥1,056,000 | 持仓: ¥556,000 | 现金: ¥500,000│
│ 累计费用: ¥125.5 | 累计滑点: ¥210.0             │
│ ⚠️ 仿真数据，非实际收益                         │
├──────────────────────────────────────────────┤
│ ┌─ 当前持仓 ──────────────────────────────┐   │
│ │ Table: 代码|名称|数量|成本|现价|盈亏|权重  │   │
│ └──────────────────────────────────────────┘  │
│ ┌─ 订单列表 ──────────────────────────────┐   │
│ │ Tabs: 全部|待审批|已提交|已成交|已拒绝     │   │
│ │ Table: 时间|代码|方向|数量|价格|状态|操作  │   │
│ │ [查看详情] → 订单详情抽屉                   │   │
│ └──────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

**订单详情抽屉**：

```
┌─ 订单详情 ──────────────────────┐
│ 订单ID: abc123                  │
│ 510300.SH 买入 6500股           │
│                                 │
│ 状态时间线:                      │
│ ● 创建 (10:30:00)              │
│ ● 审批通过 (10:30:01)           │
│ ● 入队 (10:30:02)              │
│ ● 提交 (10:30:05)              │
│ ● 成交 (10:30:06)              │
│                                 │
│ 成交详情:                        │
│ 成交价: 4.32 | 数量: 6500       │
│ 费用: ¥8.42 | 滑点: ¥14.30    │
│ 数据时点: 2026-07-23 10:30     │
│ 费用模型: flat | 滑点模型: fixed_bps│
│                                 │
│ 风控记录:                        │
│ ✅ 阶段1: 资产范围通过           │
│ ✅ 阶段2: 授权有效，级别匹配     │
│ ✅ 阶段3: 现金充足，价格正常    │
│                                 │
│ 版本追溯:                        │
│ 授权v1 → 策略v1 → 组合v1       │
└─────────────────────────────────┘
```

### 5.8 页面 P0-7：首页仪表盘（Home/Dashboard）

**路径**：`/`

**布局**（2×2 卡片网格）：

```
┌──────────────────┬──────────────────┐
│ 心智状态          │ 组合状态          │
│ 焦虑:低 ✅        │ 偏离度: 3.5%     │
│ 贪婪:低 ✅        │ 最大回撤: -2.1%  │
│ 冷静期: 无        │ 夏普: 0.69       │
│ [查看详情]        │ [查看详情]        │
├──────────────────┼──────────────────┤
│ 市场环境          │ 风险告警          │
│ A股:中性(0.52)   │ 无严重告警 ✅     │
│ 美股:偏多(0.65)  │ 中等告警: 1       │
│ 港股:中性(0.48)  │ [查看全部]        │
│ 数据: 10:30 更新  │                  │
├──────────────────┴──────────────────┤
│ 待确认事项                            │
│ · 心智状态快照待确认（12h前）          │
│ · 授权书即将到期（30天后）            │
├─────────────────────────────────────┤
│ 最近活动                              │
│ Timeline: 最近5条操作记录             │
└─────────────────────────────────────┘
```

### 5.9 页面 P1-1：Agent 中心（AgentCenter/Index）

**路径**：`/agents`

**布局**：8个Agent状态卡片（2×4网格）

```
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ 用户状态Agent │ │ 市场环境Agent│ │ 研究Agent    │ │ 策略Agent    │
│ 状态: 空闲   │ │ 状态: 运行中 │ │ 状态: 空闲   │ │ 状态: 空闲   │
│ 上次: 2h前   │ │ 上次: 30m前 │ │ 上次: 1h前   │ │ 上次: 1h前   │
│ 输出: 快照v5 │ │ 输出: ctx-v3│ │ 输出: 5份研究│ │ 输出: 策略v2 │
│ [查看历史]   │ │ [查看历史]  │ │ [查看历史]   │ │ [查看历史]   │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ 组合Agent    │ │ 执行Agent    │ │ 风控Agent    │ │ 编排Agent    │
│ ...          │ │ ...          │ │ ...          │ │ ...          │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
```

### 5.10 页面 P1-2：复盘（Review/Index）

**路径**：`/review`

**布局**：

```
┌──────────────────────────────────────────────┐
│ 2026年7月复盘                                  │
├──────────────────────────────────────────────┤
│ Tab: 画像变化 | 组合偏离 | 策略表现 | 执行质量 | 心智趋势 │
│ ┌─ 画像变化 ──────────────────────────────┐  │
│ │ v1 → v2: 风险偏好从"积极"调整为"稳健"    │  │
│ │ 影响: 授权书v1已失效，需重新确认          │  │
│ └──────────────────────────────────────────┘  │
│ ┌─ 组合偏离 ──────────────────────────────┐  │
│ │ 当前偏离度: 3.5%（阈值5%）               │  │
│ │ 最大偏离: 科技板块 +2.1%                  │  │
│ └──────────────────────────────────────────┘  │
│ ...                                           │
├──────────────────────────────────────────────┤
│ AI 建议:                                      │
│ 1. 建议保持当前配置                            │
│ 2. 关注美联储利率决议对债券配置的影响          │
│ [完成本次复盘] [导出报告]                      │
└──────────────────────────────────────────────┘
```

### 5.11 页面 P1-3：审计日志（Review/AuditLog）

**路径**：`/review/audit`

**组件**：

- 过滤器：`<Select>` subject_type + `<DatePicker>` 时间范围 + `<Input>` 搜索
- 时间线：`<Timeline>` 展示事件流
- 详情：点击事件 → `<Drawer>` 展示完整 payload
- 版本追溯：通过 `request_correlation_id` 串联完整操作链

### 5.12 通用组件规格

| 组件                | 技术实现                                  | 属性                                    |
| ------------------- | ----------------------------------------- | --------------------------------------- |
| `ConfidenceBadge`   | `<Badge>` + 颜色映射                      | value: number (0~1) → 高/中/低          |
| `VersionTag`        | `<Tag>`                                   | version: number, timestamp: string      |
| `RiskIndicator`     | Ant Design`<Progress>` (type="dashboard") | value, thresholds: {green, yellow, red} |
| `ExplanationPanel`  | `<Collapse>`                              | title, content(Markdown), agent_name    |
| `StatusTimeline`    | `<Timeline>`                              | items: [{status, time, description}]    |
| `ConstraintReport`  | 自定义表格                                | passed[], failed[], warnings[]          |
| `MentalGauge`       | `<Gauge>` (AntV)                          | value(0~1), thresholds                  |
| `AllocationChart`   | ECharts Pie/Ring                          | data: [{name, value, color}]            |
| `OrderStatusBadge`  | `<Badge>` + 状态颜色                      | status → 颜色映射                       |
| `VersionTraceChain` | `<Space>` + `<Tag>`                       | versions: [{type, version, id}]         |

---

## 六、分阶段计划与工作量

| 阶段     | 描述                    | 预估人日    | 关键交付物                                                 |
| -------- | ----------------------- | ----------- | ---------------------------------------------------------- |
| 0        | 项目脚手架与基础设施    | 3           | docker-compose + FastAPI 骨架 + JWT + Alembic              |
| 1        | 数据模型与数据库 Schema | 5           | 16张表 ORM + 迁移脚本 + Repository 层                      |
| 2        | 用户认知引擎            | 6           | 画像/心智/授权/同意 CRUD 服务 + API + 建档向导前端         |
| 3        | 市场数据与资产主数据    | 4           | AKShare/yfinance Provider + Instrument 种子数据 + 持仓导入 |
| 4        | Agent 系统              | 7           | 8个 Agent + LangGraph 编排 + 工具集                        |
| 5        | 风控三段校验            | 3           | 20+ 条规则 + 三段调用链                                    |
| 6        | 仿真交易引擎            | 4           | 仿真账户 + 订单状态机 + 成交模型                           |
| 7        | API 层完善与研究服务    | 3           | 研究服务 + 补充查询接口                                    |
| 8        | 前端实现                | 8           | 7个P0页面 + 3个P1页面 + 10个通用组件                       |
| 9        | 测试与验收              | 5           | 单元/集成/验收测试（13个PRD场景）                          |
| 10       | 收尾与集成              | 2           | 联调 + Bug修复                                             |
| **合计** |                         | **50 人日** |                                                            |

**团队估算**：

- 1 人全栈：约 10 周
- 2 人（1后端+1前端）：约 6-7 周
- 3 人（2后端+1前端）：约 4-5 周

---

## 七、测试策略

### 7.1 测试层级

| 层级         | 覆盖范围                                                        | 目标覆盖率       |
| ------------ | --------------------------------------------------------------- | ---------------- |
| 单元测试     | Service 层逻辑、规则引擎、模型校验、completeness/confidence计算 | 核心service 90%+ |
| 集成测试     | API端到端、DB交互、Agent管线                                    | 全部API路径      |
| 验收测试     | PRD 13个核心场景（A1-A13）                                      | 100%             |
| 风控专项     | 三段校验 + 硬约束不可覆盖                                       | 100%规则         |
| 心智越权专项 | 心智状态不能修改授权/创建订单                                   | 0%越权率         |

### 7.2 PRD 验收场景 → 测试用例映射

| 场景 | 名称         | 测试步骤                                           | 断言                                                 |
| ---- | ------------ | -------------------------------------------------- | ---------------------------------------------------- |
| A1   | 画像成功     | POST /v1/profiles 填写全部字段 → 确认              | response.version=1, completeness≥0.8, confidence≥0.5 |
| A2   | 画像冲突     | POST 高风险+紧现金 → 查看冲突警告                  | conflict_warnings非空, 采用审慎边界                  |
| A3   | 授权不足     | autonomy_level=L0 → POST /v1/order-intents         | error.code="AUTONOMY_INSUFFICIENT"                   |
| A4   | 组合构造成功 | 有效授权+完整持仓 → POST /v1/target-portfolios     | constructible=true, target_weights非空               |
| A5   | 持仓覆盖不足 | unresolved_weight>15% → POST /v1/target-portfolios | constructible=false, 列出未解析持仓                  |
| A6   | 研究不足     | 缺bear_case → POST /v1/strategy-proposals          | error.code="RESEARCH_INSUFFICIENT"                   |
| A7   | 仿真执行成功 | L2+风控通过 → 完整订单生命周期                     | status: pending→approved→submitted→filled            |
| A8   | 风控阻断     | 订单突破约束 → POST /v1/order-intents              | status="blocked", risk_event已创建                   |
| A9   | 用户暂停     | POST /v1/strategies/pause → 尝试新订单             | 新订单被拒, status="blocked"                         |
| A10  | 授权失效     | 撤销授权 → 查看策略/订单                           | 关联对象status="invalid"                             |
| A11  | 实盘未启用   | POST /v1/simulated-orders(account_type=live)       | error.code="LIVE_NOT_ENABLED"                        |
| A12  | 心智冷静期   | 高焦虑触发冷静期 → 创建新订单                      | 订单暂停, cooldown记录存在, 授权不变                 |
| A13  | 市场不可用   | market_context.usable_status=stale → 策略生成      | error.code="MARKET_UNAVAILABLE"                      |

---

## 八、业务规则覆盖矩阵

| 规则  | 实现位置                                             | 保障机制                                                           |
| ----- | ---------------------------------------------------- | ------------------------------------------------------------------ |
| BR-01 | profile_service.completeness_check + mandate_service | completeness < 0.6 时 mandate 不可激活，API返回 PROFILE_INCOMPLETE |
| BR-02 | mandate_service + risk_service                       | 风险预算只能从 status=active 的 mandate 读取                       |
| BR-03 | versioning.py + audit.py + trace_versions            | 全链路版本关联，request_correlation_id 串联                        |
| BR-04 | Agent 设计（graph.py）                               | 所有 Agent 只输出建议到 state，不写入 DB 的 profile/mandate 表     |
| BR-05 | research_agent + strategy_agent                      | facts/inferences/assumptions 字段分离，schema 强制                 |
| BR-06 | research_service.validate_usable()                   | 缺 source/bear_case/risks → status=insufficient                    |
| BR-07 | market_service + risk_agent.check_stage_3            | usable_status≠usable → R3-03 阻断                                  |
| BR-08 | execution_service                                    | account_type 检查，P0 仅 simulation；live 返回 LIVE_NOT_ENABLED    |
| BR-09 | 前端 Trading 页面                                    | 顶部 Banner "仿真数据，非实际收益"                                 |
| BR-10 | risk_agent + execution_service                       | 暂停/撤销后 R2-04 阻断                                             |
| BR-11 | API GET endpoints + 导出服务                         | /v1/profiles/me, /v1/audit-events 等 + CSV/JSON 导出               |
| BR-12 | holding_service                                      | 未解析资产保持 unresolved，不做默认替换                            |
| BR-13 | Agent 错误处理（graph.py）                           | 失败 → pipeline_status=failed, error_message 非空                  |
| BR-14 | consent_records + data_access_filter                 | 撤回同意后，查询层过滤对应数据                                     |
| BR-15 | user_state_service + cooldown_periods                | 心智状态只创建 cooldown/alert，不修改 mandate/order                |

---

## 九、关键技术决策

| 决策项   | 基础版选择             | 完整版演进                   |
| -------- | ---------------------- | ---------------------------- |
| 策略生成 | 规则引擎（确定性配置） | RL(PPO) + 因子模型           |
| 情绪分析 | 规则 + LLM 摘要        | FinBERT 微调 + 贝叶斯融合    |
| 心智状态 | 规则阈值判定           | Transformer Encoder 行为序列 |
| 数据管道 | asyncio + APScheduler  | Kafka + Flink                |
| 存储     | PostgreSQL + Redis     | + ClickHouse (时序)          |
| 成交模型 | 收盘价 + 固定费率/滑点 | TWAP/VWAP + 市场冲击         |
| 组合优化 | 规则权重分配           | 均值-方差 + 风险平价         |

---

## 十、风险与缓解

| 风险                       | 概率 | 影响 | 缓解措施                                    |
| -------------------------- | ---- | ---- | ------------------------------------------- |
| LangGraph 编排复杂度超预期 | 中高 | 高   | 预留7天；Agent间TypedDict传递，避免隐式耦合 |
| LLM 研究质量不稳定         | 中   | 中   | 结构化校验+重试；不足时标记insufficient     |
| 前端工作量超预期           | 中   | 中   | P1页面可延后；优先P0建档/组合/交易          |
| 市场数据API不稳定          | 中低 | 中   | MockProvider兜底；Redis缓存最近数据         |
| 心智状态模型准确率不足     | 中   | 中低 | 基础版仅触发冷静期/提示，不影响交易         |
| PostgreSQL JSONB查询性能   | 低   | 中   | 关键路径加GIN索引；必要时拆为列             |
