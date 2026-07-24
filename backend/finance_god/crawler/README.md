# A股行业资讯与市场情绪爬虫 API

## 概述

本模块提供 A 股行业资讯和市场情绪数据的实时采集接口。数据来源于东方财富和同花顺的公开 API，无需额外凭证。

**Base URL**: `/api/crawler/`（通过 `finance_app` 挂载，前端可通过 `/api/crawler/*` 访问）

---

## 接口列表

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/crawler/news` | GET | 行业资讯 |
| `/api/crawler/sentiment` | GET | 市场情绪 |
| `/api/crawler/report` | GET | 完整报告（资讯+情绪） |

---

## 1. 获取行业资讯

### `GET /api/crawler/news`

获取最新 A 股行业资讯，包含财经要闻和券商研报。

#### 请求参数（Query String）

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `sector` | string | 否 | `""` | 行业板块筛选，为空则返回综合资讯 |
| `limit` | int | 否 | `20` | 返回条数（最大 50） |
| `refresh` | string | 否 | `"0"` | 设为 `"1"` 强制刷新缓存 |

#### 可选 sector 值

`银行`、`医药生物`、`电子`、`计算机`、`食品饮料`、`电力设备`、`汽车`、`房地产`、`有色金属`、`机械设备`、`通信`、`传媒`、`国防军工`、`石油石化`、`农林牧渔`

#### 响应示例

```json
{
  "success": true,
  "count": 20,
  "data": [
    {
      "title": "综合施策提升资本市场韧性 制度改革护航高质量发展",
      "summary": "证监会近日召开党的建设暨监管工作座谈会...",
      "source": "东方财富/证券时报",
      "url": "http://stock.eastmoney.com/news/11791,202607253820879343.html",
      "publish_time": "2026-07-25T02:36:42+08:00",
      "sector": "综合",
      "tags": ["证券时报"]
    },
    {
      "title": "石油石化行业事件点评：中东地缘冲突持续升级",
      "summary": "机构: 国信证券 | 评级: 增持 | 行业: 炼化及贸易",
      "source": "东方财富研报/国信证券",
      "url": "https://data.eastmoney.com/report/info/AP202607241827327771.html",
      "publish_time": "2026-07-24T00:00:00+08:00",
      "sector": "炼化及贸易",
      "tags": ["行业研报", "炼化及贸易", "国信证券"]
    }
  ]
}
```

#### 错误响应

```json
{
  "success": false,
  "error": "请求超时",
  "data": []
}
```

---

## 2. 获取市场情绪

### `GET /api/crawler/sentiment`

获取 A 股市场综合情绪指标，包括涨跌广度、北向资金、板块热度。

#### 请求参数（Query String）

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `refresh` | string | 否 | `"0"` | 设为 `"1"` 强制刷新缓存 |

#### 响应示例

```json
{
  "success": true,
  "data": {
    "score": 55.7,
    "level": "neutral",
    "breadth": {
      "up_count": 49,
      "down_count": 50,
      "flat_count": 1,
      "limit_up": 23,
      "limit_down": 7,
      "up_ratio": 0.49
    },
    "turnover_rate": 0.0,
    "total_volume": 0.0,
    "north_flow": -0.3,
    "sector_flows": [
      {
        "sector_name": "人民币贬值受益",
        "change_percent": 14.99,
        "net_inflow": 0.0,
        "main_inflow": 0.0,
        "volume": 0.0,
        "leading_stock": "",
        "retrieved_at": "2026-07-25T02:52:59+08:00"
      }
    ],
    "hot_sectors": ["人民币贬值受益", "专精特新", "特高压"],
    "risk_sectors": ["超超临界发电", "算力租赁", "人形机器人"],
    "retrieved_at": "2026-07-25T02:52:59+08:00",
    "data_source": "eastmoney+ths"
  }
}
```

#### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `score` | float | 情绪评分 0-100 |
| `level` | string | 情绪等级：`extreme_fear` / `fear` / `neutral` / `greed` / `extreme_greed` |
| `breadth.up_count` | int | 上涨家数 |
| `breadth.down_count` | int | 下跌家数 |
| `breadth.limit_up` | int | 涨停家数 |
| `breadth.limit_down` | int | 跌停家数 |
| `breadth.up_ratio` | float | 上涨占比 (0-1) |
| `north_flow` | float | 北向资金净流入（亿元，负值为流出） |
| `sector_flows` | array | 板块涨幅排行 TOP10 |
| `hot_sectors` | array | 热门板块名称列表 |
| `risk_sectors` | array | 风险板块名称列表 |

#### 情绪评分算法

```
评分 = 涨跌比(40%) + 北向资金(20%) + 板块动能(20%) + 涨跌停比(20%)

