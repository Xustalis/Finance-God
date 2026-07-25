export type DeskSection = 'information' | 'portfolio' | 'watchlist' | 'trading'

export type SafeActionId =
  | 'navigate_information'
  | 'navigate_portfolio'
  | 'navigate_watchlist'
  | 'navigate_trading'
  | 'select_symbol'
  | 'fill_order_quantity'
  | 'refresh_market'

export interface SafeAction {
  id: SafeActionId
  object: 'workspace' | 'instrument' | 'order_draft' | 'market'
  mutation: 'ui_only' | 'draft_only'
}

export const SAFE_ACTIONS: readonly SafeAction[] = [
  { id: 'navigate_information', object: 'workspace', mutation: 'ui_only' },
  { id: 'navigate_portfolio', object: 'workspace', mutation: 'ui_only' },
  { id: 'navigate_watchlist', object: 'workspace', mutation: 'ui_only' },
  { id: 'navigate_trading', object: 'workspace', mutation: 'ui_only' },
  { id: 'select_symbol', object: 'instrument', mutation: 'ui_only' },
  { id: 'fill_order_quantity', object: 'order_draft', mutation: 'draft_only' },
  { id: 'refresh_market', object: 'market', mutation: 'ui_only' },
] as const

export type ResolvedCommand =
  | { kind: 'action'; actionId: SafeActionId; value?: string | number; message: string }
  | { kind: 'workflow'; workflowKey: string; title: string }
  | { kind: 'refused'; message: string }
  | { kind: 'unknown'; message: string }

export type CapabilityStatus = 'done' | 'partial' | 'missing'

export interface CapabilityGap {
  id: string
  area: string
  requirement: string
  current: string
  status: CapabilityStatus
  evidence: string
  phase: string
}

export interface PhasePlan {
  id: string
  title: string
  runnable: string
  deliverables: readonly string[]
  observables: readonly string[]
  gate: string
}

export type JourneyId = 'j1_first_visit' | 'j2_with_positions' | 'j3_agent_control' | 'j4_market_alert'

export interface JourneyScenario {
  id: JourneyId
  label: string
  section: DeskSection
  symbol: string
  hasPositions: boolean
  intro: string
  toastTitle: string
  toastMessage: string
}

const commands: Record<DeskSection, readonly [string, string, string]> = {
  information: [
    '分析当前标的行情',
    '核查当前行情数据新鲜度',
    '结合画像生成可研究候选',
  ],
  portfolio: [
    '分析当前仿真持仓风险',
    '运行组合集中度压力测试',
    '打开交易并准备未提交草稿',
  ],
  watchlist: [
    '分析自选标的近期异动',
    '比较当前自选标的',
    '结合画像生成可研究候选',
  ],
  trading: [
    '检查未提交订单草稿',
    '帮我制定交易方案',
    '切回持仓查看组合影响',
  ],
}

export function quickCommandsFor(section: DeskSection): readonly [string, string, string] {
  return commands[section]
}

