"""回答引擎：把 A2A 文本请求接到 Finance-God 的 agent 编排。

三级引擎按优先级自动降级，保证 A2A 接口在任何环境下都能给出规范回答：

1. ``runtime``  —— 进程内直接调用后端 ``MultiAgentRuntime``（与 /desk Agent 面板
   同一编排入口，见 finance_god/orchestration/multi_agent.py）。需要后端依赖
   已安装且配置了 ARK_API_KEY / ARK_BASE_URL / ARK_MODEL。
2. ``deepseek`` —— 直连 DeepSeek OpenAI 兼容接口（deepseek-v4-pro），复用
   desk 直答的系统提示词约束。需要 DEEPSEEK_API_KEY。
3. ``demo``     —— 确定性教学演示引擎（零依赖离线兜底）。复用 desk_intent 的
   关键词路由语义，把问题映射到系统真实工作流并给出教学性回答，
   回答中明确标注为演示模式。

环境变量 ``A2A_ENGINE`` 可强制指定 runtime / deepseek / demo，默认 auto。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

_GATEWAY_ROOT = Path(__file__).resolve().parent
_BACKEND_ROOT = _GATEWAY_ROOT.parent / "backend"
_PROJECT_ENV_FILE = _GATEWAY_ROOT.parent / ".env"
_VENDOR_SRC = (
    _BACKEND_ROOT / "vendor" / "verifolio-unified-agents-0.2.0" / "agent_framework" / "src"
)


def _load_project_env() -> None:
    """轻量 .env 加载（不覆盖已有环境变量），与后端统一使用项目根 .env。"""
    if not _PROJECT_ENV_FILE.is_file():
        return
    for raw_line in _PROJECT_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_project_env()

_DEEPSEEK_ORIGIN = "https://api.deepseek.com"  # 项目规范：DeepSeek origin 固定
_DEEPSEEK_MODEL = "deepseek-v4-pro"  # 端点白名单：deepseek-v4-pro / deepseek-v4-flash

# 与 finance_god/orchestration/multi_agent.py stream_desk_answer 的约束一致：
# 直接、自然、简洁；不虚构未提供的数据；不执行任何真实交易动作。
_SYSTEM_PROMPT = (
    "你是 Finance-God 教学投资研究系统的对话 Agent，中文优先。"
    "直接、自然、简洁地回答用户的投资教学问题。"
    "不得声称已经取得未提供的实时行情、研究证据或执行结果；"
    "不得提交订单、撤单、划转资金或更改设置；"
    "所有涉及交易的内容必须明确为仿真教学演示；"
    "不承诺收益，不推荐具体基金或个股买卖点。"
    "只输出面向用户的回答正文，不要输出 JSON、标题前缀或路由说明。"
)


class EngineUnavailable(RuntimeError):
    """当前引擎在此环境下不可用，应降级到下一级。"""


# ---------------------------------------------------------------------------
# 1) runtime：进程内复用后端 MultiAgentRuntime（与 desk Agent 面板同源）
# ---------------------------------------------------------------------------

_runtime_cache = None


class _DeepSeekChat:
    """ChatClient 协议实现：DeepSeek Chat Completions（OpenAI 兼容）。

    vendor 的 OpenAICompatibleChat 使用 Responses API，DeepSeek 端点不支持（404）；
    本适配器改走 chat.completions，供 MultiAgentRuntime 注入使用。
    deepseek-v4-pro 是推理模型：最终回答在 content，推理过程在 reasoning_content（丢弃）。
    """

    def __init__(self, api_key: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(
            api_key=api_key,
            base_url=_DEEPSEEK_ORIGIN,
            timeout=180.0,
            max_retries=3,  # 推理模型长连接偶发断开，多给重试机会
        )
        self._model = _DEEPSEEK_MODEL

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise RuntimeError("Model returned an empty response")
        return content.strip()

    def stream_complete(self, *, system_prompt: str, user_prompt: str):
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
        )
        emitted = False
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                emitted = True
                yield delta
        if not emitted:
            raise RuntimeError("Model returned an empty streamed response")


def _load_multi_agent_runtime():
    global _runtime_cache
    if _runtime_cache is not None:
        return _runtime_cache
    for path in (str(_BACKEND_ROOT), str(_VENDOR_SRC)):
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        from finance_god.orchestration.crawler_data_provider import CrawlerDataProvider
        from finance_god.orchestration.multi_agent import MultiAgentRuntime
        from research_runtime import AgentRunner
    except Exception as error:  # noqa: BLE001 - 缺依赖即降级
        raise EngineUnavailable(f"backend runtime import failed: {type(error).__name__}") from error
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    try:
        if deepseek_key:
            # DeepSeek V4 Pro 注入式组装：与 from_environment 同构，仅替换 chat_client；
            # 评测链路只需文本对话，关闭行情与 FMP 依赖
            chat_client = _DeepSeekChat(deepseek_key)
            runner = AgentRunner(
                chat_client=chat_client,
                data_provider=CrawlerDataProvider(fallback=None),
                fmp_settings=None,
                max_concurrency=4,
            )
            _runtime_cache = MultiAgentRuntime(
                runner,
                chat_client=chat_client,
                available_resources=frozenset({"workspace"}),
            )
        else:
            # 标准 ARK 路径（OpenAI Responses 兼容端点）
            _runtime_cache = MultiAgentRuntime.from_environment(
                enable_panda_data=False,
                enable_finrobot_metrics=False,
            )
    except Exception as error:  # noqa: BLE001 - 缺凭据即降级
        raise EngineUnavailable(f"backend runtime unavailable: {type(error).__name__}") from error
    return _runtime_cache


def _runtime_stream(prompt: str) -> Iterator[str]:
    import asyncio

    runtime = _load_multi_agent_runtime()

    async def _collect() -> list[str]:
        chunks: list[str] = []
        async for chunk in runtime.stream_desk_answer(
            message=prompt,
            section="information",
            symbol="000001.SZ",
        ):
            chunks.append(chunk)
        return chunks

    yield from asyncio.run(_collect())


# ---------------------------------------------------------------------------
# 2) deepseek：直连 DeepSeek V4 Pro（OpenAI 兼容 /chat/completions）
# ---------------------------------------------------------------------------


def _deepseek_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise EngineUnavailable("DEEPSEEK_API_KEY is not configured")
    return key


def _deepseek_stream(prompt: str) -> Iterator[str]:
    request = urllib.request.Request(
        f"{_DEEPSEEK_ORIGIN}/chat/completions",
        data=json.dumps(
            {
                "model": _DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": True,
                "max_tokens": 1024,
            }
        ).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_deepseek_key()}",
        },
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except Exception as error:  # noqa: BLE001 - 网络/鉴权失败即降级
        raise EngineUnavailable(f"deepseek request failed: {type(error).__name__}") from error
    with response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content", "")
            except (json.JSONDecodeError, LookupError):
                continue
            if delta:
                yield delta


# ---------------------------------------------------------------------------
# 3) demo：确定性教学演示引擎（离线兜底）
# ---------------------------------------------------------------------------

# 与 finance_god/api/desk_intent.py 的路由语义保持一致的轻量关键词映射：
# 每个条目 = (关键词, 工作流标题, 参与的编排角色, 教学讲解正文)
_DEMO_ROUTES: tuple[tuple[tuple[str, ...], str, str, str], ...] = (
    (
        ("大盘", "市场", "行情", "环境", "指数"),
        "market_context（市场环境）",
        "market_analyst → sentiment_analyst → research_manager",
        "市场环境解读通常从三个层面展开：一是指数与成交结构，观察宽基指数趋势与量能配合；"
        "二是风格与行业轮动，判断资金在防守与进攻板块间的切换；三是情绪面，"
        "结合涨跌家数与波动率评估市场温度。教学上建议先看月线定方向、再看周线找节奏。",
    ),
    (
        ("研究", "基本面", "公司", "财报", "多空"),
        "company_research（公司研究）",
        "fundamentals_analyst → bull/bear_researcher → research_manager",
        "公司研究在系统内由多个分析师角色协作完成：基本面分析师审阅经营与财务披露，"
        "多头与空头研究员分别构建最强正反论点，研究经理汇总分歧并给出治理性结论。"
        "教学要点是：结论必须引用证据（E1 等证据编号），且不给出目标价或买卖指令。",
    ),
    (
        ("组合", "持仓", "回撤", "压力", "风险"),
        "portfolio_stress（组合压力）",
        "conservative_debator → portfolio_manager",
        "组合压力测试关注三类风险：回撤风险（极端行情下的最大损失）、集中度风险"
        "（单一标的或行业权重过高）、流动性风险（能否在合理价位退出）。"
        "教学示例：稳健型组合常以债券类 60%、宽基权益 30%、现金类 10% 作为讨论起点，"
        "再依据个人损失容忍度调整。",
    ),
    (
        ("交易", "下单", "买入", "卖出", "计划"),
        "trade_plan_generation（仿真交易计划）",
        "trader → order_review → simulation_execution",
        "仿真交易流程分四步：生成交易计划（明确标的、方向、仓位与理由）→ 预填订单草稿"
        "（side、数量、价格类型）→ 订单复核（校验是否符合画像与风控）→ 仿真执行与回执。"
        "全流程均为教学仿真，不涉及真实资金，也不会真正提交到券商。",
    ),
    (
        ("复盘", "总结", "回顾"),
        "post_trade_review（交易复盘）",
        "research_manager → portfolio_manager",
        "交易复盘的教学框架是三问：当初为什么买（决策依据是否仍成立）、执行有没有偏差"
        "（实际成交与计划的差异）、下次如何改进（规则化可复用的经验）。"
        "系统会把复盘结论沉淀为证据记录，供后续研究引用。",
    ),
    (
        ("画像", "稳健", "风险等级", "投资者", "配置"),
        "investment-qa（投资概念直答）",
        "desk 对话 Agent（直答路径）",
        "稳健型投资者的典型画像：能接受温和波动但重视回撤控制，投资期限中等偏长，"
        "对流动性有一定要求。教学上常见的讨论框架是“核心-卫星”配置：核心仓位求稳，"
        "卫星仓位小比例参与权益机会。具体比例应结合个人损失容忍度评估，本系统的"
        "投资画像问卷正是用于此评估。",
    ),
)

_DEMO_FALLBACK = (
    "investment-qa（投资概念直答）",
    "desk 对话 Agent（直答路径）",
    "这是一个投资教学问题。Finance-God 的研究方法强调三点：任何结论都要有可引用的证据、"
    "风险优先于收益（先确认损失容忍度再谈配置）、纪律优先于预测（用计划和复盘代替临场决定）。"
    "如果你能补充更具体的标的、组合或场景，我可以按对应的研究工作流展开讲解。",
)


def _demo_answer(prompt: str) -> str:
    text = prompt.strip()
    for keywords, workflow, roles, body in _DEMO_ROUTES:
        if any(keyword in text for keyword in keywords):
            selected = (workflow, roles, body)
            break
    else:
        selected = _DEMO_FALLBACK
    workflow, roles, body = selected
    return (
        f"【Finance-God 教学回答 · 演示模式】\n"
        f"问题：{text}\n"
        f"路由工作流：{workflow}\n"
        f"参与角色：{roles}\n\n"
        f"{body}\n\n"
        "以上内容仅用于投资者教育与仿真演示，不构成任何投资建议；"
        "本系统不执行真实交易，不推荐具体基金或个股买卖点。"
        "（当前为离线演示引擎；配置模型凭据后将由 DeepSeek V4 Pro 编排回答。）"
    )


def _demo_stream(prompt: str) -> Iterator[str]:
    answer = _demo_answer(prompt)
    # 按段落切块，产生真实的多事件流式序列
    for block in answer.split("\n\n"):
        if block.strip():
            yield block + "\n\n"


# ---------------------------------------------------------------------------
# 引擎调度
# ---------------------------------------------------------------------------

_ENGINES: dict[str, "callable"] = {
    "runtime": _runtime_stream,
    "deepseek": _deepseek_stream,
    "demo": _demo_stream,
}
_AUTO_ORDER = ("runtime", "deepseek", "demo")


def stream_answer(prompt: str) -> tuple[str, Iterator[str]]:
    """返回 (engine_name, chunk_iterator)。auto 模式逐级降级。"""
    forced = os.environ.get("A2A_ENGINE", "auto").strip().lower()
    if forced in _ENGINES:
        return forced, _ENGINES[forced](prompt)
    last_error: Exception | None = None
    for name in _AUTO_ORDER:
        try:
            iterator = _ENGINES[name](prompt)
            # runtime/deepseek 的失败发生在首个 chunk 之前，先预取以便降级
            first = next(iterator, None)
            if first is None:
                raise EngineUnavailable(f"{name} produced no output")

            def _with_first(head: str, rest: Iterator[str]) -> Iterator[str]:
                yield head
                yield from rest

            return name, _with_first(first, iterator)
        except EngineUnavailable as error:
            last_error = error
            continue
    raise RuntimeError(f"all answer engines failed: {last_error}")


def answer(prompt: str) -> tuple[str, str]:
    """返回 (engine_name, full_text)。"""
    engine, iterator = stream_answer(prompt)
    return engine, "".join(iterator).strip()


# ---------------------------------------------------------------------------
# 任务编排：研究型任务走真多智能体编排，概念型问题直答
# ---------------------------------------------------------------------------

# 研究型任务特征：需要多角色分析/证据链的诉求；与 desk_intent 的工作流词表同源语义
_RESEARCH_TERMS = (
    "研究", "分析", "基本面", "多空", "因子", "回测", "策略", "估值", "财报",
    "行业", "宏观", "压力测试", "风险评估", "归因", "对比", "比较", "研报", "评估",
)
# 概念直答前缀：与 desk_intent._CONCEPT_PREFIXES 同源语义，避免把名词解释送进多智能体流水线
_CONCEPT_PREFIXES = ("什么是", "什么叫", "解释", "介绍", "名词", "科普")

_RISK_NOTICE = (
    "风险提示：以上内容基于公开信息与模型推理，仅供投研教育与仿真演示，"
    "不构成任何投资建议；历史规律不代表未来表现，市场有风险，决策需独立判断。"
)


def wants_research(prompt: str) -> bool:
    text = prompt.strip()
    if text.startswith(_CONCEPT_PREFIXES):
        return False
    return any(term in text for term in _RESEARCH_TERMS)


def _guess_asset_kind(prompt: str):
    from research_runtime.contracts import AssetKind

    if any(term in prompt for term in ("组合", "持仓", "配置", "再平衡")):
        return AssetKind.PORTFOLIO
    if any(term in prompt for term in ("大盘", "市场", "指数", "宏观", "行业")):
        return AssetKind.MARKET
    if "基金" in prompt:
        return AssetKind.FUND
    return AssetKind.EQUITY


def _run_agents_with_timeout(runtime, request):
    import asyncio

    timeout_s = int(os.environ.get("A2A_TASK_TIMEOUT_S", "1000"))

    async def _run():
        return await asyncio.wait_for(runtime.run(request), timeout=timeout_s)

    return asyncio.run(_run())


def _synthesize(prompt: str, sections: list[str]) -> str | None:
    """用同一底座模型把各角色结论综合成最终观点（带分歧与风险）。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    try:
        chat = _DeepSeekChat(key)
        return chat.complete(
            system_prompt=(
                "你是 Finance-God 多智能体投研团队的研究经理。基于各分析师的结论，"
                "用简体中文输出综合结论：先给核心观点（不超过三点），再列关键分歧与"
                "不确定性，最后给风险提示。不给目标价、不给买卖指令、不承诺收益；"
                "只引用分析师已给出的事实与推断，不得补造数据。控制在 500 字以内。"
            ),
            user_prompt=(
                f"用户任务：{prompt}\n\n各分析师结论：\n" + "\n\n".join(sections)[:24_000]
            ),
        )
    except Exception:  # noqa: BLE001 - 综合失败不阻断主流程
        return None


