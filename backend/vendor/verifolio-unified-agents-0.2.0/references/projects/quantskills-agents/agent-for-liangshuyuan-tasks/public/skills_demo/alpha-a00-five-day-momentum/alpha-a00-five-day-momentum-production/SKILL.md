---
name: alpha-a00-five-day-momentum-production
description: 当需要读取五日动量 Alpha 的生产计算结果时，使用此 skill。该 skill 只读取已生成的 Parquet 结果，不在调用时重新计算因子。
tags: [quant, alpha, production, stock]
---

# 五日动量 Alpha 生产结果

## 适用场景

- 当用户需要查询五日动量 Alpha 最新结果时
- 当交易 agent 需要使用该因子辅助交易判断时

## 结果文件

- 文件路径：`database.parquet`
- 数据格式：Parquet
- 更新频率：每日收盘后
- 生成方式：生产任务定时计算

## 主键

- `trade_date`
- `factor_id`
- `ts_code`

## 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| trade_date | string | 交易日期 |
| asset_type | string | 固定为 `stock` |
| ts_code | string | 股票代码 |
| factor_id | string | 因子编号 |
| factor_name | string | 因子名称 |
| factor_value | float | 5 日动量原始值 |
| score | float | 标准化评分，0-100 |
| rank | int | 横截面排名 |
| signal | string | `buy` / `hold` |
| confidence | float | 置信度 |
| data_version | string | 数据版本 |
| update_time | string | 结果生成时间 |

## 读取规则

交易 agent 读取 `database.parquet`，优先使用最新有效交易日结果。若最新结果不存在，可回退最近有效交易日，但必须说明数据日期。

## 禁止行为

- 不允许在 agent 调用时重新拉取原始行情。
- 不允许在 agent 调用时重新计算因子。
- 不允许手工修改 Parquet 结果。
