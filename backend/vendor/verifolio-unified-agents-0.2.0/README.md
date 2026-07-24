# VeriFolio Unified Agents 0.2.0

这是 VeriFolio 统一 Agent 运行时的可移植源码包，包含：

- 44 个可用 Agent：39 个结构化 Prompt Agent、4 个确定性 Monitor、1 个 FinRobot
  Metrics Agent；
- 统一 `AgentDefinition`、Registry、能力路由、三档执行配置和 LangGraph Runner；
- CLI、stdio MCP、生成目录、测试、必要的上游依据文件与许可证；
- `dist/` 下的 Python Wheel。

包内不含 `.env`、API 密钥、虚拟环境、缓存、模型运行记录或 FinRobot 输出工件。

## 推荐安装

```bash
cd agent_framework
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,mcp]'
.venv/bin/python -m research_runtime.catalog --verify
.venv/bin/python -m pytest -q
```

需要 PandaData Monitor 时安装 `panda` 可选依赖，并从 `.env.example` 创建本地
`agent_framework/.env`。不要把凭据提交或重新打入分发包。

## 入口

```bash
agent_framework/.venv/bin/verifolio-agent --help
agent_framework/.venv/bin/verifolio-agent-catalog --verify
agent_framework/.venv/bin/verifolio-agent-mcp
```

完整使用方法见 `agent_framework/README.md`。Prompt Agent 的 `proposed_actions` 只是待审核
请求；本包不会发布仓库、启动 CTP、跟单或执行订单。

