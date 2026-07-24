# 用户画像 · 投资风格原型与大师匹配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在用户画像报告顶部新增"投资风格原型 + 大师匹配"英雄区，并把报告页整体重设为功能化文案。

**Architecture:** 后端 `profile_rules.match_style()` 依据已持久化的问卷字段（无迁移）派生 5 类风格之一及对应大师，经 `serialize_profile()` 单点返回；前端 `ProfileReportView.vue` 重设顶部英雄区、恢复功能化方向命名、删除煽情臆测。投资风格与既有风险区间正交并存。

**Tech Stack:** 后端 FastAPI + Pydantic + pytest；前端 Vue 3 + TypeScript + Vite + Vitest。

设计依据：`docs/superpowers/specs/2026-07-24-profile-style-master-match-design.md`

---

### Task 1: 后端风格匹配规则 `match_style()`

**Files:**
- Modify: `backend/app/services/profile_rules.py`
- Test: `backend/tests/unit/test_profile_rules.py`

- [ ] **Step 1: Write the failing tests**

在 `backend/tests/unit/test_profile_rules.py` 顶部 import 处追加：

```python
from app.services.profile_rules import match_style
```

在文件末尾追加：

```python
def _style_of(**overrides) -> str:
    objective = {
        "investment_experience": "intermediate",
        "fund_horizon": "5_plus_years",
        "loss_reaction": "hold",
        "emergency_fund_months": 8,
    } | overrides.pop("objective", {})
    return match_style(
        objective,
        overrides.get("risk_level", "moderate"),
        overrides.get("risk_capacity", 50),
        overrides.get("profile_evidence", {}),
        overrides.get("education_only", False),
    ).style_code


def test_match_style_maps_each_of_five_styles() -> None:
    assert _style_of(objective={"investment_experience": "none", "loss_reaction": "hold"}) == "market_growth"
    assert _style_of(objective={"loss_reaction": "buy_more"}) == "value_return"
    assert _style_of(
        risk_level="growth", risk_capacity=90,
        objective={"loss_reaction": "buy_more", "investment_experience": "advanced"},
        profile_evidence={"investment_goal": 1.0},
    ) == "growth_discovery"
    assert _style_of(
        objective={"loss_reaction": "reduce"},
        profile_evidence={"liquidity_need": 1.0},
    ) == "multi_asset"
    assert _style_of(
        risk_capacity=95,
        objective={"investment_experience": "advanced", "fund_horizon": "under_1_year", "loss_reaction": "sell_all"},
        profile_evidence={"investment_knowledge": 1.0},
    ) == "trend_discipline"


def test_match_style_minor_is_market_growth_learning_anchor() -> None:
    match = match_style(
        {"investment_experience": "advanced", "fund_horizon": "under_1_year", "loss_reaction": "sell_all"},
        "growth", 95, {"investment_knowledge": 1.0}, True,
    )
    assert match.style_code == "market_growth"
    assert match.master_name == "约翰·博格"
    assert "学习标杆" in match.match_reason


def test_match_style_reason_is_chinese_and_promises_nothing() -> None:
    match = match_style(
        {"investment_experience": "intermediate", "fund_horizon": "5_plus_years", "loss_reaction": "buy_more", "emergency_fund_months": 8},
        "moderate", 50, {}, False,
    )
    assert match.style_code == "value_return"
    assert re.search(r"[\u4e00-\u9fff]", match.match_reason)
    assert "巴菲特" in match.match_reason
    for banned in ("收益", "保证", "稳赚", "必赚"):
        assert banned not in match.match_reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_profile_rules.py -k match_style -v`
Expected: FAIL with `ImportError: cannot import name 'match_style'`

- [ ] **Step 3: Implement `match_style` in `profile_rules.py`**

在 `backend/app/services/profile_rules.py` 末尾追加（`objective_text`、`HORIZON_LABELS`、`LOSS_REACTION_LABELS` 已存在，直接复用）：