def _format_result_section(result, titles: dict[str, str]) -> str:
    lines = [f"【{titles.get(result.agent_id, result.agent_id)}】"]
    lines.append(result.summary.strip())
    for claim in result.claims[:6]:
        kind = "事实" if claim.kind.value == "fact" else "推断"
        refs = f"（证据：{', '.join(claim.evidence_ids)}）" if claim.evidence_ids else ""
        lines.append(f"- [{kind}] {claim.statement}{refs}")
    return "\n".join(lines)


def _collect_briefing(prompt: str) -> str | None:
    """预研：用底座模型生成结构化背景简报作为分析师的研究素材。

    智能体是证据严格型：只喂 E1（任务本身）会导致全员结论为“无数据可分析”。
    简报明确标注来自模型知识库而非实时行情，不虚构具体报价与日内数据。
    """
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    try:
        chat = _DeepSeekChat(key)
        return chat.complete(
            system_prompt=(
                "你是投研团队的数据情报员。针对用户任务，输出一份结构化背景简报，"
                "供基本面/行情/情绪/新闻分析师作为研究素材。内容要求："
                "1) 行业/标的/主题的基本格局与产业链；2) 关键驱动因素与景气线索；"
                "3) 已知的主要风险点；4) 常用的分析框架与指标。"
                "只写你知识范围内的稳定事实与公认框架，不编造具体报价、实时数据或"
                "未经证实的事件；不确定的内容明确标注“需实时数据验证”。"
                "用紧凑的小标题+短句，控制在 800 字以内。"
            ),
            user_prompt=f"用户任务：{prompt}",
        )
    except Exception:  # noqa: BLE001 - 预研失败不阻断主流程，智能体仍可基于 E1 声明局限
        return None


