# Finance-God 黑客松版实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 PRD v1.0 实现 Finance-God 黑客松 MVP，包含 4 个可插拔核心 Agent、自进化学习层、全量 P0 前端页面，使用 PandaAI 数据 + DeepSeek API + QuantSkills，零成本跑通仿真交易闭环。

**Architecture:** FastAPI 后端 + React 前端 + LangGraph Agent 编排（队友负责）。后端采用插件化架构：数据源、LLM、Agent、风控规则均为可插拔模块，通过统一接口注册。自进化层借鉴 Hermes 思想，通过用户反馈闭环持续优化画像置信度、策略权重和偏差检测阈值。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy 2.0 / PostgreSQL 16 / React 18 + TypeScript + Vite + Ant Design 5 / LangGraph / DeepSeek API + 火山 Seed / PandaAI 数据服务 / QuantSkills

---

## 一、核心设计原则

| 原则 | 含义 |
|------|------|
| 插件化 | 数据源、LLM、Agent、风控规则、费用模型、滑点模型均可通过注册机制替换，零硬编码 |
| 接口先行 | Agent 编排层由队友负责，所有 Agent 只实现统一接口，编排层通过接口发现和调用 |
| 自进化 | 每次用户反馈（画像确认/修正、策略评价、交易复盘）写入反馈表，定期触发进化评估 |
| TDD | 核心 service 和规则引擎先写测试再写实现 |

---

