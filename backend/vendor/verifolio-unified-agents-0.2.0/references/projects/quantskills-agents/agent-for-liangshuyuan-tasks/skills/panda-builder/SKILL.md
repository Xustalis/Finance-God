---
name: panda-builder
description: 当需要在 panda-trading 项目中创建或验收一个新的 BUILD skill 时，使用此 skill。该 skill 确保目录结构、代码接口、文档格式符合 BUILD 开发与生产规则。
tags: [quant, build, scaffold, development]
---

# Panda Builder — BUILD Skill 脚手架与验收规则

## 工具定位
- 工具类型：开发辅助
- 解决问题：确保每个新 BUILD skill 的目录结构、代码接口、文档模板统一合规
- 使用对象：开发者（Claude Code）

## 触发时机

每次创建新的 BUILD skill 目录或对现有 BUILD 做验收检查时，必须参照本 skill。

---

## 1. 标准目录结构

每个 BUILD 目录命名为 `build-{编号}-{名称}/`，放在项目根目录，例如：

```
build-B12-intraday-position-manager/
├── 开发产物/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── build.py        ← 主脚本，必须提供 run() 入口
│   │   └── test.py         ← 测试脚本
│   ├── references/
│   │   └── api_guide.md    ← 数据接口说明
│   └── demo.mp4
└── 生产产物/               ← 结果型 BUILD 才需要
    ├── SKILL.md
    └── 数据库.parquet
```

---

## 2. 标准代码接口

`build.py` 必须实现以下两个函数：

```python
def run(input_data, config=None):
    """
    Args:
        input_data: 调用方传入的标准结构化数据，或 PandaAI data / 项目指定数据源返回的数据
        config: dict，可选配置
    Returns:
        dict、表格型数据或其他结构化输出
    """

def validate_input(input_data):
    """
    缺字段、空数据、类型错误时必须抛出明确异常。
    """
```

---

## 3. 生产形态判断

| 形态 | 适用情况 | 生产交付 |
|---|---|---|
| 调用型 | 轻量、实时、依赖调用方输入、结果不需缓存 | `SKILL.md + scripts/` |
| 结果型 | 重计算、多人复用、定时扫描、结果需缓存 | `SKILL.md + 数据库.parquet` |
| 混合型 | 既能即时调用，也有定时结果 | `SKILL.md + scripts/ + 数据库.parquet` |

---

## 4. SKILL.md 模板（开发版）

```markdown
---
name: build-{编号}
description: 当需要{BUILD功能}时，使用此 skill。
tags: [quant, build, development, {工具类型}]
---

# {BUILD名称}

## 工具定位
- 工具类型：
- 解决问题：
- 使用对象：agent / Alpha / 人工分析

## 适用场景
- 当用户需要{场景}时

## 输入
| 字段 | 类型 | 说明 |
|---|---|---|

## 输出
| 字段 | 类型 | 说明 |
|---|---|---|

## 调用方式
from scripts.build import run
result = run(input_data, config=config)

## 可被 Alpha 调用
- 是 / 否
- 调用限制：
- 依赖数据：

## 是否需要生产结果
- 是否生成 `数据库.parquet`：是 / 否

## 依赖
- PandaAI data / 调用方传入标准结构化数据 / 项目指定数据源
```

---

## 5. 结果型 Parquet 字段标准

| 字段 | 必须 | 说明 |
|---|---:|---|
| `trade_date` | 视情况 | 结果所属日期 |
| `build_id` | 是 | BUILD 编号，如 `B12` |
| `build_name` | 是 | BUILD 名称 |
| `target_id` | 否 | 股票/合约/策略/账户等对象 |
| `result_type` | 是 | `score` / `report` / `risk_flag` / `signal_list` 等 |
| `result_value` | 是 | 核心结果值 |
| `result_json` | 否 | 复杂结构用 JSON 字符串 |
| `data_version` | 是 | 数据版本 |
| `update_time` | 是 | 结果生成时间 |

---

## 6. 验收检查清单

完成开发后逐项确认：

- [ ] `python scripts/build.py` 可独立跑通
- [ ] 提供标准 `run(input_data, config=None)` 入口
- [ ] 数据来源为 PandaAI data、调用方传入标准结构化数据或项目指定数据源
- [ ] `validate_input()` 对缺字段、空数据、非法类型抛出明确异常
- [ ] 输出字段、类型、含义固定
- [ ] `SKILL.md` 说明适用场景和调用方式
- [ ] 提供 `test.py`，覆盖正常输入、异常输入、空数据
- [ ] 提供 `demo.mp4`（3-5 分钟跑通视频）
- [ ] 结果型 BUILD：提供 `数据库.parquet` 且生产版 `SKILL.md` 说明路径

---

## 7. 不合格情况（禁止验收上线）

- 缺少 `SKILL.md`
- 没有标准 `run()` 入口
- 未使用规定数据源，且未咨询项目工作人员
- 输入输出字段不稳定
- 无测试脚本或无跑通视频
- 声称可被 Alpha 调用但无法 import
- 结果型 BUILD 缺少 `数据库.parquet`
- `result_json` 无法解析
