# 用户心智分析Agent PRD

> 版本：v1.0  
> 项目：Multi-Agent AI投顾系统（Hackathon 4天MVP）  
> 负责Agent：用户心智分析Agent（Mental Analysis Agent）  
> 最后更新：2026-07-24

---

## 1. 概述

### 1.1 产品定位

用户心智分析Agent是Multi-Agent AI投顾系统中负责**用户心理状态感知、画像构建、行为干预**的核心Agent。它不直接参与投资建议生成，而是作为系统的"心理顾问"角色，为策略Agent提供用户心理维度的决策依据，并在必要时直接干预用户的非理性行为。

### 1.2 目标

- **感知**：通过多源数据（聊天文本、交易行为、使用模式）实时分析用户当前心智状态
- **识别**：检测认知偏差（处置效应、过度自信、羊群效应、损失厌恶、锚定效应）
- **检测**：发现用户言行不一致（说冷静但疯狂交易、说长期但日内操作）
- **辅助**：向策略Agent输出心理状态和风险调整建议，辅助交易策略调整
- **干预**：在用户出现极端情绪或严重偏差时，主动介入干预

### 1.3 MVP范围（4天Hackathon）

聚焦**核心链路可演示**：

```
用户聊天 → 情绪分析 → 画像更新 → 一致性检测 → 触发干预
用户交易 → 偏差计算 → 异常检测 → 触发干预
```

---

## 2. 系统架构

### 2.1 三大模块

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户心智分析Agent                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐      │
│  │                     感知模块（Perception）                  │      │
│  │  ┌─────────────┐ ┌─────────────┐ ┌──────────┐ ┌────────┐ │      │
│  │  │ 聊天情绪分析 │ │ 行为信号采集 │ │ 羊群效应  │ │ 市场   │ │      │
│  │  │             │ │             │ │  检测    │ │ 压力   │ │      │
│  │  └──────┬──────┘ └──────┬──────┘ └────┬─────┘ └───┬────┘ │      │
│  │         │               │             │           │       │      │
│  └─────────┼───────────────┼─────────────┼───────────┼───────┘      │
│            │               │             │           │              │
│            ▼               ▼             ▼           ▼              │
│  ┌───────────────────────────────────────────────────────────┐      │
│  │                   画像模块（Profiling）                     │      │
│  │  ┌─────────────┐ ┌─────────────┐ ┌──────────┐ ┌────────┐ │      │
│  │  │ 用户画像存储 │ │ 行为基线管理 │ │ 认知偏差  │ │ 言行   │ │      │
│  │  │             │ │             │ │  档案    │ │ 一致性 │ │      │
│  │  └─────────────┘ └─────────────┘ └──────────┘ └────────┘ │      │
│  └───────────────────────────────────────────────────────────┘      │
│            │                                                        │
│            ▼                                                        │
│  ┌───────────────────────────────────────────────────────────┐      │
│  │                   干预模块（Intervention）                  │      │
│  │  ┌─────────────┐ ┌─────────────┐ ┌──────────┐ ┌────────┐ │      │
│  │  │  触发判定   │ │  策略选择   │ │  执行    │ │ 反馈   │ │      │
│  │  │             │ │             │ │  引擎    │ │ 闭环   │ │      │
│  │  └─────────────┘ └─────────────┘ └──────────┘ └────────┘ │      │
│  └───────────────────────────────────────────────────────────┘      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
            │                    │                    │
            ▼                    ▼                    ▼
    ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐
    │  策略Agent   │    │   前端展示   │    │  Orchestrator    │
    │mental_state  │    │emotion_display│    │should_intervene  │
    │risk_adjust   │    │intervention  │    │intervention_priority│
    │bias_warnings │    │profile_summary│   │intervention_content│
    └──────────────┘    └──────────────┘    └──────────────────┘
```

### 2.2 数据流方向

```
输入层：
  聊天文本 ──→ 感知模块.情绪分析 ──→ 画像模块.情绪记录
  交易事件 ──→ 感知模块.行为采集 ──→ 画像模块.偏差计算 + 基线更新
  市场数据 ──→ 感知模块.市场压力 ──→ 画像模块.环境压力评分

处理层：
  情绪记录 + 偏差分数 + 基线偏离 ──→ 画像模块.一致性检测
  画像综合状态 ──→ 干预模块.触发判定

输出层：
  干预模块 ──→ 策略Agent（心理状态 + 风险调整建议）
  干预模块 ──→ 前端（情绪展示 + 干预内容）
  干预模块 ──→ Orchestrator（是否干预 + 优先级 + 内容）
```

---

## 3. 感知模块

### 3.1 聊天情绪分析

#### 3.1.1 双层架构

```
用户消息输入
     │
     ▼
┌─────────────────┐
│  动态词典匹配    │  ← 快速路径（<50ms）
│  Lexicon Match  │
└────────┬────────┘
         │
    confidence >= 0.5
    且文本长度 <= 50字
    且无反讽/隐喻特征？
         │
    ┌────┴────┐
    │Yes      │No
    ▼         ▼
  输出结果  ┌─────────────────┐
           │  LLM 精确分析    │  ← 精确路径（<2s）
           │  GPT-4o-mini    │
           └────────┬────────┘
                    │
                    ▼
                 输出结果
                 + 反哺词典
```

#### 3.1.2 动态词典设计

**初始词典分类**（6类，每类15-20个关键词）：

```json
{
  "贪婪": {
    "keywords": [
      "加仓", "抄底", "全仓", "追涨", "牛市来了", "暴涨", "起飞",
      "翻倍", "梭哈", "重仓", "必须买", "再不买就晚了", "FOMO",
      "错过", "上车", "冲冲冲", "干就完了", "稳赚", "血赚"
    ],
    "description": "追涨、FOMO、冲动加仓意愿"
  },
  "恐慌": {
    "keywords": [
      "崩盘", "暴跌", "割肉", "清仓", "完了", "血亏", "逃命",
      "熊市", "黑天鹅", "爆仓", "赶紧卖", "跑", "完蛋", "亏麻了",
      "要崩", "大跌", "跳水", "末日"
    ],
    "description": "害怕巨亏、想立刻止损、觉得要崩盘"
  },
  "焦虑": {
    "keywords": [
      "怎么办", "纠结", "犹豫", "不确定", "要不要", "好难",
      "不知道该", "万一", "担心", "害怕", "紧张", "睡不着",
      "心慌", "拿不准", "好烦", "焦虑"
    ],
    "description": "不确定、纠结、犹豫不决"
  },
  "乐观": {
    "keywords": [
      "看好", "会涨", "有信心", "没问题", "长期持有", "价值投资",
      "基本面好", "前景不错", "值得期待", "稳了", "乐观", "机会",
      "底部", "反转", "向好"
    ],
    "description": "看好后市、对持仓有信心"
  },
  "沮丧": {
    "keywords": [
      "亏了", "后悔", "不该", "自责", "无力", "放弃", "算了",
      "没意思", "不玩了", "套牢", "深套", "麻木了", "绝望",
      "难受", "心痛", "郁闷"
    ],
    "description": "已亏损、自责、后悔、无力感"
  },
  "冷静": {
    "keywords": [
      "分析一下", "看看数据", "基本面", "技术面", "估值", "PE",
      "仓位管理", "风险控制", "分散", "对冲", "理性", "客观",
      "计划", "策略", "纪律"
    ],
    "description": "理性分析、不带情绪、客观评估"
  }
}
```

**词典数据结构**：

```typescript
interface LexiconEntry {
  keyword: string;              // 关键词
  emotion: EmotionType;         // 情绪类别
  weight: number;               // 权重 0-1，表示该词的情绪强度
  confidence: number;           // 置信度 0-1，表示该词分类的可靠程度
  source: 'initial' | 'llm_feedback' | 'behavior_validated' | 'community';  // 来源
  last_validated: string;       // ISO 8601 最后验证时间
  usage_count: number;          // 使用次数
  hit_count: number;            // 命中次数
}

type EmotionType = '贪婪' | '恐慌' | '焦虑' | '乐观' | '沮丧' | '冷静';

// 词典存储结构
interface EmotionLexicon {
  version: string;
  updated_at: string;
  entries: LexiconEntry[];
}
```

**词典更新机制**（MVP阶段仅实现LLM反哺）：

| 更新机制 | 触发条件 | 实现方式 | MVP状态 |
|---------|---------|---------|---------|
| LLM反哺 | LLM分析置信度>0.9且词典未收录 | 提取关键词加入词典，初始confidence=0.5 | ✅ 实现 |
| 用户行为验证 | 用户说了某词后的行为与情绪匹配 | 行为确认后更新weight和confidence | ⏳ Nice to Have |
| 社区热词监测 | 监控社区高频新词 | 爬取+频率统计 | ❌ Future |

**LLM反哺伪代码**：

```python
def update_lexicon_from_llm(text: str, llm_result: EmotionResult, lexicon: EmotionLexicon):
    """当LLM高置信度分析完成后，尝试从文本中提取新关键词反哺词典"""
    if llm_result.confidence < 0.9:
        return
    
    # 分词并检查是否已在词典中
    tokens = tokenize(text)
    existing_keywords = {entry.keyword for entry in lexicon.entries}
    
    for token in tokens:
        if token not in existing_keywords and len(token) >= 2:
            # 提取新关键词
            new_entry = LexiconEntry(
                keyword=token,
                emotion=llm_result.emotion,
                weight=abs(llm_result.score),
                confidence=0.5,  # 初始置信度较低，需要后续验证
                source='llm_feedback',
                last_validated=now(),
                usage_count=1,
                hit_count=0
            )
            lexicon.entries.append(new_entry)
```

#### 3.1.3 LLM分析

**触发条件**：

```python
def should_use_llm(text: str, lexicon_result: Optional[LexiconResult]) -> bool:
    """判断是否需要调用LLM进行精确分析"""
    # 词典无结果或置信度低
    if lexicon_result is None or lexicon_result.confidence < 0.5:
        return True
    # 文本较长，可能包含复杂情绪
    if len(text) > 50:
        return True
    # 包含反讽/隐喻特征
    irony_patterns = ['呵呵', '真是', '太好了', '真棒', '呵呵哒', '你说呢', '有意思']
    if any(p in text for p in irony_patterns):
        return True
    return False
