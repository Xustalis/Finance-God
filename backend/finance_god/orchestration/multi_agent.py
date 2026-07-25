"""Async integration for the VeriFolio unified multi-agent runtime."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from difflib import SequenceMatcher
from pathlib import Path
from typing import Final

from dotenv import load_dotenv
from research_runtime import (
    AgentDefinition,
    AgentPlan,
    AgentRequest,
    AgentRun,
    AgentRunner,
)
from research_runtime.config import FmpSettings, Settings
from research_runtime.llm import OpenAICompatibleChat
from research_runtime.models import PandaDataDataset

from finance_god.agents.language_policy import NATURAL_CHINESE_POLICY

from .crawler_data_provider import CrawlerDataProvider
from .market_data_provider import FinanceGodMarketDataProvider

_PROJECT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
_PANDA_RESOURCES: Final = frozenset(dataset.value for dataset in PandaDataDataset)
_QUICK_COMMAND_STAGES: Final = frozenset(("initial", "after_answer", "after_workflow"))
_FORBIDDEN_QUICK_COMMAND_TEXT: Final = (
    "保证收益",
    "稳赚",
    "替我下单",
    "直接下单",
    "提交订单",
    "撤单",
    "资金划转",
    "修改设置",
    "读取设置",
)
_GENERIC_QUICK_COMMANDS: Final = (
    "分析当前标的",
    "查看当前标的",
    "研究当前标的",
    "分析一下",
    "继续分析",
)


def _next_stream_chunk(iterator: Iterator[str]) -> tuple[bool, str]:
    try:
        return True, next(iterator)
    except StopIteration:
        return False, ""


class MultiAgentRuntime:
    """Expose the synchronous unified runtime through Finance-God's async API."""

    def __init__(
        self,
        runner: AgentRunner,
        *,
        chat_client: OpenAICompatibleChat | None = None,
        available_resources: frozenset[str] = frozenset(),
    ) -> None:
        self._runner = runner
        self._chat_client = chat_client
        self._available_resources = available_resources

    @classmethod
    def from_environment(
        cls,
        *,
        max_concurrency: int = 4,
        enable_panda_data: bool = True,
        enable_finrobot_metrics: bool = True,
    ) -> MultiAgentRuntime:
        """Build a fully configured runtime with Finance-God owned adapters.

        The data provider uses CrawlerDataProvider as the primary source for
        sentiment (MARGIN dataset), falling back to PandaData for market bars
        and other quantitative datasets.
        """
        load_dotenv(_PROJECT_ENV_FILE, override=False)
        settings = Settings.from_environment()
        # Build PandaData provider as fallback for market bars and derivatives
        panda_provider = (
            FinanceGodMarketDataProvider.from_environment()
            if enable_panda_data
            else None
        )

        # CrawlerDataProvider handles MARGIN via crawler sentiment,
        # delegates everything else to the PandaData fallback
        data_provider = CrawlerDataProvider(fallback=panda_provider)

        chat_client = OpenAICompatibleChat(settings)
        runner = AgentRunner(
            chat_client=chat_client,
            data_provider=data_provider,
            fmp_settings=(
                FmpSettings.from_environment() if enable_finrobot_metrics else None
            ),
            max_concurrency=max_concurrency,
        )
        resources: set[str] = {"workspace"}
        if enable_panda_data:
            resources.update(_PANDA_RESOURCES)
        if enable_finrobot_metrics:
            resources.add("fmp")
        return cls(
            runner,
            chat_client=chat_client,
            available_resources=frozenset(resources),
        )

    async def run(self, request: AgentRequest) -> AgentRun:
        """Route and execute a request without blocking the application's event loop."""
        return await asyncio.to_thread(self._runner.run, request)

    async def compose_desk_turn(
        self,
        *,
        message: str,
        section: str,
        symbol: str,
        mode: str,
        workflow_title: str | None,
        action_catalog: tuple[dict[str, str], ...],
        profile_projection: dict[str, object],
        portfolio_projection: dict[str, object],
        include_answer: bool = True,
    ) -> dict[str, object]:
        """Generate one coherent response for a server-approved desk route."""
        if self._chat_client is None:
            raise RuntimeError("desk decision Agent is not configured")
        system_prompt = (
            "你是 Finance-God 交易台的对话与语义动作 Agent。服务端已经确定执行方式，"
            "你不能改变 mode 或工作流。只输出一个 JSON 对象，且只含 routing_reason、"
            "answer_text、ui_actions 三个键。routing_reason 是不超过80个汉字的一句简体中文；"
            f"mode=answer 时 answer_text {'必须直接、自然、简洁地回答用户' if include_answer else '必须为 null，回答将由独立流生成'}，"
            "mode=workflow 时必须"
            "为 null，且不能声称工作流已完成。ui_actions 只在用户明确要求改变左侧界面时使用"
            "给定动作目录；没有明确操作时返回空数组。每项只含 action_id 和 parameters，"
            "parameters 的键和值必须都是字符串。禁止提交订单、撤单、资金划转、设置、登录、"
            "DOM、CSS、坐标或任意点击。交易意图最多只能切到交易页并预填仿真草稿，不得描述为"
            "已下单。fill_trade_draft 只能使用 side、quantity、price_type，side 仅 buy/sell，"
            "price_type 仅 market/limit，只有 limit 可增加 limit_price；未指定价格时使用 market。"
            "用户画像投影是服务端提供的可信脱敏上下文。available=true 时必须使用其中已有的"
            "风险等级、损失容忍、投资方向等字段，不得声称这些字段缺失；available=false 时才可"
            "明确说明画像不可用。仿真持仓投影同样是可信只读上下文；available=true 时不得声称"
            "个人持仓缺失，positions 为空表示当前确实没有持仓。所有持仓必须明确称为仿真数据。"
            "画像与持仓均不包含的行情、基本面或事件事实不得补造。"
            f"answer_text 还必须遵守以下语言规则：{NATURAL_CHINESE_POLICY}"
        )
        user_prompt = (
            f"用户问题：{message}\n"
            f"当前工作区：{section}\n"
            f"标的：{symbol}\n"
            f"已批准执行方式：{mode}\n"
            f"工作流：{workflow_title or '无，直接回答'}\n"
            "用户画像投影："
            f"{json.dumps(profile_projection, ensure_ascii=False, sort_keys=True)}\n"
            "仿真持仓投影："
            f"{json.dumps(portfolio_projection, ensure_ascii=False, sort_keys=True)}\n"
            f"动作目录：{json.dumps(action_catalog, ensure_ascii=False)}"
        )
        raw = await asyncio.to_thread(
            self._chat_client.complete,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        try:
            turn = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError("desk turn Agent returned invalid JSON") from error
        if not isinstance(turn, dict) or set(turn) != {
            "routing_reason",
            "answer_text",
            "ui_actions",
        }:
            raise RuntimeError("desk turn Agent returned an invalid object")
        routing_reason = " ".join(str(turn["routing_reason"]).split()).strip()
        answer_text = turn["answer_text"]
        actions = turn["ui_actions"]
        if not routing_reason:
            raise RuntimeError("desk turn Agent returned an empty routing reason")
        if mode == "answer" and include_answer:
            if not isinstance(answer_text, str) or not answer_text.strip():
                raise RuntimeError("desk turn Agent returned an empty answer")
            answer_text = " ".join(answer_text.split()).strip()[:2_000]
        elif answer_text is not None:
            raise RuntimeError("workflow desk turn must not include an answer")
        if not isinstance(actions, list) or len(actions) > 10:
            raise RuntimeError("desk turn Agent returned an invalid action batch")
        if any(not isinstance(item, dict) for item in actions):
            raise RuntimeError("desk turn Agent returned a non-object action")
        return {
            "routing_reason": routing_reason[:500],
            "answer_text": answer_text,
            "ui_actions": actions,
        }

    async def stream_desk_answer(
        self,
        *,
        message: str,
        section: str,
        symbol: str,
    ) -> AsyncIterator[str]:
        """Stream a direct answer from the configured provider."""
        if self._chat_client is None:
            raise RuntimeError("desk answer Agent is not configured")
        system_prompt = (
            "你是 Finance-God 交易台的对话 Agent。直接、自然、简洁地回答用户。"
            "不得声称已经取得未提供的实时行情、研究证据或执行结果；不得提交订单、"
            "撤单、划转资金或更改设置。只输出面向用户的回答正文，不要输出 JSON、"
            f"标题前缀或路由说明。语言规则：{NATURAL_CHINESE_POLICY}"
        )
        user_prompt = (
            f"用户问题：{message}\n"
            f"当前工作区：{section}\n"
            f"当前标的：{symbol}"
        )
        iterator: Iterator[str] = self._chat_client.stream_complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        while True:
            has_value, chunk = await asyncio.to_thread(_next_stream_chunk, iterator)
            if not has_value:
                break
            yield chunk

    async def generate_desk_quick_commands(
        self,
        *,
        stage: str = "initial",
        section: str,
        symbol: str,
        instrument_name: str,
        profile_projection: dict,
        answer_text: str | None = None,
        workflow_evidence: dict | None = None,
    ) -> tuple[str, str, str]:
        """Generate and validate contextual suggestions for one conversation stage."""
        if self._chat_client is None:
            raise RuntimeError("desk quick-command Agent is not configured")
        if stage not in _QUICK_COMMAND_STAGES:
            raise ValueError(f"unsupported quick-command stage: {stage}")
        system_prompt = (
            "你为 Finance-God 桌面交易台生成三条可点击的快捷指令。"
            "三条依次承担：理解当前结论、核查反方或风险、推进下一步。"
            "每条必须包含当前股票名称或代码，并根据所处阶段承接答案或正式工作流证据。"
            "不要套用固定句式，不复述字段，不使用“分析/查看/研究当前标的”等空泛模板。"
            "三条必须具体、自然、语义不同，每条不超过30个汉字。"
            "只允许研究、解释、比较、核查和仿真草稿相关任务；不得承诺收益、提交或撤销"
            "订单、划转资金、读取或修改设置，也不得声称读取未提供的数据。"
            '只输出 JSON 字符串数组，例如 ["指令一","指令二","指令三"]。'
            f"措辞同时遵守以下规则：{NATURAL_CHINESE_POLICY}"
        )
        user_prompt = (
            f"建议阶段：{stage}\n"
            f"工作区：{section}\n"
            f"当前标的：{instrument_name}（{symbol}）\n"
            "脱敏画像："
            f"{json.dumps(profile_projection, ensure_ascii=False, sort_keys=True)}\n"
            f"刚完成的直接回答：{answer_text or '无'}\n"
            "正式工作流证据："
            f"{json.dumps(workflow_evidence, ensure_ascii=False, sort_keys=True) if workflow_evidence else '无'}"
        )
        last_error: RuntimeError | None = None
        for attempt in range(2):
            raw = await asyncio.to_thread(
                self._chat_client.complete,
                system_prompt=system_prompt,
                user_prompt=(
                    user_prompt
                    if attempt == 0
                    else f"{user_prompt}\n上次输出不合格：{last_error}。请完整重写三条。"
                ),
            )
            try:
                return _validated_quick_commands(
                    raw,
                    symbol=symbol,
                    instrument_name=instrument_name,
                )
            except RuntimeError as error:
                last_error = error
        raise last_error or RuntimeError("quick-command Agent returned invalid output")

    def plan(self, request: AgentRequest) -> AgentPlan:
        """Return the authorized execution plan without running any agent."""
        return self._runner.router.plan(request)

    def list_agents(self) -> tuple[AgentDefinition, ...]:
        """Return all agents registered by the unified runtime."""
        return self._runner.registry.list()

    @property
    def available_resources(self) -> frozenset[str]:
        """Read-only resources actually configured on this runtime instance."""
        return self._available_resources


def _validated_quick_commands(
    raw: str,
    *,
    symbol: str,
    instrument_name: str,
) -> tuple[str, str, str]:
    try:
        commands = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("quick-command Agent returned invalid JSON") from error
    if (
        not isinstance(commands, list)
        or len(commands) != 3
        or any(not isinstance(item, str) or not item.strip() for item in commands)
    ):
        raise RuntimeError("quick-command Agent must return three non-empty strings")
    normalized = tuple(" ".join(item.split()).strip() for item in commands)
    if any(len(item) > 30 for item in normalized):
        raise RuntimeError("quick-command Agent exceeded the 30-character limit")
    if any(symbol not in item and instrument_name not in item for item in normalized):
        raise RuntimeError("quick-command Agent omitted the instrument identity")
    if any(
        forbidden in item
        for item in normalized
        for forbidden in _FORBIDDEN_QUICK_COMMAND_TEXT
    ):
        raise RuntimeError("quick-command Agent proposed a forbidden action")
    if any(
        generic == item for item in normalized for generic in _GENERIC_QUICK_COMMANDS
    ):
        raise RuntimeError("quick-command Agent returned a generic command")
    for index, command in enumerate(normalized):
        for other in normalized[index + 1 :]:
            if SequenceMatcher(None, command, other).ratio() >= 0.82:
                raise RuntimeError(
                    "quick-command Agent returned near-duplicate commands"
                )
    return normalized  # type: ignore[return-value]
