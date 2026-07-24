### 1.2 目标

- **感知**：通过多源数据（聊天文本、交易行为、使用模式、市场数据）实时分析用户当前心智状态
- **识别**：检测认知偏差（处置效应、过度自信、羊群效应、损失厌恶、锚定效应）
- **检测**：发现用户言行不一致（说冷静但疯狂交易、说长期但日内操作）
- **辅助**：向策略Agent输出心理状态和风险调整建议，辅助交易策略调整
- **干预**：在用户出现极端情绪或严重偏差时，主动介入干预



---

## 2. 系统架构

### 2.1 四层架构总览

```text
┌────────────────────────────────────────────────────────────────┐
│                    干预层 (Intervention Layer)                    │
│  规则引擎 + RL策略 → 情绪安抚/偏差提示/交易限制/教育推送        │
└──────────────────────────────┬─────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────┐
│                    预测层 (Prediction Layer)                      │
│  LSTM/Transformer行为序列模型 → 情绪化交易风险/状态转移概率      │
│  时序异常检测 → 行为/情绪突变预警                                │
└──────────────────────────────┬─────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────┐
│                    理解层 (Understanding Layer)                   │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐          │
│  │风险画像  │ │情绪识别   │ │偏差检测   │ │状态识别    │          │
│  │GL-RTS   │ │词典+LLM  │ │规则+ML   │ │HMM/贝叶斯 │          │
│  │+行为校正│ │+行为特征  │ │量化指标   │ │状态转移   │          │
│  └─────────┘ └──────────┘ └──────────┘ └───────────┘          │
└──────────────────────────────┬─────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────┐
│                    感知层 (Perception Layer)                      │
│  行为事件流(Kafka) + 文本(问卷/对话) + 市场数据 + 可穿戴(可选)  │
└────────────────────────────────────────────────────────────────┘
```

### 2.2 Agent三大模块与数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户心智分析Agent                              │
│  ┌───────────────────────────────────────────────────────────┐      │
│  │  感知模块：聊天情绪分析 | 行为信号采集 | 羊群效应检测 | 市场压力│      │
│  └───────────────────────────┬───────────────────────────────┘      │
│  ┌───────────────────────────▼───────────────────────────────┐      │
│  │  画像模块：用户画像存储 | 行为基线管理 | 认知偏差档案 | 言行一致性│    │
│  └───────────────────────────┬───────────────────────────────┘      │
│  ┌───────────────────────────▼───────────────────────────────┐      │
│  │  干预模块：触发判定 | 策略选择 | 执行引擎 | 反馈闭环        │      │
│  └───────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
     ↓                  ↓                  ↓
 策略Agent           前端展示         Orchestrator
(mental_state      (emotion_display  (should_intervene
 risk_adjust        intervention      intervention_priority
 bias_warnings)     profile_summary)  intervention_content)
```

**数据流**：聊天文本→情绪分析→画像情绪记录；交易事件→行为采集→偏差计算+基线更新；市场数据→市场压力→环境压力评分；综合状态→一致性检测→干预触发→策略Agent/前端/Orchestrator

---

## 3. 数据采集层

### 3.1 行为事件流（核心数据源）

| 事件类型 | 具体事件 | 心理意义 | 采集频率 |
|:---------|:---------|:---------|:---------|
| **登录行为** | 登录时间、频率、时长、深夜登录 | 焦虑度、信息依赖度 | 实时 |
| **持仓查看** | 查看频率、停留时长、盈亏页面反复查看 | 损失厌恶、焦虑水平 | 实时 |
| **交易行为** | 下单/撤单频率、追涨杀跌模式、止损设置 | 冲动性、过度自信、自控力 | 实时 |
| **信息消费** | 浏览资讯类型、阅读时长、搜索关键词 | 确认偏误、信息过载、恐慌搜索 | 实时 |
| **社交行为** | 评论/发帖、关注热门话题、分享操作 | 从众倾向、社交验证需求 | 准实时 |

**事件格式标准**：
```json
{
  "user_id": "U12345", "timestamp": "2026-07-23T14:32:10Z",
  "event_type": "POSITION_VIEW",
  "context": {
    "symbol": "600519", "pnl_status": "loss", "view_duration_sec": 45,
    "session_count_today": 12,
    "market_condition": {"index_change": -2.3, "volatility": "high"}
  }
}
```

### 3.2 文本数据源与问卷

| 来源 | 分析目标 | 技术 |
|:-----|:---------|:-----|
| 与AI对话文本 | 个体情绪、认知模式、焦虑表达 | 词典+LLM双路径 |
| 情绪日记（用户主动） | 主观情绪状态、压力自评 | 情感分类+关键词 |
| 开放式问卷回答 | 深层心理特征、目标理解 | LLM推理 |

**心理量表**：GL-RTS(13题/季度)、GDMS决策风格(25题/半年)、Financial Anxiety Scale(5-8题/月度)、自适应Prospect Theory问卷(6-8题/半年)、情绪快速自评(1-3题/触发式)

### 3.3 技术选型

- **事件流**：Apache Kafka（Topic: user_events / market_events）
- **实时计算**：Apache Flink（滚动窗口特征计算）
- **特征存储**：Redis（热特征）+ ClickHouse（时序分析）
- **文本模型**：词典匹配（快速路径<50ms）+ LLM GPT-4o-mini（精确路径<2s）

---

## 4. 情绪感知模块

### 4.1 双层架构：词典 + LLM

```
用户消息 → 动态词典匹配(<50ms)
              │
         confidence≥0.5 且 长度≤50字 且 无反讽/隐喻？
              │
        ┌─────┴─────┐
        │Yes        │No
        ▼           ▼
      输出结果    LLM精确分析(<2s, GPT-4o-mini)
                      │
                      ▼
                   输出结果 + 反哺词典