```

**Prompt设计**：

```text
你是一个专业的投资心理分析师。请分析以下用户消息中体现的情绪状态。

用户消息：{user_message}

用户画像背景：
- 投资经验：{experience_level}
- 风险偏好：{risk_tolerance}
- 近期情绪：{recent_emotion_summary}

请严格按以下JSON格式输出：
{
  "emotion": "贪婪|恐慌|焦虑|乐观|沮丧|冷静",
  "score": <float, 0到1, 该情绪的强烈程度>,
  "arousal": <float, 0到1, 用户当前的心理激活/冲动程度>,
  "valence": <float, -1到1, 情绪效价，正面为正、负面为负>,
  "reasoning": "<string, 50字以内的分析理由>",
  "confidence": <float, 0到1, 你对这个判断的确信度>,
  "sub_emotions": [<可选, 次要情绪列表>]
}

字段说明：
- emotion: 直接判定情绪类别，这是最核心的输出
- score: 情绪强度（0.3=轻微, 0.5=中等, 0.7=强烈, 0.9=极端）
- arousal: 唤醒度（0.2=消极低落, 0.5=一般, 0.8=高度激动/冲动）
  - 贪婪/恐慌应为高唤醒(>0.7)
  - 乐观/焦虑应为中唤醒(0.4~0.7)
  - 冷静/沮丧应为低唤醒(<0.4)
- valence: 效价方向参考（贪婪/乐观/冷静为正，焦虑/沮丧/恐慌为负）
```

**成本控制策略**：

```python
# 目标：90%请求词典消化，10%调LLM
# 监控指标
LEXICON_HIT_RATE_TARGET = 0.90
LLM_CALL_RATE_TARGET = 0.10

# 动态调整词典置信度阈值
def adjust_lexicon_threshold(metrics: dict) -> float:
    """根据LLM调用比例动态调整词典置信度阈值"""
    current_llm_rate = metrics['llm_calls'] / metrics['total_requests']
    threshold = 0.5  # 默认阈值
    
    if current_llm_rate > LLM_CALL_RATE_TARGET:
        # LLM调用过多，降低阈值让更多请求走词典
        threshold = max(0.3, threshold - 0.05)
    elif current_llm_rate < LLM_CALL_RATE_TARGET * 0.5:
        # LLM调用过少，可以适当提高阈值保证质量
        threshold = min(0.7, threshold + 0.05)
    
    return threshold
```

#### 3.1.4 情绪类别定义

> **核心设计原则**：情绪类别由词典/LLM直接判定，`score`仅表示该情绪的强度（0~1），用于辅助判断是否触发干预阈值。**禁止**反向使用score推断类别。

**情绪二维模型（基于Russell环形模型）**

本系统采用效价(Valence) × 唤醒度(Arousal)二维模型定义情绪空间：

```
                高唤醒(Arousal)
                     ↑
          恐慌       │       贪婪
       (-V, +A)     │    (+V, +A)
                     │
    焦虑             │          乐观
    (-V, mid-A)     │       (+V, mid-A)
                     │
  负效价 ←───────────┼───────────→ 正效价
                     │
          沮丧       │       冷静
       (-V, -A)     │    (+V/-V, -A)
                     │
                低唤醒
```

**六类情绪定义**

| 类别 | 英文标识 | 效价(Valence) | 唤醒度(Arousal) | 典型场景 | 行为倾向 | 区分要点 |
|------|---------|:---:|:---:|---------|---------|---------|
| 贪婪 | greed | 正(+) | 高(0.7~1.0) | 追涨、FOMO、冲动加仓 | 过度交易、集中持仓 | vs乐观：有急迫行动冲动 |
| 乐观 | optimism | 正(+) | 中(0.3~0.6) | 看好后市、对持仓有信心 | 持有不动、适度加仓 | vs贪婪：平稳无冲动 |
| 冷静 | calm | 中性(0) | 低(0.0~0.3) | 理性分析、客观评估 | 按计划执行、理性决策 | 无明显情绪倾向 |
| 焦虑 | anxiety | 负(-) | 中-高(0.5~0.8) | 不确定、纠结、犹豫 | 决策延迟、频繁修改订单 | vs恐慌：未到极端行动 |
| 沮丧 | frustration | 负(-) | 低(0.1~0.4) | 已亏损、自责、后悔 | 放弃操作、或报复性交易 | vs恐慌：消极而非激动 |
| 恐慌 | panic | 负(-) | 高(0.7~1.0) | 害怕巨亏、想立刻止损 | 恐慌抛售、频繁查看 | vs沮丧：极度激动+行动冲动 |

**score字段说明**

- `score`：情绪强度，统一为 **0~1**，表示该情绪类别的确定程度和强烈程度
  - 0.3~0.5：轻微（信号存在但不显著）
  - 0.5~0.7：中等（明确的情绪表现）
  - 0.7~0.9：强烈（显著的情绪状态）
  - 0.9~1.0：极端（需要立即关注）
- `score` **不携带正负号**，正负由emotion类别本身隐含
- 干预阈值基于score：score > 0.7 触发P2干预，score > 0.9 触发P0/P1干预

#### 3.1.5 输出格式

```typescript
interface EmotionResult {
  emotion: EmotionType;           // 情绪类别（由词典/LLM直接判定，不由score推断）
  score: number;                  // 情绪强度 0~1（该情绪有多强烈）
  arousal: number;                // 唤醒度 0~1（用户的激活/冲动程度）
  valence: number;                // 效价 -1~1（正面/负面情绪方向，辅助参考）
  confidence: number;             // 置信度 0~1（分析结果的可靠程度）
  source: 'lexicon' | 'llm';     // 分析来源
  reasoning?: string;             // LLM分析理由（仅LLM路径）
  timestamp: string;              // ISO 8601 时间戳
  sub_emotions?: EmotionType[];   // 次要情绪（仅LLM路径）
}

// 设计原则：
// 1. emotion类别由词典匹配或LLM直接输出，是第一性判定
// 2. score表示强度，用于触发干预阈值，不用于反推类别
// 3. arousal用于区分同效价下的不同情绪（如贪婪vs乐观、恐慌vs沮丧）
// 4. valence为辅助参考维度，供下游模块使用

// 词典匹配结果（内部使用）
interface LexiconResult {
  matched_keywords: Array<{
    keyword: string;
    emotion: EmotionType;
    weight: number;
  }>;
  confidence: number;             // 基于匹配数量和权重的综合置信度
  dominant_emotion: EmotionType;  // 主导情绪
  score: number;                  // 情绪强度 0~1
  arousal: number;                // 唤醒度 0~1（由情绪类别映射）
  valence: number;                // 效价 -1~1（由情绪类别映射，乘以强度调节）
}
```

**词典匹配算法伪代码**：

```python
def lexicon_analyze(text: str, lexicon: EmotionLexicon) -> LexiconResult:
    """基于动态词典的情绪分析"""
    matched = []
    emotion_scores = defaultdict(list)
    
    for entry in lexicon.entries:
        if entry.keyword in text:
            matched.append({
                'keyword': entry.keyword,
                'emotion': entry.emotion,
                'weight': entry.weight
            })
            emotion_scores[entry.emotion].append(entry.weight)
    
    if not matched:
        return LexiconResult(matched_keywords=[], confidence=0.0, 
                            dominant_emotion='冷静', score=0.0)
    
    # 计算主导情绪
    emotion_avg = {}
    for emotion, weights in emotion_scores.items():
        emotion_avg[emotion] = sum(weights) / len(weights)
    
    dominant = max(emotion_avg, key=emotion_avg.get)
    
    # 唤醒度映射（基于情绪类别的固有属性）
    arousal_map = {'贪婪': 0.85, '恐慌': 0.9, '焦虑': 0.65, 
                   '乐观': 0.45, '沮丧': 0.25, '冷静': 0.15}
    
    # 效价映射
    valence_map = {'贪婪': 0.7, '恐慌': -0.9, '焦虑': -0.4, 
                   '乐观': 0.6, '沮丧': -0.5, '冷静': 0.1}
    
    # score改为0~1强度值
    score = emotion_avg[dominant]  # 直接用权重平均作为强度
    
    # 置信度：匹配词越多、权重越高，置信度越高
    confidence = min(1.0, len(matched) * 0.2 + sum(m['weight'] for m in matched) / len(matched) * 0.5)
    
    return LexiconResult(
        matched_keywords=matched,
        confidence=confidence,
        dominant_emotion=dominant,
        score=score,                              # 0~1 强度
        arousal=arousal_map[dominant],            # 唤醒度
        valence=valence_map[dominant] * score     # 效价（乘以强度调节）
    )
```

---

### 3.2 行为信号采集

#### 3.2.1 交易行为信号

```typescript
interface TradeSignal {
  user_id: string;
  trade_id: string;
  timestamp: string;              // ISO 8601
  
  // 原始交易数据
  symbol: string;                 // 股票代码
  direction: 'buy' | 'sell';      // 买卖方向
  amount: number;                 // 交易金额
  quantity: number;               // 交易数量
  price: number;                  // 成交价格
  
  // 衍生指标（Agent计算）
  trade_frequency_1h: number;     // 过去1小时交易次数
  trade_frequency_24h: number;    // 过去24小时交易次数
  position_concentration: number; // 该股票占总持仓比例 0-1
  holding_days: number;           // 持仓天数（卖出时计算）
  stop_loss_executed: boolean;    // 是否执行了预设止损
  
  // 上下文
  market_condition: 'up' | 'down' | 'flat';  // 当时大盘状态
  stock_change_pct: number;       // 该股票当日涨跌幅
}
```

#### 3.2.2 使用模式信号

```typescript
interface UsageSignal {
  user_id: string;
  timestamp: string;
  
  // 访问模式
  session_start: string;          // 会话开始时间
  session_duration_min: number;   // 会话时长（分钟）
  is_late_night: boolean;         // 是否深夜访问（23:00-06:00）
  is_pre_market: boolean;         // 是否开盘前访问（08:00-09:30）
  
