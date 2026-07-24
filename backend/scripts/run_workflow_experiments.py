#!/usr/bin/env python3
"""Run deterministic workflow-composition experiments and write review artifacts."""

from __future__ import annotations

import asyncio
from pathlib import Path

from research_runtime import AssetKind
from research_runtime.models import EvidenceRecord

from finance_god.experiments import build_offline_orchestrator
from finance_god.orchestration.workflows import (
    WorkflowContext,
    WorkflowExecutor,
    WorkflowIntent,
    WorkflowRun,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = WORKSPACE_ROOT / "artifacts" / "workflow-experiments"


def _evidence(source: str, excerpt: str) -> list[EvidenceRecord]:
    return [EvidenceRecord(identifier="E1", source=source, excerpt=excerpt)]


def experiment_contexts() -> list[tuple[str, WorkflowContext]]:
    return [
        (
            "01_company_research",
            WorkflowContext(
                intent=WorkflowIntent.COMPANY_RESEARCH,
                subject="示例基础设施公司",
                asset_kind=AssetKind.EQUITY,
                evidence=_evidence(
                    "公司公告（离线实验）",
                    "收入同比增长 18%，但资本开支和客户集中度同时上升。",
                ),
            ),
        ),
        (
            "02_market_context",
            WorkflowContext(
                intent=WorkflowIntent.MARKET_CONTEXT,
                subject="A 股市场环境",
                asset_kind=AssetKind.MARKET,
                evidence=_evidence(
                    "市场摘要（离线实验）",
                    "宽基指数温和上涨，波动率和融资余额同步抬升。",
                ),
                available_resources={
                    "market_bars",
                    "margin",
                    "lhb_list",
                    "option_underlying_volatility",
                },
                stage_payloads={
                    "market_monitor": {
                        "kind": "market_regime",
                        "subject": "A 股市场环境",
                        "symbol": "510300.SH",
                        "index_symbol": "000300.SH",
                        "option_underlying": "510300.SH",
                        "start_date": "20260701",
                        "end_date": "20260723",
                    }
                },
            ),
        ),
        (
            "03_portfolio_stress",
            WorkflowContext(
                intent=WorkflowIntent.PORTFOLIO_STRESS,
                subject="股指与宽基 ETF 组合",
                asset_kind=AssetKind.PORTFOLIO,
                evidence=_evidence(
                    "持仓快照（离线实验）",
                    "组合集中于宽基 ETF，近期相关性上升且融资交易活跃。",
                ),
                available_resources={
                    "future_dominant_corr",
                    "margin",
                    "lhb_list",
                },
                stage_payloads={
                    "correlation_monitor": {
                        "kind": "correlation_break",
                        "subject": "股指期货相关性",
                        "future_symbols": ["IF.CFE", "IC.CFE", "IH.CFE"],
                        "start_date": "20260701",
                        "end_date": "20260723",
                        "baseline_start_date": "20260101",
                        "baseline_end_date": "20260630",
                    },
                    "crowding_monitor": {
                        "kind": "crowding_risk",
                        "subject": "宽基 ETF 拥挤风险",
                        "symbol": "510300.SH",
                        "start_date": "20260701",
                        "end_date": "20260723",
                    },
                },
            ),
        ),
        (
            "04_strategy_validation",
            WorkflowContext(
                intent=WorkflowIntent.STRATEGY_VALIDATION,
                subject="月度 ETF 动量策略",
                asset_kind=AssetKind.SOFTWARE,
                evidence=_evidence(
                    "策略需求（离线实验）",
                    "策略仅用于仿真；月频调仓；必须声明费用、滑点、样本和失效条件。",
                ),
                available_resources={"workspace"},
            ),
        ),
        (
            "05_cooldown_review_only",
            WorkflowContext(
                intent=WorkflowIntent.STRATEGY_VALIDATION,
                subject="高焦虑状态下的策略复核",
                asset_kind=AssetKind.PORTFOLIO,
                evidence=_evidence(
                    "用户状态（已同意的离线实验）",
                    "用户确认当前处于冷静期，仅允许查看证据和风险说明。",
                ),
                cooldown_active=True,
            ),
        ),
        (
            "06_stale_data_review",
            WorkflowContext(
                intent=WorkflowIntent.MARKET_CONTEXT,
                subject="陈旧市场数据诊断",
                asset_kind=AssetKind.MARKET,
                evidence=_evidence(
                    "数据质量事件（离线实验）",
                    "行情快照已超过允许时效，两个来源存在冲突。",
                ),
                market_data_usable=False,
            ),
        ),
        (
            "07_user_pause_block",
            WorkflowContext(
                intent=WorkflowIntent.PORTFOLIO_STRESS,
                subject="用户暂停后的组合请求",
                asset_kind=AssetKind.PORTFOLIO,
                evidence=_evidence(
                    "控制事件（离线实验）",
                    "用户已暂停所有 Agent 和未来订单。",
                ),
                user_paused=True,
            ),
        ),
    ]


def _write_index(output_dir: Path, runs: list[tuple[str, WorkflowRun]]) -> None:
    lines = [
        "# Multi-Agent 工作流组合实验",
        "",
        "> 所有结果均由离线确定性适配器生成，用于验证编排、门禁和产物结构；"
        "不代表真实投资结论。",
        "",
        "| 实验 | 场景 | 选中工作流 | 产物 | 状态 | 阶段 | Agent |",
        "| --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for name, run in runs:
        agent_count = sum(len(stage.run.results) for stage in run.stage_runs)
        lines.append(
            "| "
            f"[{name}]({name}.md) | {run.scenario.value} | "
            f"{run.selected_workflow or '-'} | {run.artifact.artifact_kind.value} | "
            f"{run.artifact.status.value} | {len(run.stage_runs)} | {agent_count} |"
        )
    lines.extend(
        [
            "",
            "每个实验同时提供 Markdown 人读报告和 JSON 机器契约。JSON 包含路由选择、"
            "逐阶段 `AgentRun`、证据引用、限制、待审核动作和最终产物。",
            "",
            "## 实验观察",
            "",
            "- 正常研究路径会分阶段运行，后续阶段通过 `WF_Sx_Ay` 引用前序 Agent 输出。",
            "- 市场与组合场景先运行确定性 Monitor，再交给 Prompt Agent 解释和治理。",
            "- 冷静期不会继续策略验证，而是切换到只读复核并标记 `attention_required`。",
            "- 数据陈旧会切换到数据质量诊断，不生成正常市场结论。",
            "- 用户暂停时不会调用任何 Agent，最终只产生可审计的阻断通知。",
            "",
        ]
    )
    (output_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


async def run_experiments(output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    executor = WorkflowExecutor(build_offline_orchestrator())
    runs: list[tuple[str, WorkflowRun]] = []
    for name, context in experiment_contexts():
        run = await executor.execute(workflow_id=name, context=context)
        (output_dir / f"{name}.json").write_text(
            run.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (output_dir / f"{name}.md").write_text(
            run.artifact.to_markdown(),
            encoding="utf-8",
        )
        runs.append((name, run))
    _write_index(output_dir, runs)
    print(f"Generated {len(runs)} workflow experiments in {output_dir}")


if __name__ == "__main__":
    asyncio.run(run_experiments())