```python
STYLE_PROFILES = {
    "market_growth": {
        "style_logic": "市场增长型",
        "style_name": "长期市场参与者",
        "style_summary": "不猜谁会赢，长期持有整个市场，分享经济增长",
        "master_name": "约翰·博格",
        "master_name_en": "John Bogle",
    },
    "value_return": {
        "style_logic": "价值回归型",
        "style_name": "价值耐心寻找者",
        "style_summary": "寻找价格低于真实价值的好资产，耐心等待市场重新认识它",
        "master_name": "沃伦·巴菲特",
        "master_name_en": "Warren Buffett",
    },
    "growth_discovery": {
        "style_logic": "成长发现型",
        "style_name": "成长机会发现者",
        "style_summary": "寻找未来可能快速成长、但尚未被充分发现的企业",
        "master_name": "彼得·林奇",
        "master_name_en": "Peter Lynch",
    },
    "multi_asset": {
        "style_logic": "多资产配置型",
        "style_name": "多资产平衡者",
        "style_summary": "不把希望押在一种资产上，用不同资产应对不同环境",
        "master_name": "瑞·达利欧",
        "master_name_en": "Ray Dalio",
    },
    "trend_discipline": {
        "style_logic": "趋势交易型",
        "style_name": "趋势纪律执行者",
        "style_summary": "根据价格趋势和规则行动，并严格控制亏损",
        "master_name": "埃德·塞科塔",
        "master_name_en": "Ed Seykota",
    },
}

# 同分兜底：越靠前优先级越高（偏向更稳健/简单的类别）
STYLE_PRIORITY = ("market_growth", "value_return", "multi_asset", "growth_discovery", "trend_discipline")

STYLE_REASON_TEMPLATES = {
    "market_growth": "你的资金计划为{horizon}、亏损时倾向{loss}，这与博格主张的长期持有整个市场、少折腾的理念一致。",
    "value_return": "你的资金计划为{horizon}、亏损时倾向{loss}，这与巴菲特强调的价值判断与情绪纪律一致。",
    "growth_discovery": "你的资金计划为{horizon}、亏损时倾向{loss}，这与林奇寻找被低估成长机会的做法一致。",
    "multi_asset": "你的资金计划为{horizon}、亏损时倾向{loss}，这与达利欧用多资产分散应对不同环境的思路一致。",
    "trend_discipline": "你的资金计划为{horizon}、亏损时倾向{loss}，这与塞科塔顺势而为并严格止损的纪律一致。",
}
EDUCATION_STYLE_REASON = "作为学习标杆，博格倡导的低成本指数与长期定投，适合先建立稳健的投资常识。"


@dataclass(frozen=True)
class StyleMatch:
    style_code: str
    style_logic: str
    style_name: str
    style_summary: str
    master_name: str
    master_name_en: str
    match_reason: str


def _build_style_match(code: str, objective: dict, education_only: bool) -> StyleMatch:
    meta = STYLE_PROFILES[code]
    if education_only:
        reason = EDUCATION_STYLE_REASON
    else:
        horizon, _experience, loss_reaction, _reserve = objective_text(objective)
        reason = STYLE_REASON_TEMPLATES[code].format(horizon=horizon, loss=loss_reaction)
    return StyleMatch(style_code=code, match_reason=reason, **meta)


def match_style(
    objective: dict,
    risk_level: str,
    risk_capacity: float,
    profile_evidence: dict | None,
    education_only: bool,
) -> StyleMatch:
    if education_only:
        return _build_style_match("market_growth", objective, education_only=True)
    experience = objective.get("investment_experience")
    horizon = objective.get("fund_horizon")
    loss_reaction = objective.get("loss_reaction")
    reserve_months = max(0, int(objective.get("emergency_fund_months", 0) or 0))
    evidence = profile_evidence or {}
    knowledge = float(evidence.get("investment_knowledge", 0.0))
    goal = float(evidence.get("investment_goal", 0.0))
    liquidity = float(evidence.get("liquidity_need", 0.0))
    rc = float(risk_capacity or 0)
    scores = {
        "market_growth": (
            {"none": 30, "beginner": 22, "intermediate": 6, "advanced": 0}.get(experience, 0)
            + {"5_plus_years": 18, "3_5_years": 10, "1_3_years": 2, "under_1_year": -8}.get(horizon, 0)
            + {"hold": 16, "reduce": 6, "buy_more": 2, "sell_all": -6}.get(loss_reaction, 0)
            + (1 - knowledge) * 10
        ),
        "value_return": (
            {"intermediate": 22, "advanced": 16, "beginner": 6, "none": 0}.get(experience, 0)
            + {"5_plus_years": 18, "3_5_years": 12, "1_3_years": 2, "under_1_year": -10}.get(horizon, 0)
            + {"buy_more": 20, "hold": 12, "reduce": 2, "sell_all": -8}.get(loss_reaction, 0)
            + {"moderate": 6, "growth": 4, "conservative": 2}.get(risk_level, 0)
        ),
        "growth_discovery": (
            {"growth": 20, "moderate": 6, "conservative": -6}.get(risk_level, 0)
            + (rc / 100) * 15
            + {"buy_more": 18, "hold": 6}.get(loss_reaction, 0)
            + {"advanced": 14, "intermediate": 10, "beginner": 2}.get(experience, 0)
            + goal * 12
        ),
        "multi_asset": (
            {"reduce": 22, "hold": 6, "sell_all": 2}.get(loss_reaction, 0)
            + liquidity * 16
            + {"moderate": 12, "conservative": 6, "growth": 2}.get(risk_level, 0)
            + (6 if reserve_months >= 6 else 0)
        ),
        "trend_discipline": (
            {"advanced": 26, "intermediate": 8}.get(experience, 0)
            + (rc / 100) * 16
            + {"under_1_year": 18, "1_3_years": 10, "3_5_years": 0, "5_plus_years": -8}.get(horizon, 0)
            + {"sell_all": 14, "reduce": 12}.get(loss_reaction, 0)
            + knowledge * 10
        ),
    }
    best = max(STYLE_PRIORITY, key=lambda code: (scores[code], -STYLE_PRIORITY.index(code)))
    return _build_style_match(best, objective, education_only=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_profile_rules.py -v`