## 二、项目目录结构

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
│   │   ├── main.py                    # FastAPI 入口
│   │   ├── config.py                  # Pydantic Settings
│   │   ├── dependencies.py            # DI 容器
│   │   ├── core/
│   │   │   ├── security.py            # JWT 认证
│   │   │   ├── exceptions.py          # 全局异常
│   │   │   ├── events.py              # 领域事件总线
│   │   │   ├── versioning.py          # 版本化工具
│   │   │   ├── audit.py               # 审计事件写入
│   │   │   ├── cache.py               # 内存缓存（替代 Redis）
│   │   │   └── pagination.py          # 统一分页
│   │   ├── plugins/                   # ★ 插件注册中心
│   │   │   ├── __init__.py
│   │   │   ├── registry.py            # 插件注册/发现/生命周期
│   │   │   ├── base.py                # 所有插件的抽象基类
│   │   │   ├── data_providers/        # 数据源插件
│   │   │   │   ├── base.py            # DataProvider 抽象接口
│   │   │   │   ├── pandaai.py         # PandaAI 实现
│   │   │   │   └── mock.py            # Mock 数据（测试/离线）
│   │   │   ├── llm_providers/         # LLM 插件
│   │   │   │   ├── base.py            # LLMProvider 抽象接口
│   │   │   │   ├── deepseek.py        # DeepSeek API
│   │   │   │   ├── volcengine.py      # 火山引擎 Seed
│   │   │   │   └── mock.py            # Mock LLM
│   │   │   ├── fee_models/            # 费用模型插件
│   │   │   │   ├── base.py
│   │   │   │   └── flat_fee.py
│   │   │   └── slippage_models/       # 滑点模型插件
│   │   │       ├── base.py
│   │   │       └── fixed_bps.py
│   │   ├── models/                    # SQLAlchemy ORM（17 张表）
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── profile.py
│   │   │   ├── user_state.py
│   │   │   ├── mandate.py
│   │   │   ├── holding.py
│   │   │   ├── instrument.py
│   │   │   ├── research.py
│   │   │   ├── market_context.py
│   │   │   ├── strategy.py
│   │   │   ├── portfolio.py
│   │   │   ├── order.py
│   │   │   ├── execution.py
│   │   │   ├── risk_event.py
│   │   │   ├── audit_event.py
│   │   │   ├── consent.py
│   │   │   ├── cooldown.py
│   │   │   └── sim_account.py
│   │   ├── schemas/                   # Pydantic 请求/响应
│   │   │   ├── common.py
│   │   │   ├── profile.py
│   │   │   ├── mandate.py
│   │   │   ├── holding.py
│   │   │   ├── strategy.py
│   │   │   ├── portfolio.py
│   │   │   ├── order.py
│   │   │   └── review.py
│   │   ├── api/v1/                    # REST API 路由（薄层，只调 service）
│   │   │   ├── router.py
│   │   │   ├── profiles.py
│   │   │   ├── mandates.py
│   │   │   ├── holdings.py
│   │   │   ├── instruments.py
│   │   │   ├── strategies.py
│   │   │   ├── portfolios.py
│   │   │   ├── orders.py
│   │   │   ├── reviews.py
│   │   │   ├── risk_events.py
│   │   │   └── agents.py
│   │   ├── services/                  # 业务服务层
│   │   │   ├── profile_service.py
│   │   │   ├── user_state_service.py
│   │   │   ├── mandate_service.py
│   │   │   ├── holding_service.py
│   │   │   ├── market_service.py
│   │   │   ├── research_service.py
│   │   │   ├── strategy_service.py
│   │   │   ├── portfolio_service.py
│   │   │   ├── execution_service.py
│   │   │   ├── risk_service.py
│   │   │   ├── review_service.py
│   │   │   └── evolution_service.py   # ★ 自进化服务
│   │   ├── agents/                    # ★ Agent 插件（实现统一接口）
│   │   │   ├── base.py                # AgentPlugin 抽象基类
│   │   │   ├── user_state_agent.py
│   │   │   ├── market_agent.py
│   │   │   ├── strategy_portfolio_agent.py  # 合并策略+组合
│   │   │   ├── risk_agent.py
│   │   │   └── tools/                 # Agent 可调用的工具
│   │   │       ├── data_query.py
│   │   │       ├── research.py
│   │   │       └── portfolio_calc.py
│   │   ├── evolution/                 # ★ 自进化学习层
│   │   │   ├── __init__.py
│   │   │   ├── feedback_collector.py  # 反馈收集器
│   │   │   ├── profile_evolution.py   # 画像进化（置信度校准）
│   │   │   ├── strategy_evolution.py  # 策略进化（权重调整）
│   │   │   └── bias_evolution.py      # 偏差检测进化（阈值优化）
│   │   ├── risk/                      # 风控规则引擎（插件化）
│   │   │   ├── engine.py              # 规则引擎执行器
│   │   │   ├── base.py                # Rule 抽象基类
│   │   │   ├── rules/                 # 具体规则（每条规则一个文件）
│   │   │   │   ├── authorization.py
│   │   │   │   ├── user_state.py
│   │   │   │   ├── fund_order.py
│   │   │   │   ├── portfolio_risk.py
│   │   │   │   ├── market_data.py
│   │   │   │   └── agent_runtime.py
│   │   │   └── stages.py             # 三段校验编排
│   │   └── db/
│   │       ├── session.py
│   │       └── repositories/
│   └── tests/
│       ├── conftest.py
│       ├── unit/
│       ├── integration/
│       └── e2e/
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    └── src/
        ├── api/                       # API 客户端（自动生成）
        ├── hooks/
        ├── stores/                    # Zustand
        ├── pages/
        │   ├── Home/                  # P0-7: 首页仪表盘
        │   ├── Profile/               # P0-1: 建档向导 + P0-2: 画像详情
        │   ├── Mandate/               # P0-3: 授权书
        │   ├── Portfolio/             # P0-4: 持仓导入 + P0-5: 目标组合
        │   ├── AgentCenter/           # Agent 状态展示（简化版）
        │   ├── Trading/               # P0-6: 仿真交易
        │   └── Review/                # 复盘页（简化版）
        ├── components/                # 通用组件
        └── plugins/                   # ★ 前端插件注册（可扩展页面/组件）
```

---

## 三、插件化架构设计

### 3.1 插件注册中心

```python
# app/plugins/registry.py
from typing import TypeVar, Generic, Type
from abc import ABC

T = TypeVar("T", bound=ABC)

class PluginRegistry(Generic[T]):
    """通用插件注册中心，支持运行时注册/发现/替换"""
    
    def __init__(self):
        self._plugins: dict[str, Type[T]] = {}
        self._instances: dict[str, T] = {}
    
    def register(self, name: str, plugin_class: Type[T]) -> None:
        self._plugins[name] = plugin_class
    
    def get(self, name: str, **kwargs) -> T:
        if name not in self._instances:
            self._instances[name] = self._plugins[name](**kwargs)
        return self._instances[name]
    
    def list_available(self) -> list[str]:
        return list(self._plugins.keys())