```

### 4.2 动态词典设计

**初始词典**（6类，每类15-20个关键词）：

```json
{
  "贪婪": ["加仓","抄底","全仓","追涨","牛市来了","暴涨","起飞","翻倍","梭哈","重仓","必须买","再不买就晚了","FOMO","错过","上车","冲冲冲","干就完了","稳赚","血赚"],
  "恐慌": ["崩盘","暴跌","割肉","清仓","完了","血亏","逃命","熊市","黑天鹅","爆仓","赶紧卖","跑","完蛋","亏麻了","要崩","大跌","跳水","末日"],
  "焦虑": ["怎么办","纠结","犹豫","不确定","要不要","好难","不知道该","万一","担心","害怕","紧张","睡不着","心慌","拿不准","好烦","焦虑"],
  "乐观": ["看好","会涨","有信心","没问题","长期持有","价值投资","基本面好","前景不错","值得期待","稳了","乐观","机会","底部","反转","向好"],
  "沮丧": ["亏了","后悔","不该","自责","无力","放弃","算了","没意思","不玩了","套牢","深套","麻木了","绝望","难受","心痛","郁闷"],
  "冷静": ["分析一下","看看数据","基本面","技术面","估值","PE","仓位管理","风险控制","分散","对冲","理性","客观","计划","策略","纪律"]
}
```

**词典数据结构**：
```typescript
interface LexiconEntry {
  keyword: string; emotion: EmotionType; weight: number; confidence: number;
  source: 'initial' | 'llm_feedback' | 'behavior_validated' | 'community';
  last_validated: string; usage_count: number; hit_count: number;
}
type EmotionType = '贪婪' | '恐慌' | '焦虑' | '乐观' | '沮丧' | '冷静';
```

**词典更新**：MVP实现LLM反哺（LLM置信度>0.9且词典未收录→初始confidence=0.5）

**LLM反哺伪代码**：
```python
def update_lexicon_from_llm(text, llm_result, lexicon):
    if llm_result.confidence < 0.9: return
    tokens = tokenize(text)
    existing = {e.keyword for e in lexicon.entries}
    for token in tokens:
        if token not in existing and len(token) >= 2:
            lexicon.entries.append(LexiconEntry(
                keyword=token, emotion=llm_result.emotion,
                weight=abs(llm_result.score), confidence=0.5,
                source='llm_feedback', last_validated=now(), usage_count=1, hit_count=0))
```

### 4.3 LLM分析

**触发条件**：词典无结果/置信度<0.5、文本>50字、含反讽特征（"呵呵""真是""太好了"等）

**Prompt设计**：
```text
你是一个专业的投资心理分析师。请分析以下用户消息中体现的情绪状态。
用户消息：{user_message}
用户画像背景：投资经验={experience_level}，风险偏好={risk_tolerance}，近期情绪={recent_emotion_summary}
请严格按以下JSON格式输出：
{
  "emotion": "贪婪|恐慌|焦虑|乐观|沮丧|冷静",
  "score": <float 0~1 情绪强度>,
  "arousal": <float 0~1 心理激活/冲动程度>,
  "valence": <float -1~1 情绪效价>,
  "reasoning": "<50字分析理由>",
  "confidence": <float 0~1 确信度>,
  "sub_emotions": [<可选次要情绪>]
}
唤醒度参考：贪婪/恐慌>0.7, 乐观/焦虑0.4~0.7, 冷静/沮丧<0.4
```

**成本控制**：目标90%词典消化/10%调LLM，动态调整词典置信度阈值。
```python
def adjust_lexicon_threshold(metrics):
    current_llm_rate = metrics['llm_calls'] / metrics['total_requests']
    threshold = 0.5
    if current_llm_rate > 0.10: threshold = max(0.3, threshold - 0.05)
    elif current_llm_rate < 0.05: threshold = min(0.7, threshold + 0.05)
    return threshold
```

### 4.4 情绪二维模型（Russell环形模型）

```
                高唤醒(Arousal)
          恐慌(-V,+A) │ 贪婪(+V,+A)
    焦虑(-V,mid-A)    │    乐观(+V,mid-A)
  负效价 ←────────────┼────────────→ 正效价
          沮丧(-V,-A) │ 冷静(+V/-V,-A)
                低唤醒