  // 交互行为
  page_stay_times: Array<{        // 页面停留时间
    page: string;
    duration_sec: number;
  }>;
  search_keywords: string[];      // 搜索关键词
  watchlist_changes: Array<{      // 自选股变动
    action: 'add' | 'remove';
    symbol: string;
  }>;
  notification_click_rate: number; // 通知点击率 0-1
  
  // 刷新频率
  portfolio_refresh_count: number; // 持仓页面刷新次数
  price_check_frequency: number;   // 每分钟查看行情次数
}
```

#### 3.2.3 行为信号 → 情绪映射规则表

| 行为信号 | 条件 | 推断情绪 | 强度 | 置信度 |
|---------|------|---------|------|--------|
| 交易频率突增 | freq > baseline × 3 | 贪婪/恐慌 | 0.8 | 0.6 |
| 深夜频繁查看 | 23:00-06:00 且 refresh > 10次/小时 | 焦虑 | 0.6 | 0.7 |
| 开盘前密集操作 | 08:00-09:30 且 trade_count > 3 | 贪婪/焦虑 | 0.7 | 0.5 |
| 持仓页面高频刷新 | refresh > 20次/小时 | 焦虑/恐慌 | 0.5 | 0.6 |
| 大量删除自选股 | watchlist_remove > 5个/天 | 沮丧 | 0.6 | 0.5 |
| 搜索"止损""割肉" | 关键词命中 | 恐慌/沮丧 | 0.7 | 0.8 |
| 搜索"牛股""暴涨" | 关键词命中 | 贪婪 | 0.7 | 0.8 |
| 快速买入后立刻卖出 | 同股票 买卖间隔 < 10分钟 | 焦虑/恐慌 | 0.8 | 0.7 |
| 止损单未执行 | 触发止损价但未卖出 | 贪婪/沮丧 | 0.6 | 0.6 |
| 单笔交易金额突增 | amount > baseline × 3 | 贪婪 | 0.7 | 0.5 |
| 持仓集中度过高 | top1_position > 80% | 贪婪/过度自信 | 0.6 | 0.7 |
| 长时间未操作后突然活跃 | dormant_days > 7 且 突然交易 | 冲动/贪婪 | 0.7 | 0.6 |
| 连续亏损后继续加仓 | loss_streak >= 3 且 direction=buy | 沮丧/报复性交易 | 0.8 | 0.7 |
| 通知全部忽略 | click_rate < 0.1 持续3天 | 沮丧/放弃 | 0.5 | 0.4 |
| 反复查看亏损持仓 | 查看亏损股票 > 5次/天 | 沮丧/损失厌恶 | 0.6 | 0.6 |

**映射规则伪代码**：

```python
def behavior_to_emotion(trade_signal: TradeSignal, usage_signal: UsageSignal, 
                        baseline: BehaviorBaseline) -> List[BehaviorEmotionSignal]:
    """将行为信号转换为情绪推断"""
    signals = []
    
    # 交易频率突增
    if trade_signal.trade_frequency_24h > baseline.avg_daily_trades * 3:
        signals.append(BehaviorEmotionSignal(
            emotion='贪婪' if trade_signal.direction == 'buy' else '恐慌',
            score=0.8,
            confidence=0.6,
            trigger='trade_frequency_spike'
        ))
    
    # 深夜频繁查看
    if usage_signal.is_late_night and usage_signal.portfolio_refresh_count > 10:
        signals.append(BehaviorEmotionSignal(
            emotion='焦虑',
            score=-0.4,
            confidence=0.7,
            trigger='late_night_check'
        ))
    
    # 持仓集中度过高
    if trade_signal.position_concentration > 0.8:
        signals.append(BehaviorEmotionSignal(
            emotion='贪婪',
            score=0.6,
            confidence=0.7,
            trigger='high_concentration'
        ))
    
    # 连续亏损后加仓
    if trade_signal.direction == 'buy' and get_loss_streak(trade_signal.user_id) >= 3:
        signals.append(BehaviorEmotionSignal(
            emotion='沮丧',
            score=-0.6,
            confidence=0.7,
            trigger='revenge_trading'
        ))
    
    return signals
```

---

### 3.3 羊群效应检测

#### 3.3.1 检测维度

**维度1：交易方向与市场大众一致性（简化LSV指标）**

```python
def calculate_lsv(user_trades: List[Trade], market_trades: List[MarketTrade]) -> float:
    """
    简化版LSV（Lakonishok, Shleifer, Vishny）羊群效应指标
    LSV = |p_user - p_market| 
    p_user = 用户买入比例（买入次数/总交易次数）
    p_market = 市场买入比例（该股票全市场买入量/总交易量）
    """
    if not user_trades:
        return 0.0
    
    user_buy_ratio = sum(1 for t in user_trades if t.direction == 'buy') / len(user_trades)
    
    market_buy_volume = sum(t.volume for t in market_trades if t.direction == 'buy')
    market_total_volume = sum(t.volume for t in market_trades)
    market_buy_ratio = market_buy_volume / market_total_volume if market_total_volume > 0 else 0.5
    
    # LSV越接近0说明越跟随市场，越接近1说明越独立
    lsv = abs(user_buy_ratio - market_buy_ratio)
    herding_score = 1.0 - lsv  # 转换为羊群分数，越高越从众
    
    return herding_score
```

**维度2：持仓与热门推荐重合度**

```python
def calculate_hot_overlap(user_holdings: List[str], hot_stocks: List[str]) -> float:
    """计算用户持仓与热门推荐股票的重合度"""
    if not user_holdings:
        return 0.0
    
    overlap = len(set(user_holdings) & set(hot_stocks))
    overlap_ratio = overlap / len(user_holdings)
    
    return overlap_ratio  # 0-1，越高说明越跟随热门
```

**维度3：决策时间与社交信息获取的时间相关性**

```python
def calculate_social_influence(trade_time: datetime, 
                               social_reads: List[SocialReadEvent]) -> float:
    """
    检测交易决策是否受到社交信息影响
    如果在阅读社交信息后30分钟内进行交易，认为可能受影响
    """
    influence_score = 0.0
    
    for read in social_reads:
        time_diff = (trade_time - read.timestamp).total_seconds() / 60
        if 0 < time_diff <= 30:
            # 时间越近影响越大
            influence_score = max(influence_score, 1.0 - (time_diff / 30))
    
    return influence_score
```

#### 3.3.2 输出格式

```typescript
interface HerdingResult {
  herding_score: number;          // 0-1，越高越从众
  herding_type: '跟买' | '跟卖' | '无';  // 羊群类型
  dimensions: {
    lsv_score: number;            // 交易方向一致性
    hot_overlap: number;          // 热门重合度
    social_influence: number;     // 社交影响度
  };
  confidence: number;             // 置信度
  timestamp: string;
}
```

---

### 3.4 市场环境压力

```typescript
interface MarketPressure {
  market_pressure: number;        // 0-1，综合市场压力分数
  components: {
    portfolio_weighted_change: number;   // 用户持仓板块加权涨跌幅
    market_volatility: number;           // 大盘波动率（当日振幅）
    negative_news_density: number;       // 利空新闻密度 0-1
  };
  timestamp: string;
}
```

**计算伪代码**：

```python
def calculate_market_pressure(user_holdings: List[Holding], 
                              market_data: MarketData,
                              news_data: NewsData) -> MarketPressure:
    """计算用户面临的市场环境压力"""
    
    # 1. 用户持仓板块加权涨跌幅
    total_value = sum(h.quantity * h.current_price for h in user_holdings)
    weighted_change = sum(
        (h.quantity * h.current_price / total_value) * h.daily_change_pct 
        for h in user_holdings
    ) if total_value > 0 else 0
    
    # 涨跌幅转换为压力分数：大跌=高压力
    # -5% -> 1.0, 0% -> 0.5, +5% -> 0.0
    portfolio_pressure = max(0, min(1, 0.5 - weighted_change / 10))
    
    # 2. 大盘波动率
    market_amplitude = (market_data.high - market_data.low) / market_data.open
    # 振幅3%以上算高波动
    market_vol_pressure = min(1.0, market_amplitude / 0.03)
    
    # 3. 利空新闻密度
    negative_news_count = news_data.count_negative_news(hours=24)
    total_news_count = news_data.count_total_news(hours=24)
    negative_density = negative_news_count / total_news_count if total_news_count > 0 else 0
    
    # 综合压力（加权平均）
    market_pressure = (
        portfolio_pressure * 0.5 +    # 持仓压力权重最大
        market_vol_pressure * 0.3 +    # 大盘波动次之
        negative_density * 0.2         # 新闻密度最低
    )
    
    return MarketPressure(
        market_pressure=market_pressure,
        components={
            'portfolio_weighted_change': portfolio_pressure,
            'market_volatility': market_vol_pressure,
            'negative_news_density': negative_density
        },
        timestamp=now()
    )
```

---

## 4. 画像模块

### 4.1 用户画像数据结构

```typescript
interface UserProfile {
  // === 元信息 ===
  user_id: string;
  created_at: string;             // ISO 8601
  updated_at: string;
  
  // === 静态属性（低频更新） ===
  static_attributes: {
    risk_tolerance: number;       // 风险承受能力 1-10（来自问卷）
    investment_style: 'conservative' | 'balanced' | 'aggressive' | 'speculative';
    experience_level: 'beginner' | 'intermediate' | 'advanced' | 'expert';
    investment_horizon: 'day_trade' | 'short_term' | 'medium_term' | 'long_term';
    preferred_sectors: string[];  // 偏好板块
    max_single_position_pct: number; // 最大单只持仓比例偏好
  };
  
  // === 动态属性（高频更新） ===
  dynamic_attributes: {
    current_emotion: EmotionResult;           // 当前情绪状态
    emotion_history: Array<{
      emotion: EmotionType;
      score: number;
      timestamp: string;
      source: string;
    }>;                                       // 情绪历史（最近50条）
    bias_scores: {
      disposition_effect: number;             // 处置效应 0-1
      overconfidence: number;                 // 过度自信 0-1
      herding: number;                        // 羊群效应 0-1
      loss_aversion: number;                  // 损失厌恶 0-1
      anchoring: number;                      // 锚定效应 0-1
    };
    consistency_score: number;                // 言行一致性 0-1
    contradiction_type?: ContradictionType;   // 当前矛盾类型
  };
  