# 全局注册实例
data_provider_registry = PluginRegistry()
llm_provider_registry = PluginRegistry()
agent_registry = PluginRegistry()
fee_model_registry = PluginRegistry()
slippage_model_registry = PluginRegistry()
rule_registry = PluginRegistry()
```

### 3.2 Agent 插件接口（编排层由队友调用）

```python
# app/agents/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any

class AgentInput(BaseModel):
    """所有 Agent 的统一输入格式"""
    request_id: str
    user_id: str
    context: dict[str, Any] = {}  # 上下文：画像版本、授权版本、市场环境等

class AgentOutput(BaseModel):
    """所有 Agent 的统一输出格式"""
    agent_name: str
    status: str  # success / failed / insufficient / blocked
    data: dict[str, Any] = {}
    error: str | None = None
    trace: dict[str, Any] = {}  # 版本追溯信息

class AgentPlugin(ABC):
    """Agent 插件抽象基类 —— 编排层通过此接口发现和调用 Agent"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Agent 唯一标识"""
    
    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """Agent 能力声明，供编排层路由"""
    
    @property
    @abstractmethod
    def input_schema(self) -> type[BaseModel]:
        """输入 schema，供编排层校验"""
    
    @property
    @abstractmethod
    def output_schema(self) -> type[BaseModel]:
        """输出 schema，供编排层校验"""
    
    @abstractmethod
    async def execute(self, input: AgentInput) -> AgentOutput:
        """执行 Agent 逻辑"""
    
    @abstractmethod
    async def health_check(self) -> dict:
        """健康检查，供编排层监控"""
```

### 3.3 LLM 插件接口

```python
# app/plugins/llm_providers/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel

class LLMRequest(BaseModel):
    system_prompt: str
    user_message: str
    temperature: float = 0.7
    max_tokens: int = 4096
    response_format: dict | None = None  # JSON schema for structured output

class LLMResponse(BaseModel):
    content: str
    model: str
    usage: dict = {}  # {prompt_tokens, completion_tokens}

class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse: ...
    
    @abstractmethod
    async def complete_structured(self, request: LLMRequest, schema: type[BaseModel]) -> BaseModel: ...
```

### 3.4 数据源插件接口

```python
# app/plugins/data_providers/base.py
from abc import ABC, abstractmethod
from datetime import date

class DataProvider(ABC):
    @abstractmethod
    async def get_market_data(self, symbol: str, start: date, end: date) -> list[dict]: ...
    
    @abstractmethod
    async def get_financial_data(self, symbol: str) -> dict: ...
    
    @abstractmethod
    async def get_index_data(self, index_code: str, start: date, end: date) -> list[dict]: ...
    
    @abstractmethod
    async def get_macro_data(self, indicator: str, start: date, end: date) -> list[dict]: ...
    
    @abstractmethod
    async def get_calendar(self, market: str) -> list[date]: ...
```

### 3.5 风控规则插件接口

```python
# app/risk/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel

class RuleResult(BaseModel):
    rule_id: str
    rule_name: str
    passed: bool
    rule_type: str  # hard_constraint / soft_threshold
    value: float | str | None = None
    limit: float | str | None = None
    severity: str = "info"  # critical / high / medium / low / info
    explanation: str = ""

class RiskRule(ABC):
    @property
    @abstractmethod
    def rule_id(self) -> str: ...
    
    @property
    @abstractmethod
    def rule_name(self) -> str: ...
    
    @property
    @abstractmethod
    def rule_type(self) -> str: ...  # hard_constraint / soft_threshold
    
    @property
    @abstractmethod
    def stage(self) -> int: ...  # 1 / 2 / 3
    
    @abstractmethod
    async def check(self, context: dict) -> RuleResult: ...