export function resolveCommand(raw: string): ResolvedCommand {
  const text = raw.trim()
  if (!text) return { kind: 'unknown', message: '请输入要查看、分析或填写的内容。' }

  if (/(设置|密码|凭据|用户信息)/.test(text)) {
    return {
      kind: 'refused',
      message: '用户设置不在 Agent 能力范围内，请从顶部“我的”由本人操作。',
    }
  }
  if (/(直接下单|提交订单|确认下单|撤单|资金划转|自动买入|自动卖出)/.test(text)) {
    return {
      kind: 'refused',
      message: 'Agent 可填写未提交草稿，但不能提交、撤单或划转资金。',
    }
  }

  const quantity = text.match(/(?:数量|填成|填写)\D{0,8}(\d+(?:\.\d+)?)/)
  if (quantity?.[1]) {
    return {
      kind: 'action',
      actionId: 'fill_order_quantity',
      value: Number(quantity[1]),
      message: `已填写未提交草稿数量 ${quantity[1]}，尚未复核或提交。`,
    }
  }

  const symbol = text.toUpperCase().match(/\b(\d{6}(?:\.(?:SH|SZ))?)\b/)
  if (symbol?.[1]) {
    return {
      kind: 'action',
      actionId: 'select_symbol',
      value: symbol[1],
      message: `已选择 ${symbol[1]}，左右上下文已同步。`,
    }
  }

  if (/刷新.*行情|行情.*刷新/.test(text)) {
    return {
      kind: 'action',
      actionId: 'refresh_market',
      message: '正在请求服务端行情快照。',
    }
  }
  if (/持仓/.test(text) && /(打开|切回|查看)/.test(text)) {
    return {
      kind: 'action',
      actionId: 'navigate_portfolio',
      message: '已打开仿真持仓工作区。',
    }
  }
  if (/自选/.test(text) && /(打开|切换|查看)/.test(text)) {
    return {
      kind: 'action',
      actionId: 'navigate_watchlist',
      message: '已打开自选工作区。',
    }
  }
  if (/交易/.test(text) && /(打开|准备|切换)/.test(text)) {
    return {
      kind: 'action',
      actionId: 'navigate_trading',
      message: '已打开仿真交易工作区；不会自动提交。',
    }
  }
  if (/(总览|行情)/.test(text) && /(打开|切换|查看)/.test(text)) {
    return {
      kind: 'action',
      actionId: 'navigate_information',
      message: '已打开行情总览。',
    }
  }

  if (/(草稿|交易方案)/.test(text)) {
    return {
      kind: 'workflow',
      workflowKey: text.includes('草稿') ? 'order_review' : 'trade_plan_generation',
      title: text.includes('草稿') ? '订单草稿复核' : '交易计划生成',
    }
  }
  if (/(持仓|组合|集中度|压力)/.test(text)) {
    return { kind: 'workflow', workflowKey: 'portfolio_stress', title: '组合压力分析' }
  }
  if (/(行情|异动|数据新鲜度|比较)/.test(text)) {
    return { kind: 'workflow', workflowKey: 'market_context', title: '行情上下文分析' }
  }
  if (/(候选|公司研究|结合画像)/.test(text)) {
    return { kind: 'workflow', workflowKey: 'company_research', title: '可研究候选分析' }
  }

  return {
    kind: 'unknown',
    message: '当前原型只识别行情、持仓、自选、交易草稿和安全导航指令。',
  }
}

export function normalizeSymbol(value: string): string {
  const symbol = value.trim().toUpperCase()
  if (/^\d{6}\.(SH|SZ)$/.test(symbol)) return symbol
  if (/^\d{6}$/.test(symbol)) return `${symbol}.${/^[569]/.test(symbol) ? 'SH' : 'SZ'}`
  return symbol
}