Expected: PASS（含既有用例，全部通过）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/profile_rules.py backend/tests/unit/test_profile_rules.py
git commit -m "feat(profile): add investment-style master matching rule"
```

---

### Task 2: 后端把风格匹配接入画像响应

**Files:**
- Modify: `backend/app/api/v1/onboarding.py`（`serialize_profile`，约 L788）
- Modify: `backend/app/schemas/onboarding.py`（`ProfileResponse`，约 L287-302）
- Test: `backend/tests/integration/test_onboarding_api.py`

- [ ] **Step 1: Write the failing test**

在 `backend/tests/integration/test_onboarding_api.py` 末尾追加（复用文件里已有的完成画像 fixture/流程；`completed` 为完成后返回的 JSON `data`，与 L275/L306 用法一致）：

```python
@pytest.mark.asyncio
async def test_completed_profile_exposes_style_master_match(client) -> None:
    completed = await _complete_profile(client)  # 复用本文件既有的完成画像辅助流程
    profile = completed["profile"]
    assert profile["style_code"] in {
        "market_growth", "value_return", "growth_discovery", "multi_asset", "trend_discipline",
    }
    assert profile["style_name"]
    assert profile["style_logic"]
    assert profile["style_summary"]
    assert profile["master_name"]
    assert profile["master_name_en"]
    assert profile["master_match_reason"]
```

> 注：若本文件没有可复用的 `_complete_profile` 辅助，请改为内联现有完成流程（参考 L260-306 的既有测试写法）拿到 `completed` 后再断言上述字段。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/integration/test_onboarding_api.py -k style_master -v`
Expected: FAIL with `KeyError: 'style_code'`

- [ ] **Step 3: Extend the schema**

在 `backend/app/schemas/onboarding.py` 的 `ProfileResponse` 类内，`report_summary` 字段之后追加：

```python
    style_code: str
    style_logic: str
    style_name: str
    style_summary: str
    master_name: str
    master_name_en: str
    master_match_reason: str
```

- [ ] **Step 4: Wire `match_style` into `serialize_profile`**

在 `backend/app/api/v1/onboarding.py` 顶部的 `profile_rules` import 处，把 `match_style` 加入导入名单（现有导入形如 `from app.services.profile_rules import assess_profile, rank_directions` 或模块导入；确保 `match_style` 可用）。

将 `serialize_profile` 的 `return {...}` 改为先计算再展开：

```python
def serialize_profile(profile: InvestmentProfile) -> dict:
    style = match_style(
        profile.objective_profile,
        profile.risk_level,
        (profile.dimension_scores or {}).get("risk_capacity", 0),
        profile.profile_evidence,
        profile.education_only,
    )
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "session_id": profile.session_id,
        "version": profile.version,
        "objective_profile": profile.objective_profile,
        "dimension_scores": profile.dimension_scores,
        "profile_evidence": profile.profile_evidence,
        "archetype_code": profile.archetype_code,
        "archetype_title": profile.archetype_title,
        "risk_level": profile.risk_level,
        "loss_tolerance_percent": profile.loss_tolerance_percent,
        "confidence": profile.confidence,
        "completeness": profile.completeness,
        "education_only": profile.education_only,
        "report_summary": profile.report_summary,
        "style_code": style.style_code,
        "style_logic": style.style_logic,
        "style_name": style.style_name,
        "style_summary": style.style_summary,
        "master_name": style.master_name,
        "master_name_en": style.master_name_en,
        "master_match_reason": style.match_reason,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/integration/test_onboarding_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/onboarding.py backend/app/schemas/onboarding.py backend/tests/integration/test_onboarding_api.py
git commit -m "feat(profile): expose style master match in profile response"
```

---