```

**六类情绪定义**：

| 类别 | 英文 | 效价 | 唤醒度 | 典型场景 | 区分要点 |
|------|------|:----:|:------:|---------|---------|
| 贪婪 | greed | + | 0.7~1.0 | 追涨、FOMO、冲动加仓 | vs乐观：有急迫行动冲动 |
| 乐观 | optimism | + | 0.3~0.6 | 看好后市、有信心 | vs贪婪：平稳无冲动 |
| 冷静 | calm | 0 | 0.0~0.3 | 理性分析、客观评估 | 无明显情绪倾向 |
| 焦虑 | anxiety | - | 0.5~0.8 | 不确定、纠结、犹豫 | vs恐慌：未到极端行动 |
| 沮丧 | frustration | - | 0.1~0.4 | 已亏损、自责、后悔 | vs恐慌：消极而非激动 |
| 恐慌 | panic | - | 0.7~1.0 | 害怕巨亏、想立刻止损 | vs沮丧：极度激动+行动冲动 |

**score说明**：0~1情绪强度，不携带正负号。0.3~0.5轻微、0.5~0.7中等、0.7~0.9强烈、0.9~1.0极端。干预阈值：>0.7触发P2，>0.9触发P0/P1。

### 4.5 情绪分析输出格式

```typescript
interface EmotionResult {
  emotion: EmotionType; score: number; arousal: number; valence: number;
  confidence: number; source: 'lexicon' | 'llm';
  reasoning?: string; timestamp: string; sub_emotions?: EmotionType[];
}
interface LexiconResult {
  matched_keywords: Array<{keyword: string; emotion: EmotionType; weight: number}>;
  confidence: number; dominant_emotion: EmotionType; score: number; arousal: number; valence: number;
}
```

**词典匹配算法**：
```python
def lexicon_analyze(text, lexicon):
    matched, emotion_scores = [], defaultdict(list)
    for entry in lexicon.entries:
        if entry.keyword in text:
            matched.append({'keyword': entry.keyword, 'emotion': entry.emotion, 'weight': entry.weight})
            emotion_scores[entry.emotion].append(entry.weight)
    if not matched: return LexiconResult(matched_keywords=[], confidence=0.0, dominant_emotion='冷静', score=0.0)
    emotion_avg = {e: sum(w)/len(w) for e, w in emotion_scores.items()}
    dominant = max(emotion_avg, key=emotion_avg.get)
    arousal_map = {'贪婪': 0.85, '恐慌': 0.9, '焦虑': 0.65, '乐观': 0.45, '沮丧': 0.25, '冷静': 0.15}
    valence_map = {'贪婪': 0.7, '恐慌': -0.9, '焦虑': -0.4, '乐观': 0.6, '沮丧': -0.5, '冷静': 0.1}
    score = emotion_avg[dominant]
    confidence = min(1.0, len(matched)*0.2 + sum(m['weight'] for m in matched)/len(matched)*0.5)
    return LexiconResult(matched_keywords=matched, confidence=confidence, dominant_emotion=dominant,
        score=score, arousal=arousal_map[dominant], valence=valence_map[dominant]*score)
```

### 4.6 行为信号采集

```typescript
interface TradeSignal {
  user_id: string; trade_id: string; timestamp: string;
  symbol: string; direction: 'buy'|'sell'; amount: number; quantity: number; price: number;
  trade_frequency_1h: number; trade_frequency_24h: number; position_concentration: number;
  holding_days: number; stop_loss_executed: boolean;
  market_condition: 'up'|'down'|'flat'; stock_change_pct: number;
}
interface UsageSignal {
  user_id: string; timestamp: string;
  session_start: string; session_duration_min: number;
  is_late_night: boolean; is_pre_market: boolean;
  page_stay_times: Array<{page: string; duration_sec: number}>;
  search_keywords: string[];
  watchlist_changes: Array<{action: 'add'|'remove'; symbol: string}>;
  notification_click_rate: number; portfolio_refresh_count: number; price_check_frequency: number;
}
```

**行为→情绪映射规则**：

| 行为信号 | 条件 | 推断情绪 | 强度 | 置信度 |
|---------|------|---------|------|--------|
| 交易频率突增 | freq > baseline×3 | 贪婪/恐慌 | 0.8 | 0.6 |
| 深夜频繁查看 | 23:00-06:00且refresh>10/h | 焦虑 | 0.6 | 0.7 |
| 开盘前密集操作 | 08:00-09:30且trade>3 | 贪婪/焦虑 | 0.7 | 0.5 |
| 持仓页面高频刷新 | refresh>20/h | 焦虑/恐慌 | 0.5 | 0.6 |
| 搜索"止损""割肉" | 关键词命中 | 恐慌/沮丧 | 0.7 | 0.8 |
| 快速买入后立刻卖出 | 间隔<10min | 焦虑/恐慌 | 0.8 | 0.7 |
| 单笔金额突增 | amount>baseline×3 | 贪婪 | 0.7 | 0.5 |
| 持仓集中度>80% | top1>80% | 贪婪/过度自信 | 0.6 | 0.7 |
| 连续亏损后加仓 | loss_streak≥3且buy | 沮丧/报复性交易 | 0.8 | 0.7 |
| 反复查看亏损持仓 | 查看亏损股>5次/天 | 沮丧/损失厌恶 | 0.6 | 0.6 |

### 4.7 羊群效应检测

```python
# 维度1：简化LSV指标
def calculate_lsv(user_trades, market_trades):
    user_buy_ratio = sum(1 for t in user_trades if t.direction=='buy') / len(user_trades)
    market_buy_ratio = sum(t.volume for t in market_trades if t.direction=='buy') / sum(t.volume for t in market_trades)
    return 1.0 - abs(user_buy_ratio - market_buy_ratio)  # 越高越从众

