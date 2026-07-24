# 统一 Agent 与 Skill 目录

Agent 目录不是运行时的第二份配置。43 个 Agent 均来自
`research_runtime.definitions.AGENT_DEFINITIONS`，生成文件只供审阅和外部发现。

每条 Agent 记录包含：

- 稳定 `agent_id`、来源、说明与本地适配器类型；
- 最低执行配置、自动路由任务/标签、资源和逐次授权要求；
- 本地定义路径、上游依据和许可证边界。

目录不再保留无源码的宏观轮动条目，也不把 AI‑Trader 平台身份表示为 Agent。
Skill 表仍记录参考项目中的 Skill 描述符及其可用性，不代表对应外部服务已获授权。

```bash
cd agent_framework
.venv/bin/python scripts/build_agent_catalog.py
.venv/bin/python scripts/build_agent_catalog.py --check
.venv/bin/python -m research_runtime.catalog --verify
.venv/bin/python -m research_runtime.catalog --list agents
```
