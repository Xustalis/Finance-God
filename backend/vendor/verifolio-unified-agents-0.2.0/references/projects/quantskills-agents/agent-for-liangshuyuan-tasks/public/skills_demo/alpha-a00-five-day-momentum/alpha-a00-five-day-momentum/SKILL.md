---
name: alpha-a00-five-day-momentum
description: 当需要开发、计算、验证五日动量因子时，使用此 skill。支持因子计算、无未来函数检测、IC/ICIR 回测评估和信号输出。
tags: [quant, alpha, development, stock]
---

# 五日动量 Alpha

## 适用场景

- 当用户需要计算股票短期动量因子时
- 当用户需要验证一个简单 Alpha 的完整交付流程时
- 当用户需要生成候选交易信号样例时

## 因子逻辑

- 核心假设：过去 5 个交易日表现更强的股票，短期内可能延续相对强势。
- 计算公式：`factor_value = close(t) / close(t-5) - 1`
- 排序方向：因子值越大越好
- 适用市场：A 股日频股票样例

## 输入数据

本示例使用 Panda data SDK 拉取真实日频股票行情数据。正式开发时，因子计算必须使用 PandaAI data 数据拉取库或项目指定数据源获取数据。

| 字段 | 说明 | 来源 |
|---|---|---|
| trade_date | 交易日期 | 行情/交易日历 |
| ts_code | 股票代码 | 行情源 |
| close | 收盘价 | 行情源 |

## 输出结果

| 字段 | 说明 |
|---|---|
| factor_value | 5 日动量原始值 |
| score | 0-100 标准化评分 |
| rank | 当日横截面排名 |
| signal | 交易信号，示例中前 30% 为 `buy`，其余为 `hold` |

## 因子评价标准

Alpha 任务需要同时报告因子预测能力和策略层表现，不能只给单一收益结果。

| 分类 | 指标 | 方向 | 说明 |
|---|---|---|---|
| Factor Predictive Power | `IC` | 越高越好 | 因子值与下一期收益的 Pearson 相关 |
| Factor Predictive Power | `ICIR` | 越高越好 | IC 均值 / IC 标准差 |
| Factor Predictive Power | `Rank IC` | 越高越好 | 因子排名与下一期收益排名的 Spearman 相关 |
| Factor Predictive Power | `Rank ICIR` | 越高越好 | Rank IC 均值 / Rank IC 标准差 |
| Strategy Performance | `IR(SHR*)` | 越高越好 | 示例多头组合收益的信息比率/年化 Sharpe 近似 |
| Strategy Performance | `CR` | 越高越好 | 累计收益 / 最大回撤绝对值 |
| Strategy Performance | `ARR(%)` | 越高越好 | 年化收益率 |
| Strategy Performance | `MDD(%)` | 越低越好 | 最大回撤 |

硬性要求：

- 不允许未来函数：因子在 `t` 日形成时，只能使用 `t` 日及以前可获得的数据。
- 不允许偷价：策略评估不得假设用 `t` 日收盘后才知道的信号，在同一个 `t` 日收盘价成交。
- 若只有收盘价数据，本示例的策略层收益仅作为 MVP 演示口径；正式策略应使用下一可交易价，并计入手续费、滑点和停牌涨跌停等约束。

## 使用方式

Agent 使用本 skill 时，应在 `开发产物` 目录下执行命令，优先按下面顺序运行：

```bash
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

运行前需要设置 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD` 环境变量。
可选设置 `PANDA_DATA_START_DATE` 和 `PANDA_DATA_END_DATE` 控制样本区间。

## Agent 执行规则

1. 先运行 `scripts/factor.py`，确认 Panda data 能返回真实行情，且因子结果非空。
2. 再运行 `scripts/validate.py`，确认字段完整、时间顺序正确、无未来函数问题。
3. 最后运行 `scripts/backtest.py`，输出 `IC`、`ICIR`、`Rank IC`、`Rank ICIR`、`IR(SHR*)`、`CR`、`ARR(%)`、`MDD(%)` 等最小回测指标，用于判断示例是否跑通。
4. 如果任一步失败，必须报告失败命令、错误信息和数据日期，不得直接进入生产。

## 成功标准

- `factor.py` 能输出包含 `factor_value`、`score`、`rank`、`signal` 的结果。
- `validate.py` 输出验证通过信息。
- `backtest.py` 至少输出 `IC`、`ICIR`、`Rank IC`、`Rank ICIR`、`IR(SHR*)`、`CR`、`ARR(%)`、`MDD(%)`、`样本数`。
- 回测输出必须说明收益评估口径，避免未来函数和偷价。
- 结果中的 `data_version` 应为真实数据版本，例如 `real-v1`。

## 与生产产物的关系

开发产物用于计算、验证和回测；生产产物用于读取已生成结果。Agent 在开发验证时可以运行本 skill 的脚本，但在生产查询时应使用 `alpha-a00-five-day-momentum-production`，不要临时重算因子。

## 验收要求

- 不允许未来函数。
- 必须有样本外验证。
- 必须有回测指标。
- 正式任务必须使用 PandaAI data 或项目指定数据源实现。
- 不通过验证不得进入生产。

## 依赖

- Python 3.10+
- panda-data
- requests
- pandas
- pyarrow 或 fastparquet，用于写入 Parquet