# 维度2：持仓与热门重合度
def calculate_hot_overlap(user_holdings, hot_stocks):
    return len(set(user_holdings) & set(hot_stocks)) / len(user_holdings)

# 维度3：社交影响时间相关性
def calculate_social_influence(trade_time, social_reads):
    return max((1.0 - (trade_time - r.timestamp).seconds/1800 for r in social_reads if 0 < (trade_time - r.timestamp).seconds <= 1800), default=0.0)
```

```typescript
interface HerdingResult {
  herding_score: number; herding_type: '跟买'|'跟卖'|'无';
  dimensions: { lsv_score: number; hot_overlap: number; social_influence: number };
  confidence: number; timestamp: string;
}
```

### 4.8 市场环境压力

```python
def calculate_market_pressure(user_holdings, market_data, news_data):
    total = sum(h.quantity * h.current_price for h in user_holdings)
    weighted_change = sum((h.quantity*h.current_price/total)*h.daily_change_pct for h in user_holdings) if total > 0 else 0
    portfolio_pressure = max(0, min(1, 0.5 - weighted_change/10))
    market_vol_pressure = min(1.0, (market_data.high-market_data.low)/market_data.open / 0.03)
    neg_count = news_data.count_negative_news(hours=24)
    tot_count = news_data.count_total_news(hours=24)
    negative_density = neg_count / tot_count if tot_count > 0 else 0
    return MarketPressure(
        market_pressure=portfolio_pressure*0.5 + market_vol_pressure*0.3 + negative_density*0.2,
        components={'portfolio_weighted_change': portfolio_pressure, 'market_volatility': market_vol_pressure, 'negative_news_density': negative_density},
        timestamp=now())
```

```typescript
interface MarketPressure {
  market_pressure: number;  // 0-1
  components: { portfolio_weighted_change: number; market_volatility: number; negative_news_density: number };
  timestamp: string;
}
```

---

## 5. 用户画像模块

### 5.1 画像分层架构

| Layer | 数据来源 | 获取方式 | 数据特点 | 更新频率 | 可信度 |
|-------|---------|---------|---------|---------|-------|
| **Static Profile** | 用户填写 | Selection | 客观事实 | 很低 | ⭐⭐⭐⭐ |
| **Cognitive Profile** | AI聊天 | AI Conversation | 心理/目标/价值观 | 中 | ⭐⭐⭐ |
| **Behavior Profile** | 真实行为 | Behavior Tracking | 最真实 | 持续 | ⭐⭐⭐⭐⭐ |
| **Confidence Layer** | 系统计算 | Data Fusion | 画像可靠度 | 实时 | —— |

### 5.2 用户画像数据结构

```typescript
interface UserProfile {
  user_id: string; created_at: string; updated_at: string;
  static_attributes: {
    risk_tolerance: number;  // 1-10
    investment_style: 'conservative'|'balanced'|'aggressive'|'speculative';
    experience_level: 'beginner'|'intermediate'|'advanced'|'expert';
    investment_horizon: 'day_trade'|'short_term'|'medium_term'|'long_term';
    preferred_sectors: string[]; max_single_position_pct: number;
  };
  dynamic_attributes: {
    current_emotion: EmotionResult;
    emotion_history: Array<{emotion: EmotionType; score: number; timestamp: string; source: string}>;
    bias_scores: { disposition_effect: number; overconfidence: number; herding: number; loss_aversion: number; anchoring: number };
    consistency_score: number; contradiction_type?: ContradictionType;
  };
  behavioral_baseline: {
    baseline_trade_freq: number; baseline_holding_days: number; baseline_single_amount_pct: number;
    baseline_active_hours: number[]; baseline_emotion_volatility: number; baseline_risk_asset_pct: number;
    observation_period_complete: boolean; observation_start: string; observation_trade_count: number;
  };
  statistics: { total_trades: number; total_chat_messages: number; intervention_count: number; intervention_acceptance_rate: number; days_active: number };
}
type ContradictionType = '嘴硬型焦虑'|'风格漂移'|'止损失效'|'风险低估';
```

### 5.3 画像维度详解

**静态画像**："这个用户是谁？" — 基础信息(年龄/性别/地区/职业/学历)、财富情况(年收入/月现金流/总资产/负债/可投资金额)、投资经历(年限/产品/知识)、投资目标。系统自动计算：Wealth Level、Debt Ratio(`Debt/Asset`)、Cash Flow Stability、Experience Score。

**心智画像**："用户为什么这样投资？" — AI通过聊天持续推断：
- Goal（目标）：Financial Freedom/Wealth Growth/Capital Preservation/Education/Retirement（各0~100）
- Motivation（动机）：Freedom/Security/Achievement/Status/Family（各0~100）
- Risk Cognition：Risk Tolerance/Loss Aversion/Recovery Ability/Panic Probability（各0~100）
- Thinking Style：Data Driven/News Driven/KOL Driven/AI Trust/Emotional Decision/Rational Decision（各0~100）

**行为画像**："用户真正是怎么做的？" — 历史行为(Holding Period/Trading Frequency/Win Rate/Max Drawdown/Stop Loss)→Patience/Discipline/Trading Style；产品行为(Daily Open/Portfolio Check/News Reading/Cancel AI Advice/View Loss)→AI Trust/Long-term/Impulsiveness/FOMO/Loss Obsession

### 5.4 可信度层与来源融合

```text
Final Score = Behavior×50% + AI Conversation×35% + Selection×15%
```

**"言行一致性"校正**（研究依据：剑桥大学2022报告示35%用户问卷不诚实）：
```python
def calibrated_risk_tolerance(user):
    stated = questionnaire_score(user)    # 问卷自述 (0-100)
    revealed = behavior_implied_risk(user)  # 行为揭示 (0-100)
    consistency = 1 - abs(stated - revealed) / 100
    weight_behavior = 0.3 + 0.4 * (1 - consistency)  # 一致性低→偏向行为
    weight_stated = 1 - weight_behavior
    return weight_stated * stated + weight_behavior * revealed, consistency
