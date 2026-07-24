---
name: build-b00-price-change-flag
description: 当需要识别股票涨跌幅异常状态时，使用此 skill。该 BUILD 提供涨跌幅异常标记能力，可被 agent 或 Alpha 调用。
tags: [quant, build, development, data-processing]
---

# 涨跌幅异常标记 BUILD

## 工具定位

- 工具类型：数据处理型 BUILD
- 解决问题：把标准行情数据转换为稳定的涨跌幅异常标记
- 使用对象：agent / Alpha / 人工复盘

## 适用场景

- 当复盘 agent 需要快速筛选大涨或大跌股票时
- 当 Alpha 需要过滤极端涨跌样本时
- 当人工分析需要一份结构化异常列表时

## 输入

BUILD 输入来自 Panda data SDK 拉取的真实日频行情数据，并转换为标准 Python 结构化数据。正式生产时可由 PandaAI data 或项目指定数据源先拉取行情数据，再传入本工具。

| 字段 | 类型 | 说明 |
|---|---|---|
| trade_date | string | 交易日期 |
| ts_code | string | 股票代码 |
| close | float | 当日收盘价 |
| pre_close | float | 前收盘价 |

## 输出

| 字段 | 类型 | 说明 |
|---|---|---|
| trade_date | string | 交易日期 |
| build_id | string | BUILD 编号 |
| build_name | string | BUILD 名称 |
| target_id | string | 股票代码 |
| result_type | string | 固定为 `price_change_flag` |
| result_value | string | `up_spike` / `down_spike` / `normal` |
| result_json | string | JSON 字符串，包含涨跌幅和阈值 |
| data_version | string | 数据版本 |
| update_time | string | 结果生成时间 |

## 调用方式

Agent 使用本 skill 时，应先确认输入字段完整，再调用 `run` 或直接运行脚本拉取真实行情。

```python
from scripts.build import run

result = run(input_data, config={"up_threshold": 0.02, "down_threshold": -0.02})
```

运行 `python scripts/build.py` 前需要设置 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD` 环境变量。
可选设置 `PANDA_DATA_START_DATE` 和 `PANDA_DATA_END_DATE` 控制样本区间。

## Agent 执行规则

1. 若已有标准行情输入，优先调用 `run(input_data, config=...)`。
2. 若需要演示完整开发流程，可运行 `python scripts/build.py`，脚本会通过 Panda data 拉取真实行情。
3. 必须运行 `python scripts/test.py`，确认正常输入、空输入、缺字段和真实数据场景均可通过。
4. 如果测试失败，必须报告失败用例和错误信息，不得交给生产侧使用。

## 成功标准

- 输出字段包含 `trade_date`、`target_id`、`result_type`、`result_value`、`result_json`。
- `result_value` 只能是 `up_spike`、`down_spike`、`normal`。
- `result_json` 必须是可解析 JSON，并包含 `change_pct`、`up_threshold`、`down_threshold`。
- 真实数据运行时，`data_version` 应为 `real-v1`。

## 与生产产物的关系

开发产物用于生成和测试 BUILD 工具；生产产物用于读取已落地结果。Agent 在开发验证时可以运行本 skill 的脚本，但在生产查询时应使用 `build-b00-price-change-flag-production`，不要因为多人查询重复触发重计算。

## 可被 Alpha 调用

- 是
- 调用限制：输入必须包含 `trade_date`、`ts_code`、`close`、`pre_close`
- 依赖数据：日频行情数据

## 是否需要生产结果

- 是否生成 `数据库.parquet`：演示任务中生成
- 更新频率：每日收盘后
- 字段结构：见生产产物 `SKILL.md`

## 依赖

- pandas
- pyarrow 或 fastparquet，用于写入 Parquet
- panda-data
- requests