```

---

## 四、自进化学习层设计（Hermes 思想）

### 4.1 核心理念

借鉴 Hermes 的 function calling + 自进化能力：
- **Function Calling**：Agent 通过声明式工具接口调用外部能力，而非硬编码逻辑
- **自进化**：系统从每次交互的反馈中学习，持续优化三个维度

### 4.2 进化维度

| 维度 | 反馈信号 | 进化机制 | 影响范围 |
|------|---------|---------|---------|
| 画像进化 | 用户确认/修正画像维度 | 贝叶斯置信度更新 + 问题权重调整 | completeness/confidence 计算 |
| 策略进化 | 复盘时策略表现评分 | 策略候选历史胜率加权 | 策略 Agent 候选排序 |
| 偏差检测进化 | 用户确认/拒绝偏差提示 | 检测阈值自适应调整 | 用户状态 Agent 阈值 |

### 4.3 数据模型：evolution_feedbacks 表

```python
# 新增表：evolution_feedbacks（第 18 张表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | PK |
| user_id | UUID | FK |
| feedback_type | VARCHAR(32) | profile_correction / strategy_evaluation / bias_confirmation / bias_rejection |
| target_type | VARCHAR(32) | profile_dimension / strategy_proposal / cognitive_bias |
| target_id | UUID | 被反馈对象 ID |
| target_version | INTEGER | 被反馈对象版本 |
| feedback_value | JSONB | 反馈内容（评分/修正值/确认/拒绝） |
| evolution_applied | BOOLEAN | 是否已应用到进化模型 |
| applied_at | TIMESTAMPTZ | 应用时间 |
| created_at | TIMESTAMPTZ | 创建时间 |
```

### 4.4 进化服务接口

```python
# app/evolution/feedback_collector.py
class FeedbackCollector:
    """收集所有用户反馈事件，写入 evolution_feedbacks 表"""
    async def collect_profile_correction(self, user_id, dimension, old_value, new_value): ...
    async def collect_strategy_evaluation(self, user_id, strategy_id, rating, comment): ...
    async def collect_bias_feedback(self, user_id, bias_type, confirmed: bool): ...

# app/evolution/profile_evolution.py
class ProfileEvolution:
    """画像进化：根据用户修正历史调整置信度计算权重"""
    async def recalculate_confidence_weights(self, user_id) -> dict: ...
    async def suggest_question_improvements(self) -> list[dict]: ...

# app/evolution/strategy_evolution.py
class StrategyEvolution:
    """策略进化：根据历史表现调整策略候选排序权重"""
    async def update_strategy_scores(self, user_id) -> dict: ...
    async def get_strategy_ranking(self, user_id, context: dict) -> list[dict]: ...

# app/evolution/bias_evolution.py
class BiasEvolution:
    """偏差检测进化：根据用户确认/拒绝调整检测阈值"""
    async def update_thresholds(self, user_id) -> dict: ...
    async def get_adaptive_thresholds(self, user_id, bias_type: str) -> dict: ...
