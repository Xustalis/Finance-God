---
name: build-b00-price-change-flag-production
description: 当需要读取涨跌幅异常标记的生产结果时，使用此 skill。该 skill 读取已生成的 Parquet 结果，不重复执行重计算流程。
tags: [quant, build, production, data-processing]
---

# 涨跌幅异常标记生产结果

## 工具定位

- 工具类型：结果型 BUILD
- 服务对象：agent / Alpha / 人工复盘
- 是否可被 Alpha 调用：是

## 结果文件

- 文件路径：`database.parquet`
- 数据格式：Parquet
- 更新频率：每日收盘后
- 生成任务：调用开发产物中的 `scripts/build.py`，对当日标准行情数据生成异常标记

## 主键

- `trade_date`
- `build_id`
- `target_id`
- `result_type`

## 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| trade_date | string | 结果所属日期 |
| build_id | string | BUILD 编号 |
| build_name | string | BUILD 名称 |
| target_id | string | 股票代码 |
| result_type | string | 固定为 `price_change_flag` |
| result_value | string | `up_spike` / `down_spike` / `normal` |
| result_json | string | JSON 字符串，包含涨跌幅和阈值 |
| data_version | string | 数据版本 |
| update_time | string | 结果生成时间 |

## 读取规则

交易 agent 读取 `database.parquet`，按日期、股票代码和结果类型查询。默认使用最新有效交易日结果。

## 禁止行为

- 不允许多人查询时重复触发重计算。
- 不允许手工修改 Parquet 结果。
- 生产结果异常时必须提示数据日期和异常原因。