```

### 5.5 个人行为基线

**观察期**：7天或20笔交易（取先到的），期间只采集不干预。

**基线指标**：日均交易频率、平均持仓天数、平均单笔金额占比、常用交易时间段、情绪波动幅度(标准差)、风险资产占比。

**基线更新**：滑动窗口30天，每周重算，最少10个数据点。

**异常判定**：z-score > 2.0（偏离基线超过2个标准差）。
```python
def detect_anomaly(current_value, baseline_value, baseline_std):
    if baseline_std == 0: return False
    return abs(current_value - baseline_value) / baseline_std > 2.0
```

### 5.6 时间衰减机制

**指数衰减**：`w(t) = e^(-λt)`

| 数据类型 | λ | 半衰期 | 说明 |
|---------|------|--------|------|
| 情绪信号 | 0.10 | ≈7天 | 快速遗忘 |
| 偏差评分 | 0.03 | ≈23天 | 习惯性，缓慢变化 |
| 风险画像 | 0.01 | ≈69天 | 人格稳定，极慢衰减 |

**更新公式**：`score_new = α × score_current + (1-α) × score_old × e^(-λΔt)`
```python
def update_with_decay(old_score, current_score, days_elapsed, data_type, alpha=0.3):
    decay_weight = math.exp(-DECAY_CONFIG[data_type]['lambda'] * days_elapsed)
    return max(0.0, min(1.0, alpha * current_score + (1-alpha) * old_score * decay_weight))
```

---

## 6. 认知偏差检测

### 6.1 处置效应
```python
def calculate_disposition_effect(trades):
    rg = len([t for t in trades if t.status=='closed' and t.pnl>0])
    ug = len([t for t in trades if t.status=='open' and t.unrealized_pnl>0])
    rl = len([t for t in trades if t.status=='closed' and t.pnl<0])
    ul = len([t for t in trades if t.status=='open' and t.unrealized_pnl<0])
    pgr = rg/(rg+ug) if (rg+ug)>0 else 0
    plr = rl/(rl+ul) if (rl+ul)>0 else 0
    if pgr+plr==0: return 0.0
    return min(1.0, max(0.0, (pgr-plr+1)/2))
```

### 6.2 过度自信
```python
def calculate_overconfidence(trades, portfolio):
    freq_score = min(1.0, (len(trades)/max(1,get_active_days(trades))) / 5.0)
    top3 = sum(sorted(portfolio.positions.values(), reverse=True)[:3]) / portfolio.total_value
    concentration_score = max(0, (top3-0.5)/0.5)
    winning = [t for t in trades if t.status=='closed' and t.pnl>0]
    losing = [t for t in trades if t.status=='closed' and t.pnl<0]
    if winning and losing:
        accuracy_bias = max(0, 1 - (sum(t.pnl for t in winning)/len(winning)) / abs(sum(t.pnl for t in losing)/len(losing)))
    else: accuracy_bias = 0.5
    return min(1.0, max(0.0, freq_score*0.4 + concentration_score*0.3 + accuracy_bias*0.3))
