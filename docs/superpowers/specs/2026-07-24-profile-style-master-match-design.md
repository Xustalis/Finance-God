# 用户画像 · 投资风格原型与大师匹配 设计

## 背景与问题

当前用户画像体验由两页组成：`frontend/src/views/OnboardingView.vue`（问答）与
`frontend/src/views/ProfileReportView.vue`（报告）。报告页存在两类问题：

1. **缺少正向反馈钩子**：报告只给出内部分类（稳健守望者 / 均衡领航者 / 长期成长
   建设者）与推荐方向，用户无法获得"我和某位投资大师想法一致"的认同感。
2. **文案违反产品约束**：`AGENTS.md` 要求"UI 文案必须描述功能，禁止口号与隐喻"。
   现报告用武侠隐喻包装金融信息（现金固收→"守元诀"、公募基金→"百川谱"、权益
   →"青松录"、另类→"观星篇"、长期险→"长宁策"，并称"秘籍/卷轴"），并含硬编码
   煽情臆测句"你重视边界，也愿意为长期目标留出耐心"。

## 目标

- 在报告页顶部新增**投资风格原型 + 大师匹配**英雄区，给用户正向认同反馈。
- 每个用户命中 **5 类风格之一**，展示 **1 位**对应理念原型大师（真实照片，失败回退字标）。
- 报告页整体重设：去武侠隐喻、恢复功能化命名、删除煽情臆测、合规信息前置。
- 所有匹配基于**真实问卷作答字段**加权计算，不编造，不承诺收益。

## 非目标

- 不改动引导页 `OnboardingView.vue`（虚构导师"沈砚先生"保持不动）。
- 不改动风险区间体系（`risk_level` / `loss_tolerance_percent` / 方向推荐排序仍按原
  风险逻辑）。投资风格是与风险区间**正交的新轴**。
- 不做数据库迁移；匹配结果为已有字段的纯函数，在生成响应时计算，不持久化。

## 一、投资风格原型（5 类）

作为报告顶部主身份，完全采用既定定义：

| style_code | 底层投资逻辑 | 用户名称 | 一句话 | 理念原型 |
|---|---|---|---|---|
| `market_growth` | 市场增长型 | 长期市场参与者 | 不猜谁会赢，长期持有整个市场，分享经济增长 | 约翰·博格 John Bogle |
| `value_return` | 价值回归型 | 价值耐心寻找者 | 寻找价格低于真实价值的好资产，耐心等待市场重新认识它 | 沃伦·巴菲特 Warren Buffett |
| `growth_discovery` | 成长发现型 | 成长机会发现者 | 寻找未来可能快速成长、但尚未被充分发现的企业 | 彼得·林奇 Peter Lynch |
| `multi_asset` | 多资产配置型 | 多资产平衡者 | 不把希望押在一种资产上，用不同资产应对不同环境 | 瑞·达利欧 Ray Dalio |
| `trend_discipline` | 趋势交易型 | 趋势纪律执行者 | 根据价格趋势和规则行动，并严格控制亏损 | 埃德·塞科塔 Ed Seykota |

## 二、匹配算法（后端 `profile_rules.match_style()`）

问卷未直接询问风格偏好，故用现有作答对 5 类各自加权打分，取**最高分**一类；同分
按固定优先级兜底。输入来自 `objective_profile`、`ProfileAssessment`（`risk_level`、
`dimension_scores["risk_capacity"]`）与 `profile_evidence`（0..1 浮点）。

**教育模式短路**：`education_only == True`（未成年）时，直接返回 `market_growth`，
且使用学习标杆措辞（见第四节合规文案），不参与下方打分。

各风格加分项（未列出的取 0）：

**market_growth（博格）**
- experience: none `+30`，beginner `+22`，intermediate `+6`，advanced `0`
- fund_horizon: 5_plus `+18`，3_5 `+10`，1_3 `+2`，under_1 `-8`
- loss_reaction: hold `+16`，reduce `+6`，buy_more `+2`，sell_all `-6`
- 认知偏低加成：`(1 - investment_knowledge_evidence) * 10`

**value_return（巴菲特）**
- experience: intermediate `+22`，advanced `+16`，beginner `+6`，none `0`
- fund_horizon: 5_plus `+18`，3_5 `+12`，1_3 `+2`，under_1 `-10`
- loss_reaction: buy_more `+20`，hold `+12`，reduce `+2`，sell_all `-8`
- risk_level: moderate `+6`，growth `+4`，conservative `+2`

**growth_discovery（林奇）**
- risk_level: growth `+20`，moderate `+6`，conservative `-6`
- `(risk_capacity / 100) * 15`
- loss_reaction: buy_more `+18`，hold `+6`
- experience: advanced `+14`，intermediate `+10`，beginner `+2`
- `investment_goal_evidence * 12`

**multi_asset（达利欧）**
- loss_reaction: reduce `+22`，hold `+6`，sell_all `+2`
- `liquidity_need_evidence * 16`
- risk_level: moderate `+12`，conservative `+6`，growth `+2`
- emergency_fund_months ≥ 6：`+6`

**trend_discipline（塞科塔）**
- experience: advanced `+26`，intermediate `+8`
- `(risk_capacity / 100) * 16`
- fund_horizon: under_1 `+18`，1_3 `+10`，3_5 `0`，5_plus `-8`
- loss_reaction: sell_all `+14`，reduce `+12`
- `investment_knowledge_evidence * 10`