### Task 3: 前端类型与大师头像资源

**Files:**
- Modify: `frontend/src/types/api.ts`（`Profile` 接口，L33）
- Modify: `frontend/src/services/profile.ts`
- Create: `frontend/public/masters/README.txt`（占位，说明真实照片放置路径）

- [ ] **Step 1: 扩展 `Profile` 类型**

在 `frontend/src/types/api.ts` 的 `Profile` 接口末尾（`report_summary` 之后、闭合 `}` 之前）追加字段：

```typescript
; style_code:string; style_logic:string; style_name:string; style_summary:string; master_name:string; master_name_en:string; master_match_reason:string
```

- [ ] **Step 2: 新增大师头像映射到 `profile.ts`**

在 `frontend/src/services/profile.ts` 末尾追加（用 `public/` 下的 URL 字符串，缺图时 404 → 前端 `@error` 回退字标，不耦合构建）：

```typescript
export const masterPortraits:Record<string,string>={market_growth:'/masters/bogle.webp',value_return:'/masters/buffett.webp',growth_discovery:'/masters/lynch.webp',multi_asset:'/masters/dalio.webp',trend_discipline:'/masters/seykota.webp'}
export function masterInitial(name:string):string{return (name||'').replace(/[·・.\s]/g,'').slice(0,1)||'投'}
```

- [ ] **Step 3: 创建占位说明文件**

`frontend/public/masters/README.txt` 内容：

```text
放置理念原型大师照片（webp）：bogle.webp / buffett.webp / lynch.webp / dalio.webp / seykota.webp。
真实照片需在上线前确认肖像权/版权授权来源；文件缺失时前端自动回退到姓名字标，不影响运行。
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: 无新增类型错误

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/services/profile.ts frontend/public/masters/README.txt
git commit -m "feat(profile): add style master types and portrait mapping"
```

---

### Task 4: 报告页整体重设（英雄区 + 去隐喻）

**Files:**
- Modify: `frontend/src/views/ProfileReportView.vue`
- Modify: `frontend/src/styles.css`（`.report-intro` 附近，L227）
- Test: `frontend/src/tests/views.spec.ts`

- [ ] **Step 1: 更新测试 fixture 与用例**

在 `frontend/src/tests/views.spec.ts` 的 `fixtures.minorProfile.profile` 对象中，`report_summary:{...}` 之后追加字段（未成年 → market_growth）：

```typescript
,style_code:'market_growth',style_logic:'市场增长型',style_name:'长期市场参与者',style_summary:'不猜谁会赢，长期持有整个市场，分享经济增长',master_name:'约翰·博格',master_name_en:'John Bogle',master_match_reason:'作为学习标杆，博格倡导的低成本指数与长期定投，适合先建立稳健的投资常识。'
```

把既有 education-only 报告用例替换为同时校验英雄区且不含武侠词：

```typescript
  it('renders the style master hero and no wuxia metaphors',async()=>{const wrapper=mountWithPinia(ProfileReportView);await flushPromises();expect(wrapper.text()).toContain('长期市场参与者');expect(wrapper.text()).toContain('约翰·博格');expect(wrapper.text()).toContain('金融教育');expect(wrapper.find('[data-test="select-direction"]').exists()).toBe(false);expect(wrapper.find('details').exists()).toBe(true);for(const w of ['守元诀','百川谱','青松录','秘籍','卷轴']){expect(wrapper.text()).not.toContain(w)}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/tests/views.spec.ts -t "style master hero"`
Expected: FAIL（英雄区文案与去隐喻断言未满足）

- [ ] **Step 3: 重设 `ProfileReportView.vue`**

改动点（保持现有 `<script setup>` 其余逻辑不变）：

1) 顶部 import 追加 `masterPortraits, masterInitial`，并引入 `ref` 存图片失败态：

```typescript
import { directionScore, getSelectableDirections, localizeArchetype, localizeDimension, localizeProfileText, masterPortraits, masterInitial } from '@/services/profile'
```

2) 在 `const sent=new Set<string>()` 同行后追加：

```typescript
const portraitFailed=ref(false)
```

3) 删除 `directionNames`（守元诀等武侠映射）整行；保留 `directionKinds` 作为功能名，并把卡片里 `<h3>{{ directionNames[item.direction] }}</h3>` 改为 `<h3>{{ directionKinds[item.direction] }}</h3>`，同时删除卡片内那行 `<p class="chapter">{{ directionKinds[item.direction] }}</p>`（避免重复）。

4) 用功能化英雄区替换 `<section class="report-intro">…</section>` 整块：