```

### 6.3 羊群效应
```python
def calculate_herding_bias(trades, market_data, social_reads):
    lsv = calculate_lsv(trades, market_data.trades)
    hot_overlap = calculate_hot_overlap([t.symbol for t in trades if t.status=='open'], market_data.hot_stocks)
    scores = [calculate_social_influence(t.timestamp, social_reads) for t in trades]
    valid = [s for s in scores if s>0]
    social = sum(valid)/max(1,len(valid))
    return min(1.0, max(0.0, lsv*0.4 + hot_overlap*0.3 + social*0.3))
```

### 6.4 损失厌恶
```python
def calculate_loss_aversion(trades, emotion_records):
    gain_e, loss_e = [], []
    for trade in trades:
        if trade.status != 'closed': continue
        nearby = get_emotions_around(trade.timestamp, window_min=30)
        if not nearby: continue
        impact = nearby[-1].score - nearby[0].score
        (gain_e if trade.pnl>0 else loss_e).append(abs(impact))
    if not gain_e or not loss_e: return 0.5
    avg_g, avg_l = sum(gain_e)/len(gain_e), sum(loss_e)/len(loss_e)
    if avg_g == 0: return 0.7
    return min(1.0, max(0.0, (avg_l/avg_g - 0.5) / 3.0))
```

### 6.5 锚定效应
```python
def calculate_anchoring_effect(trades, portfolio):
    signals = []
    for pos in portfolio.open_positions:
        change = (pos.current_price - pos.avg_cost) / pos.avg_cost
        if abs(change) < 0.02 and len(get_recent_trades(pos.symbol, days=7)) > 3: signals.append(0.7)
        if -0.01 < change < 0.03 and pos.has_sell_order_near_cost: signals.append(0.8)
        if change < -0.20 and pos.days_held > 30 and pos.trade_count == 1: signals.append(0.6)
    return min(1.0, max(0.0, sum(signals)/len(signals))) if signals else 0.2
```

### 6.6 干预阈值
```typescript
const BIAS_INTERVENTION_THRESHOLD = 0.7;
// score > 0.9 → critical, > 0.8 → high, > 0.7 → medium
```

---

## 7. 言行一致性检测

### 7.1 三个检测维度

**维度1：聊天 vs 交易** — 说冷静但1小时交易>5次→嘴硬型焦虑(severity=0.8)；说恐慌但大额买入→风险低估(0.7)

**维度2：风格 vs 操作** — 声明long_term但日内交易>30%→风格漂移(0.7)；声明conservative但最大持仓>60%→风险低估(0.6)

**维度3：计划 vs 执行** — 触发止损价但未卖出→止损失效(0.9)；达目标价反而加仓→风格漂移(0.7)

### 7.2 一致性分数

```python
def calculate_consistency(chat_check, style_check, plan_check):
    overall = chat_check.score*0.3 + style_check.score*0.3 + plan_check.score*0.4
    all_contradictions = chat_check.contradictions + style_check.contradictions + plan_check.contradictions
    dominant = max(all_contradictions, key=lambda c: c['severity'], default=None)
    return ConsistencyResult(overall_score=overall, dimensions=[chat_check, style_check, plan_check],
        dominant_contradiction=dominant['type'] if dominant else None,
        should_intervene=overall < 0.4, intervention_reason=dominant['description'] if dominant else None)
```

```typescript
interface ConsistencyCheck {
  dimension: 'chat_vs_trade'|'style_vs_operation'|'plan_vs_execution';
  contradictions: Array<{type: ContradictionType; description: string; severity: number}>;
  score: number;  // 0-1，越低矛盾越大
}
interface ConsistencyResult {
  overall_score: number; dimensions: ConsistencyCheck[];
  dominant_contradiction?: ContradictionType;
  should_intervene: boolean; intervention_reason?: string;
}
```

---

## 8. 干预系统

### 8.1 干预触发条件

| 触发类型 | 条件 | 严重度 |
|---------|------|--------|
| emotion_extreme | \|score\|>0.8 | >0.9→P0, 否则P1 |
| bias_significant | 任一偏差>0.7 | >0.9→P1, 否则P2 |
| consistency_low | score<0.4 | <0.2→P1, 否则P2 |
| behavior_anomaly | 存在异常信号 | σ>3→P1, 否则P2 |

**复合升级**：≥2个信号同时触发→最高severity升一级。

### 8.2 干预优先级

| 级别 | 触发条件 | 方式 | 响应 |
|------|---------|------|------|
| P0立即 | 恐慌抛售/冲动全仓 | 弹窗确认+冷静期 | <1s |
| P1强提醒 | 偏差严重 | 推送偏差解释+历史教训 | <5s |
| P2温和 | 情绪波动 | 对话嵌入 | 下次回复 |
| P3信息 | 轻微偏差 | 反面信息 | 下次回复 |

### 8.3 干预策略库（CBT + 行为金融学）

| 偏差/状态 | 干预技术 | 实现 |
|:---------|:---------|:-----|
| 恐慌卖出 | CBT认知重构 | "看看历史上类似跌幅后的恢复数据..." |
| 过度自信 | 概率教育 | "你过去6月预测准确率42%，感觉80%" |
| 从众追热 | 反向数据 | "散户买入占比已达历史95%分位..." |
| 损失厌恶 | 沉没成本教育 | "不管买入价，关键是现在值不值得持有" |
| 决策疲劳 | System 2唤起 | 强制确认+冷静倒计时 |

**Dual Process Theory**：小额/定投/止损→System 1；单笔>10%资产/杠杆/极端市场→System 2强制慢思考。

### 8.4 弹窗干预

```typescript
interface PopupIntervention {
  type: 'trade_confirmation'|'bias_warning'|'cool_down';
  title: string; message: string;
  data_visualization?: { chart_type: 'bar'|'line'|'comparison'; data: Record<string,number>; caption: string };
  actions: Array<{label: string; action: 'confirm'|'cancel'|'delay'|'view_details'}>;
  cooldown_minutes: number;
}
```

### 8.5 认知重构

```python
def generate_cognitive_reframe(bias_type, context):
    reframes = {
        'disposition_effect': "你持有{stock}盈利{gain}%。如果你现在没有持有，以目前价格你会买入吗？如果是，继续持有可能更好。",
        'loss_aversion': "你在{stock}亏损{loss}%。换个角度：这笔钱现在在你手里，你会买入这只股票吗？",
        'overconfidence': "你最近{win_count}笔都盈利了。统计显示连续盈利后容易出现过度自信失误。",
        'herding': "很多人都在买{stock}。请记住大众往往是错的。哪些基本面支撑你的买入？",
        'anchoring': "你在{buy_price}买入{stock}，现在{current_price}。买入价不应影响未来判断。",
    }
    return reframes.get(bias_type, "请冷静思考你的决策依据。").format(**context)