  // === 行为基线 ===
  behavioral_baseline: {
    baseline_trade_freq: number;              // 日均交易频率
    baseline_holding_days: number;            // 平均持仓天数
    baseline_single_amount_pct: number;       // 平均单笔金额占比
    baseline_active_hours: number[];          // 常用交易时间段 [9, 10, 14, 15]
    baseline_emotion_volatility: number;      // 情绪波动幅度（标准差）
    baseline_risk_asset_pct: number;          // 风险资产占比
    observation_period_complete: boolean;     // 观察期是否完成
    observation_start: string;                // 观察期开始时间
    observation_trade_count: number;          // 观察期内交易次数
  };
  
  // === 统计信息 ===
  statistics: {
    total_trades: number;
    total_chat_messages: number;
    intervention_count: number;
    intervention_acceptance_rate: number;     // 干预接受率
    days_active: number;
  };
}

type ContradictionType = '嘴硬型焦虑' | '风格漂移' | '止损失效' | '风险低估';
```

**JSON Schema**：

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "UserProfile",
  "type": "object",
  "required": ["user_id", "created_at", "updated_at", "static_attributes", "dynamic_attributes", "behavioral_baseline"],
  "properties": {
    "user_id": { "type": "string", "format": "uuid" },
    "created_at": { "type": "string", "format": "date-time" },
    "updated_at": { "type": "string", "format": "date-time" },
    "static_attributes": {
      "type": "object",
      "required": ["risk_tolerance", "investment_style", "experience_level"],
      "properties": {
        "risk_tolerance": { "type": "number", "minimum": 1, "maximum": 10 },
        "investment_style": {
          "type": "string",
          "enum": ["conservative", "balanced", "aggressive", "speculative"]
        },
        "experience_level": {
          "type": "string",
          "enum": ["beginner", "intermediate", "advanced", "expert"]
        },
        "investment_horizon": {
          "type": "string",
          "enum": ["day_trade", "short_term", "medium_term", "long_term"]
        },
        "preferred_sectors": {
          "type": "array",
          "items": { "type": "string" }
        },
        "max_single_position_pct": { "type": "number", "minimum": 0, "maximum": 1 }
      }
    },
    "dynamic_attributes": {
      "type": "object",
      "properties": {
        "current_emotion": { "$ref": "#/definitions/EmotionResult" },
        "emotion_history": {
          "type": "array",
          "maxItems": 50,
          "items": {
            "type": "object",
            "properties": {
              "emotion": { "type": "string", "enum": ["贪婪", "恐慌", "焦虑", "乐观", "沮丧", "冷静"] },
              "score": { "type": "number", "minimum": -1, "maximum": 1 },
              "timestamp": { "type": "string", "format": "date-time" },
              "source": { "type": "string" }
            }
          }
        },
        "bias_scores": {
          "type": "object",
          "properties": {
            "disposition_effect": { "type": "number", "minimum": 0, "maximum": 1 },
            "overconfidence": { "type": "number", "minimum": 0, "maximum": 1 },
            "herding": { "type": "number", "minimum": 0, "maximum": 1 },
            "loss_aversion": { "type": "number", "minimum": 0, "maximum": 1 },
            "anchoring": { "type": "number", "minimum": 0, "maximum": 1 }
          }
        },
        "consistency_score": { "type": "number", "minimum": 0, "maximum": 1 },
        "contradiction_type": {
          "type": "string",
          "enum": ["嘴硬型焦虑", "风格漂移", "止损失效", "风险低估"]
        }
      }
    },
    "behavioral_baseline": {
      "type": "object",
      "properties": {
        "baseline_trade_freq": { "type": "number" },
        "baseline_holding_days": { "type": "number" },
        "baseline_single_amount_pct": { "type": "number" },
        "baseline_active_hours": { "type": "array", "items": { "type": "integer" } },
        "baseline_emotion_volatility": { "type": "number" },
        "baseline_risk_asset_pct": { "type": "number" },
        "observation_period_complete": { "type": "boolean" },
        "observation_start": { "type": "string", "format": "date-time" },
        "observation_trade_count": { "type": "integer" }
      }
    }
  },
  "definitions": {
    "EmotionResult": {
      "type": "object",
      "properties": {
        "emotion": { "type": "string", "enum": ["贪婪", "恐慌", "焦虑", "乐观", "沮丧", "冷静"] },
        "score": { "type": "number", "minimum": -1, "maximum": 1 },
        "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
        "source": { "type": "string", "enum": ["lexicon", "llm"] },
        "reasoning": { "type": "string" },
        "timestamp": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

---

### 4.2 个人行为基线（观察期）

#### 4.2.1 观察期定义

```python
# 观察期配置
OBSERVATION_CONFIG = {
    'min_days': 7,              # 最少观察天数
    'min_trades': 20,           # 最少观察交易次数
    'end_condition': 'whichever_first',  # 满足任一条件即结束
}

def is_observation_complete(user: UserProfile) -> bool:
    """判断观察期是否完成"""
    days_since_start = (now() - user.behavioral_baseline.observation_start).days
    trade_count = user.behavioral_baseline.observation_trade_count
    
    # 7天或20笔交易，取先到的
    return days_since_start >= 7 or trade_count >= 20
```

#### 4.2.2 观察期行为规则

```python
def handle_observation_period(user: UserProfile, event: Event):
    """观察期内的处理逻辑"""
    if not user.behavioral_baseline.observation_period_complete:
        # 观察期内：只采集数据，不做干预
        collect_data(event)
        update_baseline_incrementally(user, event)
        
        # 检查是否可以结束观察期
        if is_observation_complete(user):
            finalize_baseline(user)
            user.behavioral_baseline.observation_period_complete = True
        
        # 不触发任何干预
        return None
    
    # 观察期结束后：正常处理
    return process_normally(user, event)
```

#### 4.2.3 基线指标计算

```python
class BehaviorBaseline:
    """行为基线数据结构"""
    baseline_trade_freq: float        # 日均交易频率（笔/天）
    baseline_holding_days: float      # 平均持仓天数
    baseline_single_amount_pct: float # 平均单笔金额占总资产比例
    baseline_active_hours: List[int]  # 常用交易时间段（小时列表）
    baseline_emotion_volatility: float # 情绪波动幅度（情绪分数的标准差）
    baseline_risk_asset_pct: float    # 风险资产占总资产比例

def calculate_baseline(trades: List[Trade], emotion_records: List[EmotionResult],
                       portfolio_snapshots: List[PortfolioSnapshot]) -> BehaviorBaseline:
    """基于观察期数据计算行为基线"""
    
    # 1. 日均交易频率
    days_span = (trades[-1].timestamp - trades[0].timestamp).days or 1
    baseline_trade_freq = len(trades) / days_span
    
    # 2. 平均持仓天数（仅计算已卖出的）
    closed_trades = [t for t in trades if t.status == 'closed']
    baseline_holding_days = (
        sum(t.holding_days for t in closed_trades) / len(closed_trades)
        if closed_trades else 0
    )
    
    # 3. 平均单笔金额占比
    avg_portfolio_value = sum(s.total_value for s in portfolio_snapshots) / len(portfolio_snapshots)
    baseline_single_amount_pct = (
        sum(t.amount for t in trades) / len(trades) / avg_portfolio_value
        if avg_portfolio_value > 0 else 0
    )
    
    # 4. 常用交易时间段
    hour_counts = Counter(t.timestamp.hour for t in trades)
    baseline_active_hours = [h for h, c in hour_counts.most_common(4)]
    
    # 5. 情绪波动幅度
    scores = [e.score for e in emotion_records]
    baseline_emotion_volatility = stdev(scores) if len(scores) > 1 else 0
    
    # 6. 风险资产占比
    baseline_risk_asset_pct = (
        sum(s.risk_asset_value for s in portfolio_snapshots) / 
        sum(s.total_value for s in portfolio_snapshots)
        if portfolio_snapshots else 0.5
    )
    
    return BehaviorBaseline(
        baseline_trade_freq=baseline_trade_freq,
        baseline_holding_days=baseline_holding_days,
        baseline_single_amount_pct=baseline_single_amount_pct,
        baseline_active_hours=baseline_active_hours,
        baseline_emotion_volatility=baseline_emotion_volatility,
        baseline_risk_asset_pct=baseline_risk_asset_pct
    )
```

#### 4.2.4 基线更新策略

```python
# 滑动窗口配置
BASELINE_UPDATE_CONFIG = {
    'window_days': 30,           # 滑动窗口30天
    'recalculate_interval': 7,   # 每周重新计算
    'min_data_points': 10,       # 最少数据点才进行更新
}

def update_baseline_sliding_window(user: UserProfile, new_data: dict):
    """滑动窗口基线更新"""
    window_start = now() - timedelta(days=30)
    
    # 获取窗口内所有数据
    recent_trades = get_trades_since(user.user_id, window_start)
    recent_emotions = get_emotions_since(user.user_id, window_start)
    recent_snapshots = get_snapshots_since(user.user_id, window_start)
    
    if len(recent_trades) >= BASELINE_UPDATE_CONFIG['min_data_points']:
        new_baseline = calculate_baseline(recent_trades, recent_emotions, recent_snapshots)
        user.behavioral_baseline = new_baseline
```

#### 4.2.5 异常判定

```python
def detect_anomaly(current_value: float, baseline_value: float, 
                   baseline_std: float) -> bool:
    """检测当前值是否偏离基线超过2个标准差"""
    if baseline_std == 0:
        return False
    z_score = abs(current_value - baseline_value) / baseline_std
    return z_score > 2.0  # 超过2个标准差视为异常