```html
    <section class="master-hero"><div class="master-portrait"><img v-if="!portraitFailed" :src="masterPortraits[data.profile.style_code]" :alt="data.profile.master_name" @error="portraitFailed=true"><div v-else class="portrait-fallback" role="img" :aria-label="data.profile.master_name"><span>{{ masterInitial(data.profile.master_name) }}</span></div></div><div class="master-copy"><p class="chapter">投资风格 · {{ data.profile.style_logic }}</p><h1>{{ data.profile.style_name }}</h1><p class="report-lead">{{ data.profile.style_summary }}</p><p class="master-line">你的投资风格最接近 <strong>{{ data.profile.master_name }}</strong> · {{ data.profile.master_name_en }}</p><p class="match-reason">{{ data.profile.master_match_reason }}</p><p class="hero-note">投资风格标杆 · 理念相近，非收益承诺；账户与持仓为模拟数据。</p><div class="trait-row"><span v-for="trait in data.profile.report_summary.traits.slice(0,5)" :key="trait">{{ localizeProfileText(trait) }}</span></div></div></section>
```

5) 在 `metric-band` 起始处新增一格展示风险分类（archetype 下移为分类副标题）：把 `<section class="metric-band">` 后的第一个 `<div>` 之前插入：

```html
<div><small>风险分类</small><strong>{{ localizeArchetype(data.profile.archetype_title,data.profile.archetype_code) }}</strong><span>完整度 {{ Math.round(data.profile.completeness*100) }}%</span></div>
```

6) 把方向区块标题里的武侠措辞替换：将 `{{ data.profile.education_only?'启蒙篇':'与你相配的三本秘籍' }}` 改为 `{{ data.profile.education_only?'金融教育方向':'推荐配置方向' }}`；将 `{{ data.profile.education_only?'从稳健的金钱习惯开始':'方向比产品更重要' }}` 改为 `{{ data.profile.education_only?'从稳健的金钱习惯开始':'按匹配度排序，方向仅供参考' }}`；将"查看另外两类/只看前三"保持不变。

- [ ] **Step 4: 新增英雄区样式**

在 `frontend/src/styles.css` 的 `.report-intro { … }`（L227）之后追加：

```css
.master-hero { display: grid; grid-template-columns: auto 1fr; gap: 2rem; align-items: center; padding: clamp(2.5rem,6vw,5rem) clamp(1rem,8vw,8rem) 2.5rem; background: var(--ink); color: var(--paper-light); }
.master-portrait { width: 132px; height: 132px; border-radius: 4px; overflow: hidden; background: #2b2b2b; display: grid; place-items: center; }
.master-portrait img { width: 100%; height: 100%; object-fit: cover; }
.master-portrait .portrait-fallback span { font-size: 3rem; font-family: var(--font-numeric); color: var(--paper-light); }
.master-copy .chapter { color: #c4917a; }
.master-copy h1 { margin: .3rem 0 .8rem; }
.master-line { margin: .4rem 0; color: var(--paper-light); }
.match-reason { color: #b8a890; max-width: 760px; line-height: 1.7; }
.hero-note { margin-top: .6rem; font-size: .82rem; color: #8f8577; }
@media (max-width: 1024px) { .master-hero { grid-template-columns: 1fr; } }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/tests/views.spec.ts`
Expected: PASS（英雄区渲染、去隐喻、education-only 无选择按钮、既有方向选择用例均通过）

- [ ] **Step 6: 类型检查与构建**

Run: `cd frontend && npx vue-tsc --noEmit && npx vite build`
Expected: 通过，无类型错误

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/ProfileReportView.vue frontend/src/styles.css frontend/src/tests/views.spec.ts
git commit -m "feat(profile): redesign report with style master hero and functional copy"
```

---

## Self-Review 记录

- **Spec 覆盖**：5 类定义(Task 1 常量)、匹配算法(Task 1)、教育短路(Task 1)、后端派生接入(Task 2)、schema(Task 2)、前端类型/头像(Task 3)、英雄区+去隐喻+合规小字+方向功能名(Task 4)、测试(各 Task)。均有对应任务。
- **占位扫描**：无 TBD/TODO；Task 2 对 `_complete_profile` 辅助给出了内联回退指引。
- **类型一致性**：后端 `StyleMatch.match_reason` → 响应键 `master_match_reason` → 前端 `Profile.master_match_reason`，全链路一致；`style_code`/`style_logic`/`style_name`/`style_summary`/`master_name`/`master_name_en` 命名跨层一致。
- **假设**：`test_onboarding_api.py` 存在可复用的完成画像流程；`profile.objective_profile` 在持久化画像中为含 `investment_experience/fund_horizon/loss_reaction/emergency_fund_months` 的字典。