```

### 8.6 频率限制

```python
INTERVENTION_LIMITS = {
    'max_daily': 3, 'same_type_cooldown_hours': 24,
    'user_can_disable': True, 'global_cooldown_minutes': 30,
}
```

### 8.7 反馈闭环

```typescript
interface InterventionRecord {
  id: string; user_id: string; timestamp: string;
  trigger: InterventionTrigger; strategy: InterventionStrategy; content: string;
  user_response: { action: 'accepted'|'dismissed'|'ignored'|'delayed'; response_time_sec: number;
    subsequent_behavior_change?: { changed: boolean; description: string; time_to_change_min: number } };
  effectiveness: { immediate_score: number; delayed_score?: number; behavior_adjusted: boolean };
}
```

```python
def evaluate_intervention_effectiveness(record, user_state_after):
    score = 0.0
    action_scores = {'accepted': 1.0, 'delayed': 0.7, 'dismissed': 0.2, 'ignored': 0.0}
    score += action_scores.get(record.user_response.action, 0) * 0.3
    before, after = abs(record.trigger.score), abs(user_state_after.emotion_score)
    score += max(0, before-after)/before * 0.4 if before > 0 else 0
    if record.user_response.subsequent_behavior_change?.changed: score += 0.3
    return min(1.0, score)
