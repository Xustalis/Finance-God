# Multi-Agent 工作流组合实验

## 目标

实验验证同一个 Multi-Agent Runtime 在不同业务状态下不会固定走一条链路。场景选择层先按
产品安全优先级处理暂停、硬风控、冷静期和数据异常，再选择分阶段 Agent 组合。

## 选择矩阵

| 情况 | 工作流 | 阶段组合 | 最终产物 |
| --- | --- | --- | --- |
| 公司基本面与投资论点研究 | `company_research` | 事实审阅 → 正反观点与风险辩论 → 研究治理汇总 | `ResearchMemo` |
| 市场数据可用，需要判断市场环境 | `market_context` | 确定性市场 Monitor → 市场/新闻/情绪解释 → 治理复核 | `MarketContext` |
| 组合相关性与拥挤风险上升 | `portfolio_stress` | 相关性 Monitor → 拥挤度 Monitor → 风险辩论与治理 | `PortfolioRiskReview` |
| 有效授权与工作区资源下验证量化策略 | `strategy_validation` | 需求 → Alpha 设计 → 回测 → 测试 → 治理汇总 | `StrategyValidationDossier` |
| 冷静期或策略授权失效 | `review_only` | 证据与下行风险只读复核 | `ReviewOnlyMemo`，状态为 `attention_required` |
| 市场数据陈旧或冲突 | `data_quality_review` | 数据缺口与可用性诊断 | `DataQualityReport`，状态为 `attention_required` |
| 用户暂停或硬风控阻断 | 不调用 Agent | 直接终止 | `WorkflowBlockNotice`，状态为 `blocked` |

选择顺序固定为：

1. 用户暂停；
2. 硬风控；
3. 冷静期；
4. 数据与市场异常；
5. 授权状态；
6. 正常业务工作流。

该顺序意味着低优先级策略机会不能覆盖高优先级阻断。

## 分阶段证据传递

每个阶段仍使用上游包的 `AgentRequest` 和 `AgentRun`。阶段完成后，执行器把 Agent 摘要转换
成新的 `EvidenceRecord`，例如 `WF_S1_A1`，加入下一阶段输入。这样汇总 Agent 能引用前序
结果，同时每条引用都可回溯到具体阶段和 Agent。

同一阶段内的多个 Agent 可以并行运行；阶段之间严格顺序运行。因此“事实审阅”和“风险辩论”
可以各自并行，但最终治理阶段一定在前序证据就绪后开始。

## 最终产物契约

每次工作流返回一个 `WorkflowRun`，包含：

- 场景选择结果与理由；
- 每个阶段的原始 `AgentRun`、路由计划和结果；
- 最终 `WorkflowArtifact`；
- 证据 ID、Agent ID、路由提示和未执行的待审核动作。

最终产物提供两种形式：

1. **JSON**：机器可读，适合 API、审计、持久化和后续组合服务；
2. **Markdown**：人类可读，包含摘要、证据支持判断、未知项、Agent 贡献、待审核动作和下一步。

`proposed_actions` 在两种形式中都明确标为“未执行”。实验不会创建订单、修改授权或模拟外部
操作成功。

## 运行实验

```bash
cd backend
.venv/bin/python -m scripts.run_workflow_experiments
```

输出目录为仓库根级 `artifacts/workflow-experiments/`。当前包含 7 个场景，每个场景同时
生成 `.json` 与 `.md`，并由 `index.md` 汇总。

实验使用 `finance_god.experiments` 下的确定性模型和数据适配器，不访问模型服务或市场数据。
生产环境仍通过 `MultiAgentRuntime.from_environment()` 注入真实适配器。