def check_all_anomalies(user: UserProfile, current_state: dict) -> List[AnomalySignal]:
    """检查所有维度的异常"""
    anomalies = []
    baseline = user.behavioral_baseline
    
    checks = [
        ('trade_freq', current_state['trade_freq_24h'], baseline.baseline_trade_freq),
        ('holding_days', current_state['avg_holding_days'], baseline.baseline_holding_days),
        ('single_amount', current_state['avg_amount_pct'], baseline.baseline_single_amount_pct),
        ('emotion_volatility', current_state['emotion_std'], baseline.baseline_emotion_volatility),
    ]
    
    for name, current, base in checks:
        std = get_baseline_std(user, name)
        if detect_anomaly(current, base, std):
            anomalies.append(AnomalySignal(
                dimension=name,
                current_value=current,
                baseline_value=base,
                deviation_sigma=(current - base) / std if std > 0 else 0,
                timestamp=now()
            ))
    
    return anomalies
```

---

### 4.3 认知偏差档案

#### 4.3.1 处置效应（Disposition Effect）

**定义**：倾向于过早卖出盈利股票，而长期持有亏损股票。

```python
def calculate_disposition_effect(trades: List[Trade]) -> float:
    """
    处置效应分数 = PGR - PLR 的归一化值
    PGR (Proportion of Gains Realized) = 已实现盈利笔数 / (已实现盈利笔数 + 未实现盈利笔数)
    PLR (Proportion of Losses Realized) = 已实现亏损笔数 / (已实现亏损笔数 + 未实现亏损笔数)
    """
    realized_gains = len([t for t in trades if t.status == 'closed' and t.pnl > 0])
    unrealized_gains = len([t for t in trades if t.status == 'open' and t.unrealized_pnl > 0])
    
    realized_losses = len([t for t in trades if t.status == 'closed' and t.pnl < 0])
    unrealized_losses = len([t for t in trades if t.status == 'open' and t.unrealized_pnl < 0])
    
    pgr = realized_gains / (realized_gains + unrealized_gains) if (realized_gains + unrealized_gains) > 0 else 0
    plr = realized_losses / (realized_losses + unrealized_losses) if (realized_losses + unrealized_losses) > 0 else 0
    
    # 处置效应 = PGR远大于PLR的程度
    # PGR > PLR 说明存在处置效应
    if pgr + plr == 0:
        return 0.0
    
    de_score = (pgr - plr + 1) / 2  # 归一化到0-1
    return min(1.0, max(0.0, de_score))
```

#### 4.3.2 过度自信（Overconfidence）

**定义**：高估自己预测市场的能力，表现为过度交易和集中持仓。

```python
def calculate_overconfidence(trades: List[Trade], portfolio: Portfolio) -> float:
    """
    过度自信 = 交易频率得分 × 0.4 + 持仓集中度得分 × 0.3 + 预测准确率偏差 × 0.3
    """
    # 交易频率得分：日均交易 > 5次 算高频
    daily_freq = len(trades) / max(1, get_active_days(trades))
    freq_score = min(1.0, daily_freq / 5.0)
    
    # 持仓集中度得分：前3只股票占比
    top3_concentration = sum(sorted(portfolio.positions.values(), reverse=True)[:3]) / portfolio.total_value
    concentration_score = max(0, (top3_concentration - 0.5) / 0.5)
    
    # 预测准确率偏差：用户自评 vs 实际
    # MVP简化：用盈利交易的平均收益 vs 亏损交易的平均亏损比
    winning_trades = [t for t in trades if t.status == 'closed' and t.pnl > 0]
    losing_trades = [t for t in trades if t.status == 'closed' and t.pnl < 0]
    
    if winning_trades and losing_trades:
        avg_win = sum(t.pnl for t in winning_trades) / len(winning_trades)
        avg_loss = abs(sum(t.pnl for t in losing_trades) / len(losing_trades))
        # 如果亏损远大于盈利但还在频繁交易，说明过度自信
        accuracy_bias = max(0, 1 - (avg_win / avg_loss)) if avg_loss > 0 else 0
    else:
        accuracy_bias = 0.5  # 数据不足时给中间值
    
    overconfidence = freq_score * 0.4 + concentration_score * 0.3 + accuracy_bias * 0.3
    return min(1.0, max(0.0, overconfidence))
```

#### 4.3.3 羊群效应（Herding）

```python
def calculate_herding_bias(trades: List[Trade], market_data: MarketData,
                           social_reads: List[SocialReadEvent]) -> float:
    """
    羊群效应 = LSV指标 × 0.4 + 热门重合度 × 0.3 + 社交影响度 × 0.3
    """
    lsv = calculate_lsv(trades, market_data.trades)       # 3.3.1 维度1
    hot_overlap = calculate_hot_overlap(                   # 3.3.1 维度2
        [t.symbol for t in trades if t.status == 'open'],
        market_data.hot_stocks
    )
    
    # 社交影响度：平均社交影响分数
    social_scores = []
    for trade in trades:
        score = calculate_social_influence(trade.timestamp, social_reads)
        if score > 0:
            social_scores.append(score)
    social_influence = sum(social_scores) / len(social_scores) if social_scores else 0
    
    herding = lsv * 0.4 + hot_overlap * 0.3 + social_influence * 0.3
    return min(1.0, max(0.0, herding))
```

#### 4.3.4 损失厌恶（Loss Aversion）

**定义**：对损失的痛苦感大于对等额收益的快乐感，通常损失厌恶系数约为2-2.5。

```python
def calculate_loss_aversion(trades: List[Trade], emotion_records: List[EmotionResult]) -> float:
    """
    损失厌恶系数 = |亏损时情绪强度| / |盈利时情绪强度|
    归一化到0-1：系数2.0对应分数0.5（正常水平），系数>3对应高分
    """
    # 获取盈利和亏损交易前后的情绪变化
    gain_emotions = []
    loss_emotions = []
    
    for trade in trades:
        if trade.status != 'closed':
            continue
        # 获取交易前后30分钟内的情绪记录
        nearby_emotions = get_emotions_around(trade.timestamp, window_min=30)
        if not nearby_emotions:
            continue
        
        emotion_impact = nearby_emotions[-1].score - nearby_emotions[0].score
        
        if trade.pnl > 0:
            gain_emotions.append(abs(emotion_impact))
        elif trade.pnl < 0:
            loss_emotions.append(abs(emotion_impact))
    
    if not gain_emotions or not loss_emotions:
        return 0.5  # 数据不足，给中间值
    
    avg_gain_emotion = sum(gain_emotions) / len(gain_emotions)
    avg_loss_emotion = sum(loss_emotions) / len(loss_emotions)
    
    if avg_gain_emotion == 0:
        return 0.7  # 盈利无情绪反应但亏损有，高度损失厌恶
    
    loss_aversion_ratio = avg_loss_emotion / avg_gain_emotion
    
    # 归一化：ratio=1 -> score=0.2, ratio=2 -> score=0.5, ratio=3+ -> score=0.8+
    score = min(1.0, max(0.0, (loss_aversion_ratio - 0.5) / 3.0))
    return score
```

#### 4.3.5 锚定效应（Anchoring Effect）

**定义**：过度依赖最初获得的信息（锚点）来做决策，如买入价格成为心理锚点。

```python
def calculate_anchoring_effect(trades: List[Trade], portfolio: Portfolio) -> float:
    """
    锚定效应 = 买入价格锚定强度
    检测：用户是否因为当前价格接近买入价格而做出非理性决策
    """
    anchoring_signals = []
    
    for position in portfolio.open_positions:
        buy_price = position.avg_cost
        current_price = position.current_price
        change_pct = (current_price - buy_price) / buy_price
        
        # 信号1：价格在买入价附近（±2%）时交易量异常大
        if abs(change_pct) < 0.02:
            # 检查是否有大量加仓或减仓
            recent_trades = get_recent_trades(position.symbol, days=7)
            if len(recent_trades) > 3:
                anchoring_signals.append(0.7)
        
        # 信号2：回本即卖（价格刚回到买入价就急于卖出）
        if -0.01 < change_pct < 0.03 and position.has_sell_order_near_cost:
            anchoring_signals.append(0.8)
        
        # 信号3：深套不动（亏损>20%但完全不操作）
        if change_pct < -0.20 and position.days_held > 30 and position.trade_count == 1:
            anchoring_signals.append(0.6)
    
    if not anchoring_signals:
        return 0.2  # 无锚定信号，给基础分
    
    score = sum(anchoring_signals) / len(anchoring_signals)
    return min(1.0, max(0.0, score))
```

#### 4.3.6 偏差分数汇总

```typescript
interface BiasScores {
  disposition_effect: number;     // 处置效应 0-1
  overconfidence: number;         // 过度自信 0-1
  herding: number;                // 羊群效应 0-1
  loss_aversion: number;          // 损失厌恶 0-1
  anchoring: number;              // 锚定效应 0-1
}

// 干预阈值
const BIAS_INTERVENTION_THRESHOLD = 0.7;

function getBiasWarning(biasScores: BiasScores): BiasWarning[] {
  const warnings: BiasWarning[] = [];
  
  const biasNames: Record<string, string> = {
    disposition_effect: '处置效应',
    overconfidence: '过度自信',
    herding: '羊群效应',
    loss_aversion: '损失厌恶',
    anchoring: '锚定效应',
  };
  
  for (const [key, score] of Object.entries(biasScores)) {
    if (score > BIAS_INTERVENTION_THRESHOLD) {
      warnings.push({
        bias_type: key,
        bias_name: biasNames[key],
        score: score,
        severity: score > 0.9 ? 'critical' : score > 0.8 ? 'high' : 'medium',
        message: generateBiasMessage(key, score),
      });
    }
  }
  
  return warnings;
}
```

---

### 4.4 言行一致性检测

#### 4.4.1 检测维度

**维度1：聊天表达 vs 交易行为**

```python
def check_chat_vs_trade(emotion_result: EmotionResult, 
                        trade_signals: List[TradeSignal]) -> ConsistencyCheck:
    """
    检测：说冷静但疯狂交易，说恐慌但实际在买入
    """
    contradictions = []
    
    # 嘴上说冷静，但交易频率异常高
    if emotion_result.emotion == '冷静' and emotion_result.confidence > 0.6:
        recent_trade_freq = sum(1 for t in trade_signals 
                                 if is_within(t.timestamp, hours=1))
        if recent_trade_freq > 5:
            contradictions.append({
                'type': '嘴硬型焦虑',
                'description': f'声称冷静分析，但过去1小时交易了{recent_trade_freq}次',
                'severity': 0.8
            })
    
    # 嘴上说恐慌，但实际上在大笔买入
    if emotion_result.emotion == '恐慌':
        big_buys = [t for t in trade_signals 
                    if t.direction == 'buy' and t.amount > baseline_amount * 2]
        if big_buys:
            contradictions.append({
                'type': '风险低估',
                'description': '表达恐慌情绪，但正在进行大额买入',
                'severity': 0.7
            })
    
    return ConsistencyCheck(
        dimension='chat_vs_trade',
        contradictions=contradictions,
        score=1.0 - max((c['severity'] for c in contradictions), default=0)
    )