```

---

## 五、技术选型对比（原方案 vs 黑客松版）

| 层级 | 原方案 | 黑客松版 | 变更理由 |
|------|--------|---------|---------|
| LLM | OpenAI GPT-4o | DeepSeek API + 火山 Seed（插件切换） | 免费、SDK 兼容、双模型冗余 |
| 市场数据 | AKShare + yfinance | PandaAI 全量数据服务 | 专业级、7天全量、覆盖完整 |
| 金融计算 | 自建回测/风险分析 | QuantSkills | 现成能力、省去自建 |
| 缓存 | Redis | 内存缓存（cachetools） | MVP 单机无需分布式缓存 |
| 自进化 | 无 | Hermes 思想：反馈闭环 + 决策进化 | 差异化亮点 |
| Agent 编排 | LangGraph 自实现 | 队友负责，留接口 | 分工协作 |
| Agent 数量 | 8 个 | 4 个核心 + 插件扩展 | 聚焦 MVP |
| 风控规则 | 硬编码 | 插件化规则引擎 | 可扩展 |

---

## 六、分阶段任务计划

### Phase 0: 项目脚手架与基础设施（3 天）

- [ ] Task 0.1: 初始化 backend（FastAPI + pyproject.toml + 目录结构）
- [ ] Task 0.2: 配置管理（config.py + .env.example + docker-compose）
- [ ] Task 0.3: 插件注册中心（registry.py + base.py）
- [ ] Task 0.4: 核心工具（versioning.py + cache.py + audit.py + pagination.py + exceptions.py）
- [ ] Task 0.5: 数据库连接 + Alembic 初始化
- [ ] Task 0.6: JWT 认证（security.py）
- [ ] Task 0.7: 初始化 frontend（Vite + React + TS + Ant Design + Zustand）

### Phase 1: 数据模型（5 天）

- [ ] Task 1.1: users + user_profiles ORM 模型 + 迁移
- [ ] Task 1.2: user_state_snapshots + consent_records + cooldown_periods ORM
- [ ] Task 1.3: investment_mandates ORM
- [ ] Task 1.4: holding_snapshots + instruments ORM
- [ ] Task 1.5: research_memos + market_contexts ORM
- [ ] Task 1.6: strategy_proposals + target_portfolios ORM
- [ ] Task 1.7: order_intents + execution_records + sim_account ORM
- [ ] Task 1.8: risk_events + audit_events ORM
- [ ] Task 1.9: evolution_feedbacks ORM（自进化表）
- [ ] Task 1.10: Repository 层（通用 CRUD + 版本查询）

### Phase 2: 插件层实现（4 天）

- [ ] Task 2.1: LLM 插件 — base.py + deepseek.py + volcengine.py + mock.py
- [ ] Task 2.2: 数据源插件 — base.py + pandaai.py + mock.py
- [ ] Task 2.3: 费用模型插件 — base.py + flat_fee.py
- [ ] Task 2.4: 滑点模型插件 — base.py + fixed_bps.py
- [ ] Task 2.5: 插件自动发现与注册（启动时扫描 plugins/ 目录）

### Phase 3: 用户认知引擎 Services（5 天）

- [ ] Task 3.1: profile_service（CRUD + completeness/confidence 计算 + 版本化）
- [ ] Task 3.2: user_state_service（心智快照 + 冷静期判定 + 偏差检测）
- [ ] Task 3.3: mandate_service（创建/激活/暂停/撤销 + 授权校验）
- [ ] Task 3.4: holding_service（CSV 解析 + 资产匹配 + 未解析检测）
- [ ] Task 3.5: 对应 API 路由（profiles + mandates + holdings + instruments）

### Phase 4: 4 个核心 Agent（6 天）

- [ ] Task 4.1: Agent 基类（base.py）+ Agent 注册
- [ ] Task 4.2: 用户状态 Agent（规则引擎 + 偏差检测 + 冷静期判定）
- [ ] Task 4.3: 市场环境 Agent（PandaAI 数据 + 情绪评分 + LLM 摘要）
- [ ] Task 4.4: 策略组合 Agent（授权约束映射 + 资产配置 + 组合构造 + 调仓计划）
- [ ] Task 4.5: 风控 Agent（三段规则引擎 + 插件化规则注册）
- [ ] Task 4.6: Agent 工具集（data_query + research + portfolio_calc）
- [ ] Task 4.7: Agent 编排接口适配（确保队友的编排层可发现/调用所有 Agent）

### Phase 5: 风控规则引擎（3 天）

- [ ] Task 5.1: 规则引擎执行器（engine.py + stages.py）
- [ ] Task 5.2: 阶段一规则（R1-01 ~ R1-08：授权、画像、资产、集中度、现金、未解析）
- [ ] Task 5.3: 阶段二规则（R2-01 ~ R2-06：授权再校验、自主级别、冷静期、暂停、限额、幂等）
- [ ] Task 5.4: 阶段三规则（R3-01 ~ R3-06：现金充足、价格保护、市场可用、暂停、重复、滑点）

### Phase 6: 仿真交易引擎（3 天）

- [ ] Task 6.1: execution_service（订单状态机 + 幂等 + 生命周期）
- [ ] Task 6.2: 仿真成交（调用费用/滑点插件 + 更新 sim_account）
- [ ] Task 6.3: 对应 API 路由（strategies + portfolios + orders）

### Phase 7: 自进化学习层（2 天）

- [ ] Task 7.1: evolution_feedbacks 表 + FeedbackCollector
- [ ] Task 7.2: ProfileEvolution（画像置信度贝叶斯更新）
- [ ] Task 7.3: StrategyEvolution（策略历史胜率加权排序）
- [ ] Task 7.4: BiasEvolution（偏差检测阈值自适应）
- [ ] Task 7.5: 在 profile/strategy/bias service 中集成反馈收集点

### Phase 8: 复盘服务（1 天）

- [ ] Task 8.1: review_service（画像变化 + 组合偏离 + 策略表现 + 执行质量 + 心智趋势）
- [ ] Task 8.2: review API 路由

### Phase 9: 前端实现（7 天）

- [ ] Task 9.1: 全局布局 + 路由 + API 客户端 + Zustand store
- [ ] Task 9.2: 通用组件（ConfidenceBadge + VersionTag + RiskIndicator + StatusTimeline + ConstraintReport）
- [ ] Task 9.3: P0-1 建档向导（7 步向导 + 实时完整度）
- [ ] Task 9.4: P0-2 画像详情（维度卡片 + 置信度 + 心智面板 + 修正抽屉）
- [ ] Task 9.5: P0-3 授权书（展示 + 自主级别选择 + 暂停/撤销）
- [ ] Task 9.6: P0-4 持仓导入（CSV 上传 + 解析预览 + 手动匹配）
- [ ] Task 9.7: P0-5 目标组合（饼图 + 约束报告 + 风险情景 + 调仓计划 + 版本追溯）
- [ ] Task 9.8: P0-6 仿真交易（账户概览 + 持仓表 + 订单列表 + 详情抽屉）
- [ ] Task 9.9: P0-7 首页仪表盘（心智 + 组合 + 市场 + 风险 4 卡片 + 待确认 + 最近活动）
- [ ] Task 9.10: Agent 状态页（简化版，展示 Agent 接口输出）
- [ ] Task 9.11: 复盘页（简化版，Tab 展示各维度）

### Phase 10: 测试与验收（4 天）

- [ ] Task 10.1: 单元测试 — profile/mandate/holding service
- [ ] Task 10.2: 单元测试 — 风控规则引擎（20+ 条规则）
- [ ] Task 10.3: 集成测试 — API 端到端（PRD 13 个验收场景 A1-A13）
- [ ] Task 10.4: 自进化测试 — 反馈收集 + 进化效果验证
- [ ] Task 10.5: 心智越权专项 — 心智状态不能修改授权/创建订单（0% 越权率）

### Phase 11: 联调与收尾（2 天）

- [ ] Task 11.1: 与队友编排层联调
- [ ] Task 11.2: Bug 修复 + 文档补充

**总计：约 45 天（单人），3 人团队约 3-4 周**

---

## 七、关键技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 策略生成（基础版） | 规则引擎 + LLM 解释 | 确定性高，可快速验证 |
| 情绪分析 | PandaAI 数据 + 规则评分 + LLM 摘要 | 免费数据 + 简单有效 |
| 心智状态 | 规则阈值（可被进化层调整） | 基础版够用，阈值可自适应 |
| 数据管道 | asyncio + APScheduler | MVP 无需 Kafka |
| 存储 | PostgreSQL only | 单机够用，JSONB 灵活 |
| 成交模型 | 收盘价 + 插件化费用/滑点 | 可扩展为 TWAP/VWAP |
| 组合优化 | 规则权重分配 | 后续可升级为均值-方差 |
| Agent 编排 | 队友负责，接口适配 | 分工协作 |
| 自进化 | Hermes 思想：反馈闭环 | 差异化，不影响核心交易安全 |

---

## 八、PRD 验收场景覆盖

| 场景 | 覆盖 Task |
|------|----------|
| A1 画像成功 | Task 3.1 + Task 10.3 |
| A2 画像冲突 | Task 3.1 + Task 10.3 |
| A3 授权不足 | Task 5.3 (R2-02) + Task 10.3 |
| A4 组合构造成功 | Task 4.4 + Task 10.3 |
| A5 持仓覆盖不足 | Task 3.4 + Task 5.2 (R1-06) + Task 10.3 |
| A6 研究不足 | Task 4.3 + Task 10.3 |
| A7 仿真执行成功 | Task 6.1 + Task 10.3 |
| A8 风控阻断 | Task 5.1-5.4 + Task 10.3 |
| A9 用户暂停 | Task 5.3 (R2-04) + Task 10.3 |
| A10 授权失效 | Task 3.3 + Task 10.3 |
| A11 实盘未启用 | Task 6.1 + Task 10.3 |
| A12 心智冷静期 | Task 3.2 + Task 5.3 (R2-03) + Task 10.3 |
| A13 市场不可用 | Task 4.3 + Task 5.4 (R3-03) + Task 10.3 |