**同分兜底优先级**（从高到低，取靠前者）：
`market_growth` > `value_return` > `multi_asset` > `growth_discovery` > `trend_discipline`
（默认偏向更稳健/简单的类别）。

**匹配说明句（`master_match_reason`）**：由命中风格与用户真实作答拼接，只陈述行为
一致性，不涉及收益。示例（value_return）：
`你偏好长期持有、亏损时倾向分批增加，这与巴菲特强调的价值判断与情绪纪律一致。`
每类提供一个模板，填入 `fund_horizon` / `loss_reaction` 的中文标签（复用
`HORIZON_LABELS` / `LOSS_REACTION_LABELS`）。

## 三、后端改动

`backend/app/services/profile_rules.py`
- 新增常量 `STYLE_PROFILES`（5 类的 `style_code`→{logic, name, summary, master_name,
  master_name_en}）与 `match_style(objective, assessment, profile_evidence,
  education_only) -> StyleMatch` 数据类（含上表字段 + `match_reason`）。

`backend/app/api/v1/onboarding.py`（约 L797 组装 profile 响应处）
- 调用 `match_style(...)`，在 profile 字典追加：`style_code`、`style_logic`、
  `style_name`、`style_summary`、`master_name`、`master_name_en`、`master_match_reason`。

`backend/app/schemas/onboarding.py`
- `ProfileRead`（或对应画像响应 schema）增加上述 7 个字符串字段。

不新增数据库列、不写 Alembic 迁移。

## 四、前端改动

`frontend/src/types/api.ts`
- `Profile` 接口增加：`style_code`、`style_logic`、`style_name`、`style_summary`、
  `master_name`、`master_name_en`、`master_match_reason`（均 string）。

`frontend/src/services/profile.ts`
- 新增 `masterPortraits: Record<string /*style_code*/, string>` 映射到静态资源；
  无需本地化风格文案（后端已返回中文）。

`frontend/src/views/ProfileReportView.vue`（整体重设）
- **顶部英雄区（新）**：大师真实照片（`<img @error>` 失败时回退大师姓氏字标，
  沿用 mentor 图的回退写法）+ `master_name` + "你的投资风格最接近 XXX" + `style_logic`
  标签 + `style_name` 作为身份标题 + `style_summary` + `master_match_reason` +
  合规小字"投资风格标杆·理念相近，非收益承诺；账户与持仓为模拟数据"。
- **风险区间下移**到 metric band：保留 `risk_level`（稳健/均衡/成长）、
  `loss_tolerance_percent`、资金期限、流动性、投资经验。archetype 作为分类副标题。
- **去武侠隐喻**：删除 `directionNames`（守元诀等）与"秘籍/卷轴"措辞；方向统一使用
  功能名——现金与固收 / 公募基金 / 权益(股票) / 另类配置 / 长期储蓄保险（复用现有
  `directionKinds`）。区块标题改为功能化，如"推荐配置方向（按匹配度排序）"。
- **删煽情臆测**：移除硬编码 `report-lead`「你重视边界，也愿意为长期目标留出耐心」；
  改用后端 `report_summary.reasoning`（基于作答）。
- **合规块前置**：判断依据 / 低置信度信息 / 风险提醒继续保留并靠前展示。
- 未成年教育模式：英雄区措辞改为"学习标杆"，不出现"投资风格标杆/收益"暗示。

`frontend/src/assets/images/masters/`（新增静态资源）
- `bogle.webp`、`buffett.webp`、`lynch.webp`、`dalio.webp`、`seykota.webp`。
- 真实照片的授权来源在上线前需人工确认（见"风险与假设"）；缺失时字标回退保证不崩。

## 五、合规与文案约束

- 全部匹配文案框定为"理念/风格相近"，**禁止**任何收益、业绩或"你会像大师一样赚钱"
  暗示；保留并前置既有 `risk_notice`。
- 账户/持仓/推荐仍是模拟数据，英雄区合规小字明确标注。
- 新增 UI 文案均为功能化描述，不得引入新的口号或隐喻。

## 六、测试计划

后端 `backend/tests/unit/test_profile_rules.py`
- 为 5 类各构造一组触发作答，断言 `match_style().style_code` 命中预期。
- 断言未成年 `education_only` 强制 `market_growth` 且措辞为学习标杆。
- 断言同分兜底按优先级返回。
- 断言 `master_match_reason` 含中文且不含"收益/保证"等词。

前端 `frontend/src/tests/views.spec.ts` / `core-behavior.spec.ts`
- 断言报告页渲染英雄区（`style_name`、`master_name`、一句话、匹配说明）。
- 断言照片 `@error` 回退到字标。
- 断言方向名称为功能名、不含"守元诀/秘籍/卷轴"等隐喻词。

## 七、风险与假设

- **假设**：后端画像响应在 `onboarding.py` 单点组装，追加字段不影响 workbench 交接
  既有字段（`saveAndEmitProfileCompleted` 的 payload 不变）。
- **风险（肖像/版权）**：巴菲特、达利欧等真人照片存在肖像权/版权风险；采用真实照片是
  产品既定选择，上线前须确认图片授权来源。字标回退确保资源缺失时不崩、可先上线。
- **假设**：5 类风格与现有 3 档风险区间正交并存，不改变方向推荐排序逻辑。