```

**维度2：声明风格 vs 实际操作**

```python
def check_style_vs_operation(user_profile: UserProfile, 
                             recent_trades: List[Trade]) -> ConsistencyCheck:
    """
    检测：说长期投资但频繁日内交易，说保守但满仓投机
    """
    contradictions = []
    style = user_profile.static_attributes.investment_style
    horizon = user_profile.static_attributes.investment_horizon
    
    # 声称长期投资但进行日内交易
    if horizon == 'long_term':
        day_trades = [t for t in recent_trades 
                      if t.holding_days is not None and t.holding_days < 1]
        day_trade_ratio = len(day_trades) / len(recent_trades) if recent_trades else 0
        
        if day_trade_ratio > 0.3:
            contradictions.append({
                'type': '风格漂移',
                'description': f'声明长期投资，但{day_trade_ratio*100:.0f}%的交易为日内交易',
                'severity': 0.7
            })
    
    # 声称保守但持仓高度集中
    if style == 'conservative':
        concentration = get_top_position_concentration(user_profile)
        if concentration > 0.6:
            contradictions.append({
                'type': '风险低估',
                'description': f'声明保守投资，但最大持仓占比{concentration*100:.0f}%',
                'severity': 0.6
            })
    
    return ConsistencyCheck(
        dimension='style_vs_operation',
        contradictions=contradictions,
        score=1.0 - max((c['severity'] for c in contradictions), default=0)
    )
```

**维度3：设定计划 vs 执行偏离**

```python
def check_plan_vs_execution(user_plans: List[TradingPlan], 
                            actual_trades: List[Trade]) -> ConsistencyCheck:
    """
    检测：设了止损但不执行，设了定投但随意更改
    """
    contradictions = []
    
    for plan in user_plans:
        if plan.type == 'stop_loss' and plan.status == 'active':
            # 检查是否有触发止损但未执行的情况
            for trade in actual_trades:
                if (trade.symbol == plan.symbol and 
                    trade.current_price <= plan.stop_price and
                    not trade.stop_executed):
                    contradictions.append({
                        'type': '止损失效',
                        'description': f'{plan.symbol}已触发止损价{plan.stop_price}，但未执行卖出',
                        'severity': 0.9
                    })
        
        if plan.type == 'target_sell' and plan.status == 'active':
            for trade in actual_trades:
                if (trade.symbol == plan.symbol and
                    trade.current_price >= plan.target_price and
                    trade.direction == 'buy'):  # 到目标价反而加仓
                    contradictions.append({
                        'type': '风格漂移',
                        'description': f'{plan.symbol}已达目标价，但未按计划卖出反而加仓',
                        'severity': 0.7
                    })
    
    return ConsistencyCheck(
        dimension='plan_vs_execution',
        contradictions=contradictions,
        score=1.0 - max((c['severity'] for c in contradictions), default=0)
    )
```

#### 4.4.2 一致性分数计算

```typescript
interface ConsistencyCheck {
  dimension: 'chat_vs_trade' | 'style_vs_operation' | 'plan_vs_execution';
  contradictions: Array<{
    type: ContradictionType;
    description: string;
    severity: number;             // 0-1
  }>;
  score: number;                  // 0-1，越低说明矛盾越大
}

interface ConsistencyResult {
  overall_score: number;          // 综合一致性分数 0-1
  dimensions: ConsistencyCheck[];
  dominant_contradiction?: ContradictionType;  // 最突出的矛盾类型
  should_intervene: boolean;      // 是否需要干预
  intervention_reason?: string;
}
```

```python
def calculate_consistency(chat_check: ConsistencyCheck,
                          style_check: ConsistencyCheck,
                          plan_check: ConsistencyCheck) -> ConsistencyResult:
    """计算综合一致性分数"""
    # 加权平均（计划执行权重最高）
    weights = {
        'chat_vs_trade': 0.3,
        'style_vs_operation': 0.3,
        'plan_vs_execution': 0.4
    }
    
    overall_score = (
        chat_check.score * weights['chat_vs_trade'] +
        style_check.score * weights['style_vs_operation'] +
        plan_check.score * weights['plan_vs_execution']
    )
    
    # 找出最严重的矛盾
    all_contradictions = (chat_check.contradictions + 
                          style_check.contradictions + 
                          plan_check.contradictions)
    
    dominant = max(all_contradictions, key=lambda c: c['severity'], default=None)
    
    return ConsistencyResult(
        overall_score=overall_score,
        dimensions=[chat_check, style_check, plan_check],
        dominant_contradiction=dominant['type'] if dominant else None,
        should_intervene=overall_score < 0.4,
        intervention_reason=dominant['description'] if dominant else None
    )
```

---

### 4.5 时间衰减机制

#### 4.5.1 衰减函数

```
指数衰减函数：w(t) = e^(-λt)

其中：
- t = 时间差（天）
- λ = 衰减系数

不同数据类型的衰减配置：
┌──────────┬────────┬────────────┬──────────────────────────┐
│ 数据类型 │   λ    │  半衰期    │ 说明                     │
├──────────┼────────┼────────────┼──────────────────────────┤
│ 情绪信号 │  0.10  │  ≈7天      │ 情绪是瞬时的，快速遗忘   │
│ 偏差评分 │  0.03  │  ≈23天     │ 偏差是习惯性的，缓慢变化 │
│ 风险画像 │  0.01  │  ≈69天     │ 人格相对稳定，极慢衰减   │
└──────────┴────────┴────────────┴──────────────────────────┘
```

```python
import math
from datetime import datetime

DECAY_CONFIG = {
    'emotion': {'lambda': 0.10, 'half_life_days': 6.93},   # ln(2)/0.1 ≈ 7天
    'bias': {'lambda': 0.03, 'half_life_days': 23.1},      # ln(2)/0.03 ≈ 23天
    'profile': {'lambda': 0.01, 'half_life_days': 69.3},   # ln(2)/0.01 ≈ 69天
}

def exponential_decay(days_elapsed: float, data_type: str) -> float:
    """计算时间衰减权重"""
    lam = DECAY_CONFIG[data_type]['lambda']
    return math.exp(-lam * days_elapsed)
```

#### 4.5.2 更新公式

```
score_new = α × score_current + (1 - α) × score_old × e^(-λΔt)

其中：
- α = 新信号权重（学习率）
- score_current = 当前信号计算出的分数
- score_old = 历史累计分数
- λ = 衰减系数
- Δt = 距离上次更新的天数
```

```python
def update_with_decay(old_score: float, current_score: float,
                      days_elapsed: float, data_type: str,
                      alpha: float = 0.3) -> float:
    """
    带时间衰减的分数更新
    
    参数:
        old_score: 历史分数
        current_score: 当前信号分数
        days_elapsed: 距上次更新的天数
        data_type: 数据类型 ('emotion', 'bias', 'profile')
        alpha: 新信号权重（学习率）
    
    返回:
        更新后的分数
    """
    decay_weight = exponential_decay(days_elapsed, data_type)
    
    # 新信号权重 + 衰减后的历史分数
    new_score = alpha * current_score + (1 - alpha) * old_score * decay_weight
    
    return max(0.0, min(1.0, new_score))


# === 使用示例 ===

# 情绪更新（快衰减）
emotion_score = update_with_decay(
    old_score=0.3,           # 上次情绪分数
    current_score=0.8,       # 当前检测到的情绪分数
    days_elapsed=0.5,        # 距上次更新12小时
    data_type='emotion',
    alpha=0.5                # 情绪更新给更高的新信号权重
)

# 偏差更新（中衰减）
bias_score = update_with_decay(
    old_score=0.6,           # 历史偏差分数
    current_score=0.8,       # 本次交易计算的偏差
    days_elapsed=1.0,        # 距上次更新1天
    data_type='bias',
    alpha=0.2                # 偏差更新给较低的新信号权重（需要多次确认）
)

# 画像更新（慢衰减）
risk_score = update_with_decay(
    old_score=0.5,
    current_score=0.7,
    days_elapsed=7.0,        # 每周更新一次
    data_type='profile',
    alpha=0.1                # 画像更新极其保守
)
```

---

## 5. 干预模块

### 5.1 干预触发条件

```typescript
interface InterventionTrigger {
  trigger_type: 'emotion_extreme' | 'bias_significant' | 'consistency_low' | 'behavior_anomaly' | 'compound';
  severity: 'P0' | 'P1' | 'P2' | 'P3';
  score: number;
  threshold: number;
  details: string;
}