/** Backend / product gap matrix against the Agent-controlled desk requirements. */
export const CAPABILITY_GAPS: readonly CapabilityGap[] = [
  {
    id: 'desk-bootstrap',
    area: '交易台启动',
    requirement: 'GET /api/desk/bootstrap 一次返回画像投影、工作区、3 条快捷指令、动作目录与 context_version',
    current: '已提供 bootstrap、脱敏画像投影、3 条快捷指令、动作目录、动态 capability 与 context_version；生产客户端仍需完成单次初始化接入',
    status: 'partial',
    evidence: 'backend/finance_god/api/desk_routes.py；backend/tests/api/test_desk_bootstrap.py',
    phase: 'P1',
  },
  {
    id: 'market-observation-history',
    area: '行情事实存储',
    requirement: '追加 market_observations + 可重建 market_latest + fetch_run 可观测',
    current: '仅 market_snapshots 最新值与 market_alerts 全局日志',
    status: 'partial',
    evidence: 'alembic 20260724_0014_market_monitor.py；MarketPoller',
    phase: 'P2',
  },
  {
    id: 'market-worker',
    area: '服务端行情采集',
    requirement: '独立 Market Worker、交易日历、分层间隔、租约防重复',
    current: 'API lifespan 内 MarketPoller 默认 30s；与 API 进程耦合',
    status: 'partial',
    evidence: 'backend/finance_god/application/market_poller.py；server.py lifespan',
    phase: 'P2',
  },
  {
    id: 'alert-user-delivery',
    area: '重大行情提醒',
    requirement: '规则版本 + 用户映射 + Toast/历史/关闭/已读/处理 + SSE',
    current: '全局 market_alerts 仍为拉取；用户 notifications 已有未读、历史和已读回执，但尚无行情事件映射、关闭/处理语义与 SSE',
    status: 'partial',
    evidence: 'market_data/monitor.py；workspace_routes notifications',
    phase: 'P3',
  },
  {
    id: 'workflow-worker',
    area: '工作流执行',
    requirement: '领取/租约/续租/节点执行/取消/恢复；queued→running→终态',
    current: '进程内与独立 Workflow Worker 已可用，使用 queued→running CAS 领取并持久化节点产物；租约续租、公开取消和多 Worker SKIP LOCKED 尚未上线',
    status: 'partial',
    evidence: 'application/workflow_worker.py；scripts/run_workflow_worker.py；tests/workflows/test_workflow_worker.py',
    phase: 'P4',
  },
  {
    id: 'workflow-events',
    area: '工作流事件流',
    requirement: 'GET events cursor + 终态折叠可展开节点时间线',
    current: 'progress 快照存在；无 events/cancel 公开接口',
    status: 'missing',
    evidence: 'docs/page-design/02_前后端职责与数据合同.md §5 未上线项',
    phase: 'P4',
  },
  {
    id: 'agent-conversation',
    area: 'Agent 会话',
    requirement: '持久 conversation/message；意图路由到唯一 WorkflowRun；快捷指令服务端返回',
    current: '交易台意图已由 /workflows/desk 服务端选择 WorkflowRun，bootstrap 返回 3 条快捷指令；仍无持久 conversation/message',
    status: 'partial',
    evidence: 'api/workflow_routes.py；api/desk_routes.py；生产 DeskAgentPanel',
    phase: 'P5',
  },
  {
    id: 'profile-projection',
    area: '画像投影',
    requirement: 'SuitabilityProfileProjection 脱敏版本化；设置不进 Agent',
    current: 'bootstrap 与研究工作流已使用 SuitabilityProfileProjection；仍需补用途同意、投影生命周期和客户端版本刷新',
    status: 'partial',
    evidence: 'agent_routes.py _profile_evidence_excerpt；server investor profile',
    phase: 'P1/P5',
  },
  {
    id: 'research-candidates',
    area: '可研究候选',
    requirement: '画像+行情版本生成候选，附理由/反方证据/未知项',
    current: '候选服务与 research_candidates 工作流已消费同源画像投影、当前仿真持仓和真实行情，并固化 Evidence；候选池范围仍有限',
    status: 'partial',
    evidence: 'application/candidate_service.py',
    phase: 'P5',
  },
  {
    id: 'ui-action-bridge',
    area: '左右联动',
    requirement: '服务端 UiActionDescriptor 白名单 + 回执 applied/rejected/stale_context + 审计',
    current: 'bootstrap 已发布安全动作目录，POST /desk/ui-actions 返回 applied/rejected/stale_context；当前回执只做服务端校验，尚未持久化动作审计，也未由生产客户端消费并应用',
    status: 'partial',
    evidence: 'backend/finance_god/api/desk_routes.py；backend/tests/api/test_desk_bootstrap.py',
    phase: 'P6',
  },
  {
    id: 'sse-outbox',
    area: '实时推送',
    requirement: 'Outbox Publisher + GET /api/events SSE cursor 恢复',
    current: 'workflow outbox 表存在；无发布器与用户 SSE',
    status: 'missing',
    evidence: 'workflow outbox 持久化；无 events stream 路由',
    phase: 'P3/P4',
  },
  {
    id: 'settings-exclusion',
    area: '用户设置隔离',
    requirement: '设置不在 capability/action 目录；仅本人读写',
    current: 'bootstrap capability 固定 settings_excluded=true，动作目录不含设置/提交/撤单/划转；仍需审计测试确保后续工具注册不会回归',
    status: 'done',
    evidence: 'backend/finance_god/api/desk_routes.py；backend/tests/api/test_desk_bootstrap.py',
    phase: 'P1/P6',
  },
  {
    id: 'simulation-ref-price',
    area: '仿真撮合引用价',
    requirement: '服务端绑定 PandaData 版本引用价，禁止浏览器 reference_price 作事实',
    current: '仿真链路较完整；MarketDataBarProvider 仍可能返回空',
    status: 'partial',
    evidence: 'execution/*；architecture 审计',
    phase: 'P7',
  },
] as const