涨跌比得分 = up_ratio × 100
北向资金得分 = clamp((north_flow + 100) / 200 × 100, 0, 100)
板块动能得分 = 上涨板块数 / 总板块数 × 100
涨跌停得分 = limit_up / (limit_up + limit_down) × 100
```

---

## 3. 获取完整报告

### `GET /api/crawler/report`

一次调用获取完整的市场资讯 + 情绪报告。

#### 请求参数（Query String）

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `sector` | string | 否 | `""` | 行业板块筛选 |
| `limit` | int | 否 | `20` | 资讯条数（最大 50） |
| `refresh` | string | 否 | `"0"` | 设为 `"1"` 强制刷新缓存 |

#### 响应示例

```json
{
  "success": true,
  "news": [
    {
      "title": "...",
      "summary": "...",
      "source": "...",
      "url": "...",
      "publish_time": "...",
      "sector": "...",
      "tags": []
    }
  ],
  "sentiment": {
    "score": 55.7,
    "level": "neutral",
    "breadth": { ... },
    "north_flow": -0.3,
    "sector_flows": [ ... ],
    "hot_sectors": [ ... ],
    "risk_sectors": [ ... ],
    "retrieved_at": "...",
    "data_source": "eastmoney+ths"
  },
  "errors": [],
  "retrieved_at": "2026-07-25T02:58:55+08:00"
}
```

---

## 缓存策略

| 数据类型 | 缓存时间 | 说明 |
|----------|----------|------|
| 行业资讯 | 5 分钟 | 仅综合资讯缓存，指定板块始终实时获取 |
| 市场情绪 | 1 分钟 | 确保数据实时性 |

通过 `?refresh=1` 参数可强制跳过缓存。

---

## 数据源

| 数据 | 来源 | 接口 | 更新频率 |
|------|------|------|----------|
| 财经要闻 | 东方财富 np-listapi | 公开 JSON API | 实时滚动 |
| 行业研报 | 东方财富 reportapi | 公开 JSON API | 每日更新 |
| 涨跌广度 | 同花顺热股 API | 公开 JSON API | 盘中实时 |
| 北向资金 | 东方财富 datacenter | 公开 JSON API | T+1 |
| 板块热度 | 同花顺概念标签 | 公开 JSON API | 盘中实时 |

---

## 前端调用示例

```typescript
// 获取行业资讯
const newsResp = await fetch('/api/crawler/news?limit=15');
const newsData = await newsResp.json();

// 获取市场情绪
const sentimentResp = await fetch('/api/crawler/sentiment');
const sentimentData = await sentimentResp.json();

// 获取完整报告
const reportResp = await fetch('/api/crawler/report?limit=20&refresh=1');
const reportData = await reportResp.json();

// 按行业筛选
const bankNews = await fetch('/api/crawler/news?sector=银行&limit=10');
```

---

## Python 直接调用

```python
from finance_god.crawler import CrawlerService

service = CrawlerService()

# 获取资讯
news = await service.get_news(limit=20)

# 获取情绪
sentiment = await service.get_sentiment()

# 获取完整报告
report = await service.get_full_report(sector="电子", news_limit=15)

# 强制刷新
news = await service.get_news(force_refresh=True)
```

---

## 错误处理

所有接口在数据源不可达时会降级返回部分数据，不会完全失败：

- 资讯接口：某一数据源失败时仍返回其他源的数据
- 情绪接口：单项指标获取失败时该项返回默认值（0），不影响整体评分
- 完整报告：即使部分失败也会返回 `success: true`（只要有数据），`errors` 数组记录失败详情

HTTP 状态码：
- `200` — 成功
- `502` — 所有数据源均不可达
- `500` — 服务内部错误