// 触发条件配置
const TRIGGER_CONFIG = {
  emotion_extreme: {
    condition: (state: MentalState) => Math.abs(state.emotion_score) > 0.8,
    severity: (score: number) => Math.abs(score) > 0.9 ? 'P0' : 'P1',
    description: '情绪极端',
  },
  bias_significant: {
    condition: (state: MentalState) => Object.values(state.bias_scores).some(s => s > 0.7),
    severity: (maxScore: number) => maxScore > 0.9 ? 'P1' : 'P2',
    description: '认知偏差显著',
  },
  consistency_low: {
    condition: (state: MentalState) => state.consistency_score < 0.4,
    severity: (score: number) => score < 0.2 ? 'P1' : 'P2',
    description: '言行矛盾',
  },
  behavior_anomaly: {
    condition: (state: MentalState) => state.anomaly_signals.length > 0,
    severity: (anomalies: AnomalySignal[]) => 
      anomalies.some(a => Math.abs(a.deviation_sigma) > 3) ? 'P1' : 'P2',
    description: '行为异常',
  },
};
```

**复合条件升级逻辑**：

```python
def evaluate_triggers(mental_state: MentalState) -> List[InterventionTrigger]:
    """评估所有触发条件，支持复合升级"""
    triggers = []
    
    # 单一条件检测
    if abs(mental_state.emotion_score) > 0.8:
        severity = 'P0' if abs(mental_state.emotion_score) > 0.9 else 'P1'
        triggers.append(InterventionTrigger(
            trigger_type='emotion_extreme',
            severity=severity,
            score=mental_state.emotion_score,
            threshold=0.8,
            details=f'情绪分数={mental_state.emotion_score}'
        ))
    
    max_bias = max(mental_state.bias_scores.values())
    if max_bias > 0.7:
        triggers.append(InterventionTrigger(
            trigger_type='bias_significant',
            severity='P1' if max_bias > 0.9 else 'P2',
            score=max_bias,
            threshold=0.7,
            details=f'最高偏差分数={max_bias}'
        ))
    
    if mental_state.consistency_score < 0.4:
        triggers.append(InterventionTrigger(
            trigger_type='consistency_low',
            severity='P1' if mental_state.consistency_score < 0.2 else 'P2',
            score=mental_state.consistency_score,
            threshold=0.4,
            details=f'一致性分数={mental_state.consistency_score}'
        ))
    
    # 复合条件升级：多个信号同时触发时，升级干预强度
    if len(triggers) >= 2:
        # 将最高severity升级一级
        highest = min(triggers, key=lambda t: {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}[t.severity])
        upgraded = {'P3': 'P2', 'P2': 'P1', 'P1': 'P0', 'P0': 'P0'}[highest.severity]
        triggers.append(InterventionTrigger(
            trigger_type='compound',
            severity=upgraded,
            score=len(triggers),
            threshold=2,
            details=f'多信号同时触发，升级为{upgraded}级干预'
        ))
    
    return triggers
```

### 5.2 干预策略

| 优先级 | 触发条件 | 干预方式 | 响应时间 | 示例 |
|--------|---------|---------|---------|------|
| P0（立即） | 恐慌性抛售/冲动全仓 | 弹窗确认 | <1s | "检测到您可能在冲动操作，是否确定执行？建议等待10分钟再做决定" |
| P1（强提醒） | 认知偏差严重 | 推送偏差解释+历史教训 | <5s | "数据显示您倾向于过早卖出盈利股票，这被称为'处置效应'，可能导致..." |
| P2（温和引导） | 情绪波动 | 对话嵌入 | 下次回复时 | "我注意到你似乎有些焦虑，可能需要冷静一下再做决策" |
| P3（信息补充） | 轻微偏差 | 提供反面信息 | 下次回复时 | "关于这只股票，这里有一些你可能没注意到的风险因素..." |

**干预策略选择伪代码**：

```python
def select_intervention_strategy(trigger: InterventionTrigger,
                                 user_profile: UserProfile) -> InterventionStrategy:
    """根据触发条件和用户特征选择干预策略"""
    
    if trigger.severity == 'P0':
        return InterventionStrategy(
            method='popup',
            content=generate_popup_confirmation(trigger),
            delay_seconds=0,
            require_acknowledgement=True
        )
    
    elif trigger.severity == 'P1':
        return InterventionStrategy(
            method='push_notification',
            content=generate_bias_explanation(trigger, user_profile),
            delay_seconds=5,
            require_acknowledgement=False,
            include_historical_lesson=True
        )
    
    elif trigger.severity == 'P2':
        return InterventionStrategy(
            method='chat_embed',
            content=generate_gentle_reminder(trigger),
            delay_seconds=0,  # 下次对话时自然嵌入
            require_acknowledgement=False
        )
    
    else:  # P3
        return InterventionStrategy(
            method='info_supplement',
            content=generate_counter_information(trigger),
            delay_seconds=0,
            require_acknowledgement=False
        )
```

### 5.3 干预方式

#### 5.3.1 对话嵌入

```python
def generate_chat_embedded_intervention(mental_state: MentalState,
                                        ai_response: str) -> str:
    """在AI回复中自然融入心理提醒"""
    
    intervention_phrases = {
        '焦虑': [
            "在分析这个问题之前，我想提醒你，做决策时保持冷静很重要。",
            "我注意到你似乎有些纠结，也许可以先深呼吸一下，我们慢慢分析。",
        ],
        '恐慌': [
            "市场波动确实让人紧张，但历史数据显示恐慌性操作往往不是最优选择。",
            "我理解你的担忧，不过在做出重大决策前，让我们先看看数据。",
        ],
        '贪婪': [
            "这个机会看起来不错，但我们也要考虑风险管理。",
            "在加仓之前，让我们回顾一下你的仓位管理计划。",
        ],
        '沮丧': [
            "投资有赢有亏很正常，重要的是我们从中学到了什么。",
            "现在的亏损不代表未来的结果，让我们客观分析一下情况。",
        ],
    }
    
    emotion = mental_state.current_emotion
    phrases = intervention_phrases.get(emotion, [])
    
    if phrases:
        intervention = random.choice(phrases)
        # 在AI回复开头或中间自然插入
        return f"{intervention}\n\n{ai_response}"
    
    return ai_response
```

#### 5.3.2 弹窗提醒

```typescript
interface PopupIntervention {
  type: 'trade_confirmation' | 'bias_warning' | 'cool_down';
  title: string;
  message: string;
  data_visualization?: {
    chart_type: 'bar' | 'line' | 'comparison';
    data: Record<string, number>;
    caption: string;
  };
  actions: Array<{
    label: string;
    action: 'confirm' | 'cancel' | 'delay' | 'view_details';
  }>;
  cooldown_minutes: number;       // 强制冷静时间
}

// 示例：冲动交易确认弹窗
const IMPULSE_TRADE_POPUP: PopupIntervention = {
  type: 'trade_confirmation',
  title: '交易确认',
  message: '我们注意到你近期交易频率是平时的3倍。研究表明，频繁交易往往降低收益。你是否确定要执行此操作？',
  data_visualization: {
    chart_type: 'bar',
    data: {
      '你的本周交易次数': 15,
      '你的平时平均次数': 5,
    },
    caption: '你的交易频率对比',
  },
  actions: [
    { label: '我再想想', action: 'delay' },
    { label: '确认执行', action: 'confirm' },
    { label: '查看详情', action: 'view_details' },
  ],
  cooldown_minutes: 5,
};
```

#### 5.3.3 数据展示

```python
def generate_data_insight(user_profile: UserProfile, 
                          trigger: InterventionTrigger) -> str:
    """生成用户行为数据洞察，用数据说话"""
    baseline = user_profile.behavioral_baseline
    current = get_current_metrics(user_profile.user_id)
    
    insights = []
    
    # 交易频率对比
    if current.trade_freq_7d > baseline.baseline_trade_freq * 2:
        insights.append(
            f"你本周交易了{current.trade_freq_7d}次，是你平时"
            f"（{baseline.baseline_trade_freq:.1f}次/天）的"
            f"{current.trade_freq_7d/baseline.baseline_trade_freq:.1f}倍。"
        )
    
    # 持仓集中度
    if current.top_position_pct > 0.6:
        insights.append(
            f"你最大的单只持仓占总资产的{current.top_position_pct*100:.0f}%，"
            f"远超分散投资建议的20%上限。"
        )
    
    # 持仓时间
    if current.avg_holding_days < baseline.baseline_holding_days * 0.5:
        insights.append(
            f"你近期的平均持仓时间({current.avg_holding_days:.1f}天)"
            f"比你的历史平均({baseline.baseline_holding_days:.1f}天)短了很多。"
        )
    
    return '\n'.join(insights)
```

#### 5.3.4 认知重构

```python
def generate_cognitive_reframe(bias_type: str, context: dict) -> str:
    """引导用户重新思考决策依据"""
    
    reframes = {
        'disposition_effect': (
            "你持有的{stock}目前盈利了{gain}%，你想卖出锁定利润。\n\n"
            "但请思考：如果你现在没有持有这只股票，以目前的价格和基本面，"
            "你会选择买入吗？如果答案是'会'，那么继续持有可能是更好的选择。"
        ),
        'loss_aversion': (
            "你在{stock}上亏损了{loss}%，这让你很难做出卖出的决定。\n\n"
            "试着换个角度：这笔钱如果现在在你手里，你会用它买入这只股票吗？"
            "如果答案是否定的，那留在这只股票里可能并不是最好的选择。"
        ),
        'overconfidence': (
            "你最近{win_count}笔交易都盈利了，感觉自己掌握了市场节奏。\n\n"
            "但统计显示，连续盈利后往往容易出现过度自信导致的失误。"
            "回顾一下，你的成功有多少是基于分析，有多少是运气？"
        ),
        'herding': (
            "很多人都在买{stock}，你也想跟着买。\n\n"
            "请记住：大众往往是错的。在跟随之前，"
            "请独立回答：这只股票的哪些基本面指标支撑你的买入决策？"
        ),
        'anchoring': (
            "你在{buy_price}元买入的{stock}，现在价格是{current_price}元。\n\n"
            "你的买入价格不应该影响你对未来的判断。"
            "请只基于当前的价格和信息来评估：这只股票未来值不值得持有？"
        ),
    }
    
    template = reframes.get(bias_type, "请冷静思考你的决策依据。")
    return template.format(**context)
```

### 5.4 干预频率限制

```python
INTERVENTION_LIMITS = {
    'max_daily': 3,                    # 每日最多干预3次
    'same_type_cooldown_hours': 24,    # 同一类型干预24小时内不重复
    'user_can_disable': True,          # 用户可关闭特定类型提醒
    'global_cooldown_minutes': 30,     # 任意干预之间最少间隔30分钟
}

