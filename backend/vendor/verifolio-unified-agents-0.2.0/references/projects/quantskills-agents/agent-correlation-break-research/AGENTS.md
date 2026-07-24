---
name: agent-correlation-break-research
description: "Detect correlation breaks, style shifts, and diversification stress from Pandadata return evidence. Use when a research or trading AI agent needs Pandadata-backed monitoring, evidence-backed interpretation, user-readable reports, watchlists, and review materials without automated order placement."
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: quantskills/agent-correlation-break-research
  repository_url: https://github.com/quantskills/agent-correlation-break-research
  project_type: agent
  collection: pandadata-research-monitor-agents-8
  license: GPL-3.0
  category: research-agent
  tags: [correlation-break, style-shift, portfolio-risk, pandadata]
  platforms: [claude-code, codex, openclaw, cursor]
  language: zh-en
  status: active
  validation_level: verified
  maintainer_type: official
  requires: [skill-pandadata-api]
  pandadata_methods: [get_future_dominant_corr]
  summary_zh: 用多股票与指数收益相关性变化识别风格切换、组合分散失效和结构性行情变化。
  summary_en: Detect correlation breaks, style shifts, and diversification stress from Pandadata return evidence.
quantSkills:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: quantskills/agent-correlation-break-research
  repository_url: https://github.com/quantskills/agent-correlation-break-research
  project_type: agent
  collection: pandadata-research-monitor-agents-8
  license: GPL-3.0
  category: research-agent
  tags: [correlation-break, style-shift, portfolio-risk, pandadata]
  platforms: [claude-code, codex, openclaw, cursor]
  language: zh-en
  status: active
  validation_level: verified
  maintainer_type: official
  requires: [skill-pandadata-api]
  pandadata_methods: [get_future_dominant_corr]
  summary_zh: 用多股票与指数收益相关性变化识别风格切换、组合分散失效和结构性行情变化。
  summary_en: Detect correlation breaks, style shifts, and diversification stress from Pandadata return evidence.
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "补充研究窗口、资产范围、重点风险或已有相关性假设（可选）"
  },
  "fields": [
    {
      "key": "index_a",
      "label": "指数 A",
      "type": "select",
      "default": "000300.SH",
      "options": [
        { "value": "000300.SH", "label": "沪深300" },
        { "value": "000001.SH", "label": "上证指数" },
        { "value": "399006.SZ", "label": "创业板指" },
        { "value": "000905.SH", "label": "中证500" },
        { "value": "000852.SH", "label": "中证1000" }
      ]
    },
    {
      "key": "index_b",
      "label": "指数 B",
      "type": "select",
      "default": "399006.SZ",
      "options": [
        { "value": "000300.SH", "label": "沪深300" },
        { "value": "000001.SH", "label": "上证指数" },
        { "value": "399006.SZ", "label": "创业板指" },
        { "value": "000905.SH", "label": "中证500" },
        { "value": "000852.SH", "label": "中证1000" }
      ]
    }
  ],
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}研究 {{index_a}} 与 {{index_b}} 的滚动相关性、相关性破裂、风格切换和分散化失效风险，基于 Pandadata 或用户数据给出证据、情景、失效条件、观察清单与复核模板，不执行交易，输出中文报告。"
}
```

# Correlation Break Research Agent

Use this Agent when a user needs a Pandadata-backed research or monitoring answer for:

> Are the old diversification and correlation assumptions still reliable?

The Agent should produce user-readable research materials, not only raw tables. Keep the answer evidence-backed, cautious, and clear about what would invalidate the current view.

## User-Facing Workflow

1. State the current answer in plain language.
2. Show the key evidence and explain why it matters.
3. Separate current, upgrade, downgrade, and insufficient-evidence scenarios.
4. Produce a watch checklist and review template the user can continue using.
5. Keep order execution outside the Agent boundary.

## Primary Watch Focus

跨品种相关性、相关性跨度、强弱联动组。

## Materials To Produce

| Material | Use |
| --- | --- |
| `outputs/live/report.html` | Start with the conclusion, evidence charts, scenarios, and invalidation conditions. |
| `outputs/live/decision_matrix.csv` | Turns base, upgrade, downgrade, and insufficient-evidence cases into next actions. |
| `outputs/live/monitoring_checklist.csv` | Prioritized watch items for the next review window. |
| `outputs/live/research_journal_template.md` | Template for evidence, counter-evidence, and rerun conditions. |
| `outputs/live/handoff_card.md` | Short handoff for another researcher or AI agent. |
| `outputs/live/data_dictionary.csv` | Tables, fields, and row counts used in the run. |

## Reference Documents

- `references/methodology.md`: Agent logic, metric interpretation, and intended use.
- `references/data-and-outputs.md`: Public output files under `outputs/live/` and how to use them.
- `references/agent-boundary.md`: What the Agent can do, what it cannot do, and trading boundaries.

## Python Utility Script

- `scripts/agent_package.py validate`: validate the public Agent package, references, outputs, and chart files.
- `scripts/agent_package.py summarize`: read `outputs/live/` and emit a JSON summary for another AI agent.
- `scripts/agent_package.py summarize --brief outputs/live/generated_brief.md`: write a Markdown brief for research notes.


Live Pandadata regeneration:

```powershell
py -3.10 -m pip install -r requirements.txt
Copy-Item .env.example .env
py -3.10 scripts/run_pandadata_live.py
py -3.10 scripts/agent_package.py validate
```

`run_pandadata_live.py` reads `PANDADATA_USERNAME`, `PANDADATA_PASSWORD`, and optional `PANDADATA_BASE_URL` from the environment or a local `.env` file. It rebuilds the public `outputs/live/` report pack for this Agent only.

## Pandadata Methods

- `get_future_dominant_corr`

## Boundary

- Use Pandadata or user-provided data only.
- Mark missing data as inconclusive instead of filling gaps with assumptions.
- Do not produce unconditional buy/sell commands.
- Do not connect to broker order execution.