def _research_events(prompt: str):
    """多智能体研究事件流：预研简报 → 计划 → 各角色结论 → 综合观点。"""
    runtime = _load_multi_agent_runtime()
    from research_runtime import AgentRequest
    from research_runtime.models import EvidenceRecord

    yield {"type": "status", "text": "数据情报员正在收集背景素材……"}
    evidence = [
        EvidenceRecord(
            identifier="E1",
            source="Finance-God A2A research request",
            excerpt=prompt[:4_000],
        )
    ]
    briefing = _collect_briefing(prompt)
    if briefing:
        evidence.append(
            EvidenceRecord(
                identifier="E2",
                source="Finance-God 背景简报（模型知识库，非实时行情）",
                excerpt=briefing[:4_000],
            )
        )
    request = AgentRequest(
        run_id=f"fg-a2a-{uuid4().hex[:24]}",
        subject=prompt[:500],
        task_type="research",
        asset_kind=_guess_asset_kind(prompt),
        evidence=evidence,
        max_agents=int(os.environ.get("A2A_MAX_AGENTS", "4")),
    )
    titles = {a.agent_id: a.title for a in runtime.list_agents()}
    plan = runtime.plan(request)
    roster = "；".join(
        f"{titles.get(item.agent_id, item.agent_id)}（{item.reason}）"
        for item in plan.assignments
    )
    yield {
        "type": "status",
        "text": f"研究计划已生成：Planner 选拨 {len(plan.assignments)} 个智能体 —— {roster}",
    }
    run = _run_agents_with_timeout(runtime, request)
    sections: list[str] = []
    yield {"type": "chunk", "text": f"# 多智能体研究报告\n任务：{prompt}\n\n"}
    if briefing:
        yield {
            "type": "chunk",
            "text": f"## 背景简报（模型知识库，非实时行情）\n{briefing}\n\n",
        }
    yield {"type": "chunk", "text": "## 各角色结论\n"}
    for result in run.results:
        section = _format_result_section(result, titles)
        sections.append(section)
        yield {"type": "chunk", "text": section + "\n\n"}
    yield {"type": "status", "text": "各角色分析完成，研究经理正在综合结论……"}
    synthesis = _synthesize(prompt, sections)
    if synthesis:
        yield {"type": "chunk", "text": f"## 综合结论（研究经理）\n{synthesis}\n\n"}
    yield {"type": "chunk", "text": f"---\n{_RISK_NOTICE}"}


def run_task(prompt: str):
    """统一任务入口：产出事件字典流 {type: status|chunk, text}。

    研究型任务优先走多智能体编排（A2A_RESEARCH=off 可关闭）；
    概念型问题、编排不可用或研究中途失败时，降级到直答引擎，
    确保任何情况下都以完整回答收尾（终态始终 completed）。
    """
    research_pref = os.environ.get("A2A_RESEARCH", "auto").strip().lower()
    if research_pref != "off" and wants_research(prompt):
        try:
            yield from _research_events(prompt)
            return
        except EngineUnavailable as error:
            yield {
                "type": "status",
                "text": "多智能体运行时不可用，已切换直答模式。",
            }
            print(f"[engine] research unavailable: {error}")
        except Exception as error:  # noqa: BLE001 - 研究中途失败不能拖崩整个任务
            yield {
                "type": "status",
                "text": "部分智能体调用失败，已切换为综合直答模式。",
            }
            print(f"[engine] research failed midway: {type(error).__name__}: {error}")
    _, iterator = stream_answer(prompt)
    for chunk in iterator:
        yield {"type": "chunk", "text": chunk}