class InterventionLimiter:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.daily_count = 0
        self.last_intervention_time = None
        self.last_intervention_by_type = {}  # type -> datetime
        self.disabled_types = set()          # 用户关闭的干预类型
    
    def can_intervene(self, intervention_type: str) -> bool:
        """检查是否可以进行干预"""
        # 检查用户是否关闭了该类型
        if intervention_type in self.disabled_types:
            return False
        
        # 检查每日上限
        if self.daily_count >= INTERVENTION_LIMITS['max_daily']:
            return False
        
        # 检查全局冷却时间
        if self.last_intervention_time:
            elapsed = (now() - self.last_intervention_time).total_seconds() / 60
            if elapsed < INTERVENTION_LIMITS['global_cooldown_minutes']:
                return False
        
        # 检查同类型冷却
        last_of_type = self.last_intervention_by_type.get(intervention_type)
        if last_of_type:
            hours_since = (now() - last_of_type).total_seconds() / 3600
            if hours_since < INTERVENTION_LIMITS['same_type_cooldown_hours']:
                return False
        
        return True
    
    def record_intervention(self, intervention_type: str):
        """记录一次干预"""
        self.daily_count += 1
        self.last_intervention_time = now()
        self.last_intervention_by_type[intervention_type] = now()
    
    def reset_daily(self):
        """每日重置计数器"""
        self.daily_count = 0
```

### 5.5 反馈闭环

```typescript
interface InterventionRecord {
  id: string;                       // UUID
  user_id: string;
  timestamp: string;                // ISO 8601
  trigger: InterventionTrigger;     // 触发条件
  strategy: InterventionStrategy;   // 干预策略
  content: string;                  // 干预内容
  
  // 用户响应
  user_response: {
    action: 'accepted' | 'dismissed' | 'ignored' | 'delayed';
    response_time_sec: number;      // 响应时间
    subsequent_behavior_change?: {
      changed: boolean;
      description: string;
      time_to_change_min: number;   // 行为改变所需时间（分钟）
    };
  };
  
  // 效果评估
  effectiveness: {
    immediate_score: number;        // 即时效果评分 0-1（干预后情绪变化）
    delayed_score?: number;         // 延迟效果评分（24小时后）
    behavior_adjusted: boolean;     // 用户是否调整了行为
  };
}
```

```python
def evaluate_intervention_effectiveness(record: InterventionRecord,
                                        user_state_after: MentalState) -> float:
    """评估干预效果"""
    score = 0.0
    
    # 1. 用户是否接受（action层面）
    action_scores = {
        'accepted': 1.0,
        'delayed': 0.7,
        'dismissed': 0.2,
        'ignored': 0.0,
    }
    score += action_scores.get(record.user_response.action, 0) * 0.3
    
    # 2. 情绪是否回归正常范围
    emotion_before = abs(record.trigger.score)
    emotion_after = abs(user_state_after.emotion_score)
    emotion_improvement = max(0, emotion_before - emotion_after) / emotion_before if emotion_before > 0 else 0
    score += emotion_improvement * 0.4
    
    # 3. 行为是否调整
    if record.user_response.subsequent_behavior_change?.changed:
        score += 0.3
    
    return min(1.0, score)


def learn_intervention_preference(user_id: str, 
                                  records: List[InterventionRecord]) -> dict:
    """学习哪种干预方式对用户最有效"""
    method_effectiveness = defaultdict(list)
    
    for record in records:
        if record.effectiveness:
            method = record.strategy.method
            method_effectiveness[method].append(record.effectiveness.immediate_score)
    
    preferences = {}
    for method, scores in method_effectiveness.items():
        preferences[method] = {
            'avg_effectiveness': sum(scores) / len(scores),
            'count': len(scores),
            'recommended': sum(scores) / len(scores) > 0.6
        }
    
    return preferences
```

---

## 6. 数据流与接口定义

### 6.1 输入接口

#### POST /mental/chat — 接收聊天文本

```typescript
// Request
interface ChatRequest {
  user_id: string;
  message: string;                  // 用户消息文本
  session_id: string;               // 会话ID
  timestamp: string;                // ISO 8601
  context?: {
    previous_messages: Array<{      // 最近5条消息（上下文）
      role: 'user' | 'assistant';
      content: string;
    }>;
    active_stock?: string;          // 当前查看的股票
  };
}

// Response
interface ChatResponse {
  emotion: EmotionResult;           // 情绪分析结果
  consistency?: ConsistencyResult;  // 一致性检测结果
  intervention?: InterventionStrategy; // 干预建议（如有）
  profile_update: {
    emotion_recorded: boolean;
    bias_recalculated: boolean;
  };
}
```

#### POST /mental/trade — 接收交易事件

```typescript
// Request
interface TradeRequest {
  user_id: string;
  trade: {
    trade_id: string;
    symbol: string;
    direction: 'buy' | 'sell';
    amount: number;
    quantity: number;
    price: number;
    timestamp: string;
    order_type: 'market' | 'limit' | 'stop_loss' | 'target';
  };
  portfolio_snapshot: {
    total_value: number;
    positions: Array<{
      symbol: string;
      quantity: number;
      avg_cost: number;
      current_price: number;
      pnl_pct: number;
      holding_days: number;
    }>;
  };
}

// Response
interface TradeResponse {
  anomaly_detected: boolean;
  anomaly_signals: AnomalySignal[];
  bias_update: BiasScores;
  baseline_deviation: {
    dimension: string;
    deviation_sigma: number;
  }[];
  intervention?: InterventionStrategy;
}
```

#### POST /mental/behavior — 接收行为事件

```typescript
// Request
interface BehaviorRequest {
  user_id: string;
  event_type: 'page_view' | 'search' | 'watchlist_change' | 'notification_click' | 'app_session';
  timestamp: string;
  data: Record<string, any>;        // 事件特定数据
}

// Response
interface BehaviorResponse {
  signals_extracted: number;
  emotion_signals: Array<{
    emotion: EmotionType;
    score: number;
    confidence: number;
    trigger: string;
  }>;
  intervention?: InterventionStrategy;
}
```

#### GET /mental/profile/{user_id} — 获取用户画像

```typescript
// Response
interface ProfileResponse {
  user_id: string;
  profile: UserProfile;
  observation_status: {
    complete: boolean;
    days_elapsed: number;
    trades_counted: number;
    days_remaining?: number;
  };
  generated_at: string;
}
```

#### GET /mental/state/{user_id} — 获取当前心智状态

```typescript
// Response
interface MentalStateResponse {
  user_id: string;
  current_state: {
    emotion: EmotionResult;
    bias_scores: BiasScores;
    consistency_score: number;
    market_pressure: number;
    herding_score: number;
    anomaly_count: number;
  };
  risk_adjustment: {
    recommended_position_scale: number;  // 0-1, 建议仓位缩放比例
    reason: string;
  };
  active_interventions: InterventionStrategy[];
  timestamp: string;
}
```

### 6.2 输出接口

#### 向策略Agent输出

```typescript
interface StrategyAgentOutput {
  user_id: string;
  mental_state: {
    emotion: EmotionType;
    emotion_score: number;
    emotion_confidence: number;
  };
  risk_adjustment: {
    position_scale: number;          // 0.5-1.5, 仓位缩放建议
    // 情绪极端时建议缩小仓位，冷静时可正常或略大
    max_single_trade_pct: number;    // 建议单笔最大占比
    reason: string;
  };
  bias_warnings: Array<{
    bias_type: string;
    score: number;
    description: string;
    recommendation: string;          // 给策略Agent的建议
  }>;
  timestamp: string;
}
```

#### 向前端输出

```typescript
interface FrontendOutput {
  user_id: string;
  emotion_display: {
    current_emotion: EmotionType;
    emotion_emoji: string;           // 展示用emoji
    emotion_trend: Array<{           // 最近7天情绪趋势
      date: string;
      dominant_emotion: EmotionType;
      score: number;
    }>;
  };
  intervention_content?: {
    show_popup: boolean;
    popup_data?: PopupIntervention;
    chat_embed?: string;             // 嵌入对话的文本
    notification?: string;           // 推送通知文本
  };
  profile_summary: {
    investment_style: string;
    risk_level: string;
    consistency_badge: '一致' | '轻微偏差' | '明显矛盾';
    top_bias: string;                // 最突出的偏差
    observation_complete: boolean;
  };
}
```

#### 向Orchestrator输出

```typescript
interface OrchestratorOutput {
  user_id: string;
  should_intervene: boolean;
  intervention_priority: 'P0' | 'P1' | 'P2' | 'P3' | null;
  intervention_content: string | null;
  intervention_method: 'popup' | 'chat_embed' | 'push_notification' | 'info_supplement' | null;
  context_for_orchestrator: {
    user_emotional_state: string;     // 人类可读的情绪状态描述
    recommended_action: string;       // 建议Orchestrator采取的行动
    suppress_other_agents: boolean;   // 是否需要暂时抑制其他Agent的回复
  };
}
```

### 6.3 事件流

```
┌────────────────────────────────────────────────────────────────────┐
│                          事件处理流程                               │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  交易事件 (POST /mental/trade)                                     │
│  ├─→ 1. 存储交易记录                                               │
│  ├─→ 2. 更新行为基线（如果在观察期）                                │
│  ├─→ 3. 触发偏差重算（5大偏差）                                    │
│  ├─→ 4. 异常检测（偏离基线检查）                                    │
│  ├─→ 5. 一致性检测（风格漂移、止损失效）                            │
│  └─→ 6. 干预判定 → 输出干预策略                                    │
│                                                                    │
│  聊天事件 (POST /mental/chat)                                      │
│  ├─→ 1. 情绪分析（词典 → LLM）                                    │
│  ├─→ 2. 更新情绪历史                                               │
│  ├─→ 3. 一致性检测（嘴硬型焦虑、风险低估）                          │
│  ├─→ 4. 词典反哺（如果走LLM路径）                                  │
│  └─→ 5. 干预判定 → 输出干预策略                                    │
│                                                                    │
│  行为事件 (POST /mental/behavior)                                   │
│  ├─→ 1. 行为信号提取                                               │
│  ├─→ 2. 行为→情绪映射                                              │
│  ├─→ 3. 羊群效应检测（如果涉及交易相关行为）                        │
│  └─→ 4. 干预判定（如果触发异常）                                    │
│                                                                    │
│  定时任务 (Cron)                                                   │
│  ├─→ 每日00:00 - 基线更新（滑动窗口重算）                          │
│  ├─→ 每日00:00 - 画像衰减更新（时间衰减应用）                       │
│  ├─→ 每日00:00 - 干预次数计数器重置                                │
│  └─→ 每周日 - 基线全量重算 + 偏差分数衰减更新                       │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```