export const PHASE_PLANS: readonly PhasePlan[] = [
  {
    id: 'P0',
    title: '基线与架构决策',
    runnable: '现有产品保持可运行；不改变交易事实',
    deliverables: ['ADR：API+Market Worker+Workflow Worker', '自治等级 L0–L3', '行情检测 SLA', '测试基线'],
    observables: ['/live /ready', '前后端测试报告', 'PandaData 成功率/延迟'],
    gate: '确认 Agent 永不提交/撤单；提醒四态分离；采集分层延迟',
  },
  {
    id: 'P1',
    title: '统一合同与 Desk Bootstrap',
    runnable: '客户端一次加载工作区；旧接口兼容',
    deliverables: ['统一 {success,data,error,meta}', 'GET /api/desk/bootstrap', 'SuitabilityProfileProjection', 'action descriptor v1'],
    observables: ['bootstrap p50/p95', '投影版本', '字段契约测试'],
    gate: '设置/凭据不出现在 bootstrap；金额字符串；context_version 可验证',
  },
  {
    id: 'P2',
    title: '行情采集纵向闭环',
    runnable: 'Market Worker 独立写 DB；API 只读事实',
    deliverables: ['observations/latest/schedule/fetch_run', '交易日历', '租约', '保留策略'],
    observables: ['每轮成功/失败/空结果', '延迟', '落后量', 'next_due'],
    gate: '重启不丢最新事实；双 Worker 不重复；失败标 stale 不伪造',
  },
  {
    id: 'P3',
    title: '重大行情与提醒闭环',
    runnable: '事件落库→用户通知→Toast/历史→SSE',
    deliverables: ['规则版本', '用户映射', 'delivery', '关闭/已读/处理', 'SSE cursor'],
    observables: ['检测延迟', 'dedupe 命中', '投递延迟', '未处理 P0/P1'],
    gate: '普通 Toast 自动隐藏 ≠ 已读；P0/P1 不自动消失；跨用户隔离',
  },
  {
    id: 'P4',
    title: '工作流 Worker 与产物',
    runnable: '创建的 Run 被领取并到达真实终态',
    deliverables: ['claim/lease', '节点执行', 'cancel', '恢复', 'artifact 查询', '事件投影'],
    observables: ['queue age', '节点耗时', '重试', '租约恢复', '终态分布'],
    gate: '进程终止可恢复；幂等只创建一个 Run；浏览器不模拟进度',
  },
  {
    id: 'P5',
    title: 'Agent 会话与任务路由',
    runnable: '右侧会话持久；研究意图统一 WorkflowRun',
    deliverables: ['conversation/message', '意图路由', '服务端 3 条快捷指令', '候选产物'],
    observables: ['workflow_key', '证据引用', '投影版本', '拒绝原因'],
    gate: '无第三套任务状态；画像缺失显式 degraded；证据失败阻断下游',
  },
  {
    id: 'P6',
    title: 'Agent 控制左侧',
    runnable: '导航/筛选/选标的/填未提交草稿',
    deliverables: ['动作目录', '参数 schema', '版本校验', '回执', 'ui_action_audit'],
    observables: ['applied/rejected/stale_context', '动作延迟', 'descriptor 版本'],
    gate: '无 DOM/坐标；设置与提交永不在目录；每动作有回执',
  },
  {
    id: 'P7',
    title: '完整交易台旅程',
    runnable: '总览/持仓/自选/交易 + Agent 端到端',
    deliverables: ['候选→研究→计划→草稿→复核→本人提交', '我的与提醒完整'],
    observables: ['漏斗', '版本冲突', '风险拒绝', 'user confirmation actor'],
    gate: '行情失败不假市值；账户标仿真；提交需用户手势+不可编辑摘要',
  },
  {
    id: 'P8',
    title: '生产加固与渐进发布',
    runnable: '灰度与回退',
    deliverables: ['SLO', 'Runbook', '审计导出', '灾备', '隐私安全测试'],
    observables: ['错误预算', '队列积压', 'SSE 连接', '跨租户防护'],
    gate: '故障演练、备份恢复、PandaData live smoke、1440/1024 验收',
  },
] as const