```

---

## 9. 异常场景与保护机制

- **观察期保护**：新用户7天/20笔交易观察期，只采集不干预
- **数据不足降级**：交易不足时偏差返回0.5；情绪置信度<0.3不触发干预
- **极端市场保护**：大盘跌幅>5%时自动提升压力分数，增加干预敏感度
- **用户权益**：可查看/纠正/删除画像；可关闭特定干预；画像辅助决策不替代适当性审查
- **核心原则**：行为数据权重>自我描述；敏感特征需多次确认；所有结论记录来源/时间/可信度

---

## 10. 接口定义

### 10.1 输入接口

**POST /mental/chat**
```typescript
// Request: { user_id, message, session_id, timestamp, context?: { previous_messages[], active_stock? } }
// Response: { emotion: EmotionResult, consistency?: ConsistencyResult, intervention?: InterventionStrategy, profile_update: { emotion_recorded, bias_recalculated } }
```

**POST /mental/trade**
```typescript
// Request: { user_id, trade: { trade_id, symbol, direction, amount, quantity, price, timestamp, order_type }, portfolio_snapshot: { total_value, positions[] } }
// Response: { anomaly_detected, anomaly_signals[], bias_update: BiasScores, baseline_deviation[], intervention? }
```

**POST /mental/behavior**
```typescript
// Request: { user_id, event_type, timestamp, data }
// Response: { signals_extracted, emotion_signals[], intervention? }
```

**GET /mental/profile/{user_id}** → `{ user_id, profile: UserProfile, observation_status, generated_at }`

**GET /mental/state/{user_id}** → `{ user_id, current_state: { emotion, bias_scores, consistency_score, market_pressure, herding_score, anomaly_count }, risk_adjustment: { recommended_position_scale, reason }, active_interventions[], timestamp }`

### 10.2 输出接口

**向策略Agent**：
```typescript
interface StrategyAgentOutput {
  user_id: string;
  mental_state: { emotion: EmotionType; emotion_score: number; emotion_confidence: number };
  risk_adjustment: { position_scale: number; max_single_trade_pct: number; reason: string };
  bias_warnings: Array<{ bias_type: string; score: number; description: string; recommendation: string }>;
  timestamp: string;
}
```

**向前端**：
```typescript
interface FrontendOutput {
  user_id: string;
  emotion_display: { current_emotion: EmotionType; emotion_emoji: string;
    emotion_trend: Array<{date: string; dominant_emotion: EmotionType; score: number}> };
  intervention_content?: { show_popup: boolean; popup_data?: PopupIntervention; chat_embed?: string; notification?: string };
  profile_summary: { investment_style: string; risk_level: string;
    consistency_badge: '一致'|'轻微偏差'|'明显矛盾'; top_bias: string; observation_complete: boolean };
}
```

**向Orchestrator**：
```typescript
interface OrchestratorOutput {
  user_id: string; should_intervene: boolean;
  intervention_priority: 'P0'|'P1'|'P2'|'P3'|null;
  intervention_content: string|null;
  intervention_method: 'popup'|'chat_embed'|'push_notification'|'info_supplement'|null;
  context_for_orchestrator: { user_emotional_state: string; recommended_action: string; suppress_other_agents: boolean };
}
```

### 10.3 事件流处理

```
交易事件: 存储→更新基线→偏差重算(5大)→异常检测→一致性检测→干预判定
聊天事件: 情绪分析(词典→LLM)→更新情绪历史→一致性检测→词典反哺→干预判定
行为事件: 信号提取→行为→情绪映射→羊群检测→干预判定
定时任务: 每日00:00基线更新+画像衰减+计数重置；每周日全量重算+偏差衰减
```

---

## 11. 数据模型

**user_profiles**: user_id(PK), static_attributes(JSONB), dynamic_attributes(JSONB), behavioral_baseline(JSONB), statistics(JSONB), created_at, updated_at

**emotion_records**: id(PK), user_id(FK), emotion(VARCHAR), score(FLOAT), arousal(FLOAT), valence(FLOAT), confidence(FLOAT), source(VARCHAR), reasoning(TEXT), timestamp

**trade_records**: id(PK), user_id(FK), trade_id, symbol, direction, amount(DECIMAL), price(DECIMAL), market_condition, timestamp

**bias_scores**: id(PK), user_id(FK), disposition_effect(FLOAT), overconfidence(FLOAT), herding(FLOAT), loss_aversion(FLOAT), anchoring(FLOAT), calculated_at

**intervention_records**: id(PK), user_id(FK), trigger_type, severity, method, content(TEXT), user_action, effectiveness_score(FLOAT), timestamp

**emotion_lexicon**: id(PK), keyword, emotion, weight(FLOAT), confidence(FLOAT), source, usage_count(INT), hit_count(INT), last_validated

---

## 12. 技术选型与项目结构

| 方向 | 技术 | 用途 |
|------|------|------|
| 后端框架 | Python FastAPI / Node.js | API服务 |
| 情绪分析(快) | 动态词典匹配 | 90%请求<50ms |
| 情绪分析(精) | GPT-4o-mini LLM | 10%复杂文本<2s |
| 事件流 | Apache Kafka | 行为事件采集 |
| 流计算 | Apache Flink | 实时特征计算 |
| 特征存储 | Redis + ClickHouse | 热特征+时序 |
| 数据库 | PostgreSQL(JSONB) | 画像与记录 |
| 异常检测 | IsolationForest/PyOD | 行为异常 |
| 时序建模 | PyTorch LSTM/Transformer | 行为预测(Future) |
| 中文金融NLP | FinBERT2(Future) | 金融情感分析 |
| 金融大模型 | FinGPT/FinGLM(Future) | Agent推理 |

---

## 13. 非功能需求

- **性能**：词典<50ms、LLM<2s、偏差计算<500ms、干预判定<100ms、API P99<3s
- **成本**：词典命中率90%、LLM调用率10%、动态阈值调整
- **隐私**：加密存储、用户可查看/纠正/删除、心理特征需多次确认
- **扩展**：词典动态扩展、偏差模块可插拔、策略库配置化

---

## 14. MVP交付计划

**Phase 1（MVP — 4天Hackathon）**：词典+LLM双路径情绪分析、基础行为追踪与基线、五大偏差检测、言行一致性检测(三维度)、规则引擎干预(P0~P3)、基础API

**Phase 2（增强）**：LSTM/Transformer行为序列模型、HMM状态识别、言行一致性校正、情绪驱动动态策略、多源信号融合

**Phase 3（完整）**：多模态融合(可穿戴+文本+行为)、RL优化干预、在线学习、FinBERT2集成、完整预测层

---

## 15. 核心原则

1. **用户画像是持续更新的动态模型，不是一次性问卷**
2. **行为数据权重高于自我描述** — 用户说和做可能不一致
3. **敏感心理特征需多次数据确认**，不靠单次对话/行为判断
4. **所有画像结论记录来源、时间和可信度**
5. **用户可查看、纠正和删除画像信息**
6. **画像辅助决策，不替代适当性审查和风险控制**
7. **知止 — 知道何时该停止，才能在投资中保持理性**