export const JOURNEY_SCENARIOS: readonly JourneyScenario[] = [
  {
    id: 'j1_first_visit',
    label: 'J1 首次进入',
    section: 'information',
    symbol: '000001.SZ',
    hasPositions: false,
    intro: '首次进入、没有仿真交易。快捷指令优先“可研究候选”，不是“立即买入”。服务端 bootstrap 已提供同类确定性指令，本隔离原型仍用本地映射展示交互。',
    toastTitle: '初始化说明',
    toastMessage: '左右工作区已就绪。重大行情与个性化候选依赖后续 P2–P5 后端闭环。',
  },
  {
    id: 'j2_with_positions',
    label: 'J2 已有持仓',
    section: 'portfolio',
    symbol: '600519.SH',
    hasPositions: true,
    intro: '返回用户、已有仿真持仓。快捷指令切换为持仓分析与压力测试。组合估值必须引用真实行情版本。',
    toastTitle: '持仓上下文已绑定',
    toastMessage: 'portfolio_version 与 market_version 变化会使旧动作返回 stale_context（生产合同）。',
  },
  {
    id: 'j3_agent_control',
    label: 'J3 自然语言控左',
    section: 'trading',
    symbol: '000001.SZ',
    hasPositions: false,
    intro: '试用“打开交易并把数量填成 200”。Agent 只能填未提交草稿；直接下单/撤单/打开设置会被拒绝。生产服务端已提供动作白名单与回执，客户端接入和持久审计仍待完成。',
    toastTitle: '动作白名单生效',
    toastMessage: '本原型本地执行 SAFE_ACTIONS；生产必须服务端 descriptor + 审计。',
  },
  {
    id: 'j4_market_alert',
    label: 'J4 重大行情提醒',
    section: 'information',
    symbol: '300750.SZ',
    hasPositions: false,
    intro: '重大行情应由确定性规则检测后推送。当前后端只有全局 market_alerts 拉取，用户级 SSE 与四态提醒未闭环。',
    toastTitle: '重大行情提醒 · 合同示例',
    toastMessage: '正式提醒必须引用 observation 与 rule_version。关闭浮层不等于已读或处理完成。',
  },
] as const

export function gapSummary(gaps: readonly CapabilityGap[] = CAPABILITY_GAPS): {
  done: number
  partial: number
  missing: number
} {
  return {
    done: gaps.filter((item) => item.status === 'done').length,
    partial: gaps.filter((item) => item.status === 'partial').length,
    missing: gaps.filter((item) => item.status === 'missing').length,
  }
}

export function phaseForGap(gapId: string): PhasePlan | undefined {
  const gap = CAPABILITY_GAPS.find((item) => item.id === gapId)
  if (!gap) return undefined
  const phaseId = gap.phase.split('/')[0]
  return PHASE_PLANS.find((item) => item.id === phaseId)
}
