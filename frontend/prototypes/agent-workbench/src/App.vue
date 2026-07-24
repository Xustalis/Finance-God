<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import {
  AGENT_ACTIONS,
  quickCommandsFor,
  resolveAgentCommand,
  type AgentActionId,
  type InformationMode,
  type WorkflowKey,
  type WorkspaceSection,
} from './agentActions'

const MINIMUM_DESKTOP_WIDTH = 1024
const MARKET_POLL_INTERVAL_MS = 60_000
const AGENT_COLLAPSE_KEY = 'finance-god-agent-workbench-collapsed'

interface MarketQuote {
  symbol: string
  name: string
  last: number | string
  change: number | string | null
  change_percent: number | string | null
  open: number | string
  high: number | string
  low: number | string
  previous_close: number | string | null
  volume: number | string
  amount: number | string | null
  provider: string
  provider_time: string
  frequency: string
  freshness: string
  market_status: string
}

interface MarketBar {
  time: string
  open: number | string
  high: number | string
  low: number | string
  close: number | string
  volume: number | string
  provider_time: string
  freshness: string
}

interface MarketOverviewResponse {
  data: {
    quotes: MarketQuote[]
  }
}

interface BarsResponse {
  provider: string
  symbol: string
  frequency: string
  bars: MarketBar[]
}

type WorkflowStatus = 'running' | 'completed' | 'failed'
type StepStatus = 'pending' | 'running' | 'completed' | 'failed'

interface WorkflowStep {
  id: string
  label: string
  status: StepStatus
}

interface WorkflowRun {
  runId: string
  key: WorkflowKey
  code: string
  title: string
  status: WorkflowStatus
  startedAt: string
  endedAt: string | null
  steps: WorkflowStep[]
}

interface ConversationMessage {
  id: number
  role: 'user' | 'agent'
  text: string
  at: string
}

interface AlertRecord {
  id: number
  key: string
  severity: 'info' | 'warning' | 'error'
  title: string
  detail: string
  source: string
  createdAt: string
  read: boolean
}

const sectionItems: ReadonlyArray<{
  id: WorkspaceSection
  label: string
  hint: string
  action: AgentActionId
}> = [
  { id: 'information', label: '信息', hint: '行情、交易与策略', action: 'navigate_information' },
  { id: 'portfolio', label: '持仓', hint: '仿真仓位与风险', action: 'navigate_portfolio' },
  { id: 'watchlist', label: '自选', hint: '观察标的与上下文', action: 'navigate_watchlist' },
  { id: 'history', label: '交易记录', hint: '仿真订单与成交', action: 'navigate_history' },
  { id: 'wallet', label: '钱包', hint: '仿真现金与占用', action: 'navigate_wallet' },
]

const informationModes: ReadonlyArray<{
  id: InformationMode
  label: string
  action: AgentActionId
}> = [
  { id: 'market', label: '行情', action: 'show_market' },
  { id: 'trade', label: '交易', action: 'show_trade' },
  { id: 'strategy', label: '策略', action: 'show_strategy' },
]

const workflowDefinitions: Record<
  WorkflowKey,
  { code: string; steps: readonly string[] }
> = {
  market_context: {
    code: 'WF-MC-01',
    steps: ['校验 PandaData 版本', '装配市场上下文', '运行市场与情绪节点', '生成证据化结论'],
  },
  company_research: {
    code: 'WF-CR-01',
    steps: ['校验标的身份', '读取批准证据', '运行正反研究节点', '汇总结论与未知项'],
  },
  portfolio_stress: {
    code: 'WF-PS-01',
    steps: ['读取仿真组合版本', '校验行情新鲜度', '运行压力与集中度节点', '生成风险产物'],
  },
  trade_plan_generation: {
    code: 'WF-TP-01',
    steps: ['读取研究与授权版本', '生成计划候选', '确定性计算费用与偏离', '生成待审阅计划'],
  },
  order_review: {
    code: 'WF-OR-01',
    steps: ['冻结草稿输入版本', '计算费用与组合影响', '执行正式风控', '生成不可编辑复核摘要'],
  },
  strategy_validation: {
    code: 'WF-SV-01',
    steps: ['校验策略需求', '运行受限策略节点', '执行确定性测试', '生成验证档案'],
  },
  event_impact: {
    code: 'WF-EI-01',
    steps: ['确认阈值事件事实', '关联持仓与自选', '运行事件影响节点', '生成提醒与影响说明'],
  },
}

const currentWidth = ref(
  typeof window === 'undefined' ? MINIMUM_DESKTOP_WIDTH : window.innerWidth,
)
const storedAgentCollapsed = typeof window === 'undefined'
  ? null
  : window.localStorage.getItem(AGENT_COLLAPSE_KEY)
const agentCollapsed = ref(
  storedAgentCollapsed === null
    ? typeof window !== 'undefined' && window.innerWidth < 1280
    : storedAgentCollapsed === 'true',
)
let hasExplicitAgentPreference = storedAgentCollapsed !== null
const currentSection = ref<WorkspaceSection>('information')
const informationMode = ref<InformationMode>('market')
const selectedSymbol = ref('000001.SZ')
const symbols = ref(['000001.SZ', '600519.SH', '300750.SZ'])
const quotes = ref<MarketQuote[]>([])
const bars = ref<MarketBar[]>([])
const barsFrequency = ref<string | null>(null)
const marketLoading = ref(false)
const marketError = ref<string | null>(null)
const barsLoading = ref(false)
const barsError = ref<string | null>(null)
const lastRequestAt = ref<string | null>(null)
const activeAgentAction = ref<AgentActionId | null>(null)

const orderSide = ref<'buy' | 'sell'>('buy')
const orderQuantity = ref<number | null>(null)
const orderLimitPrice = ref<number | null>(null)

const composer = ref('')
const messages = ref<ConversationMessage[]>([
  {
    id: 1,
    role: 'agent',
    text: '已读取当前页面上下文。你可以让我切换工作区、分析当前对象或填写未提交草稿；用户设置与订单提交仍由你本人操作。',
    at: new Date().toISOString(),
  },
])
let messageSequence = 1

const activeWorkflow = ref<WorkflowRun | null>(null)
const workflowExpanded = ref(false)
let workflowTimer: ReturnType<typeof setInterval> | null = null

const remindersOpen = ref(false)
const settingsOpen = ref(false)
const alerts = ref<AlertRecord[]>([])
const activeToast = ref<AlertRecord | null>(null)
const alertKeys = new Set<string>()
let alertSequence = 0
let toastTimer: ReturnType<typeof setTimeout> | null = null

let overviewInFlight = false
let overviewAbort: AbortController | null = null
let barsAbort: AbortController | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
let highlightTimer: ReturnType<typeof setTimeout> | null = null

const selectedQuote = computed(
  () => quotes.value.find((quote) => quote.symbol === selectedSymbol.value) ?? null,
)

const unreadAlertCount = computed(
  () => alerts.value.filter((alert) => !alert.read).length,
)

const quickCommands = computed(
  () => quickCommandsFor(currentSection.value, informationMode.value),
)

const pageTitle = computed(() => {
  const section = sectionItems.find((item) => item.id === currentSection.value)
  return section?.label ?? '信息'
})

const contextLabel = computed(() => {
  if (currentSection.value === 'information') {
    const mode = informationModes.find((item) => item.id === informationMode.value)
    return `${pageTitle.value} / ${mode?.label ?? '行情'} · ${selectedSymbol.value}`
  }
  return `${pageTitle.value} · ${selectedSymbol.value}`
})

const chartPoints = computed(() => {
  if (bars.value.length < 2) return ''
  const width = 760
  const height = 246
  const insetX = 16
  const insetY = 18
  const closes = bars.value.map((bar) => Number(bar.close))
  if (closes.some((value) => !Number.isFinite(value))) return ''
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const spread = max - min || 1
  return closes
    .map((close, index) => {
      const x = insetX + (index / (closes.length - 1)) * (width - insetX * 2)
      const y = insetY + ((max - close) / spread) * (height - insetY * 2)
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
})

const chartSummary = computed(() => {
  if (!bars.value.length) return '当前没有可用 K 线数据。'
  const first = bars.value[0]
  const last = bars.value[bars.value.length - 1]
  return `${selectedSymbol.value}，${barsFrequency.value ?? '频率未知'}，共 ${bars.value.length} 条；区间首个收盘 ${formatNumber(first?.close)}，末个收盘 ${formatNumber(last?.close)}。`
})

const providerTimeLabel = computed(
  () => formatDateTime(selectedQuote.value?.provider_time ?? null),
)

const changeDirection = computed(() => {
  const value = Number(selectedQuote.value?.change_percent)
  if (!Number.isFinite(value) || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
})

const simulatedPositions = [
  { symbol: '600519.SH', quantity: '100', available: '100', cost: '仿真账本字段', valuation: '等待后端估值' },
  { symbol: '000001.SZ', quantity: '1,200', available: '1,200', cost: '仿真账本字段', valuation: '等待后端估值' },
]

const simulatedHistory = [
  { id: 'SIM-ORDER-018', symbol: '000001.SZ', side: '买入', status: '已成交（结构示例）', time: '仿真时点' },
  { id: 'SIM-ORDER-017', symbol: '600519.SH', side: '卖出', status: '已撤销（结构示例）', time: '仿真时点' },
]

function formatNumber(value: number | string | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '—'
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(numeric)
}

function formatPercent(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '—'
  const sign = numeric > 0 ? '+' : ''
  return `${sign}${numeric.toFixed(2)}%`
}

function formatDateTime(value: string | null): string {
  if (!value) return '等待上游时点'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const formatted = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
  return `${formatted} CST`
}

function normalizeSymbol(value: string): string {
  const symbol = value.trim().toUpperCase()
  if (/\.(SH|SZ)$/.test(symbol)) return symbol
  if (/^\d{6}$/.test(symbol)) {
    return `${symbol}.${/^[569]/.test(symbol) ? 'SH' : 'SZ'}`
  }
  return symbol
}

async function apiError(response: Response): Promise<string> {
  const body = await response.json().catch(() => null) as {
    error?: { code?: string; message?: string }
  } | null
  const code = body?.error?.code ? `（${body.error.code}）` : ''
  return body?.error?.message
    ? `${body.error.message}${code}`
    : `请求失败：HTTP ${response.status}${code}`
}

async function loadMarketOverview(): Promise<void> {
  if (overviewInFlight) return
  overviewInFlight = true
  overviewAbort = new AbortController()
  marketLoading.value = true
  marketError.value = null
  try {
    const query = encodeURIComponent(symbols.value.join(','))
    const response = await fetch(`/api/market/overview?symbols=${query}`, {
      signal: overviewAbort.signal,
      headers: { Accept: 'application/json' },
    })
    if (!response.ok) throw new Error(await apiError(response))
    const payload = await response.json() as MarketOverviewResponse
    if (!Array.isArray(payload.data?.quotes) || payload.data.quotes.length === 0) {
      throw new Error('PandaData 返回空行情；未使用演示价格替代。')
    }
    quotes.value = payload.data.quotes
    lastRequestAt.value = new Date().toISOString()
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    marketError.value = error instanceof Error ? error.message : String(error)
    pushAlert({
      key: `market-error:${marketError.value}`,
      severity: 'error',
      title: '行情请求失败',
      detail: `${marketError.value} 最后成功行情不会被伪装为当前数据。`,
      source: 'PandaData 接入',
    })
  } finally {
    overviewInFlight = false
    overviewAbort = null
    marketLoading.value = false
  }
}

async function loadBars(): Promise<void> {
  if (barsAbort) barsAbort.abort()
  const controller = new AbortController()
  barsAbort = controller
  barsLoading.value = true
  barsError.value = null
  try {
    const response = await fetch(
      `/api/market/bars?symbol=${encodeURIComponent(selectedSymbol.value)}&limit=48`,
      {
        signal: controller.signal,
        headers: { Accept: 'application/json' },
      },
    )
    if (!response.ok) throw new Error(await apiError(response))
    const payload = await response.json() as BarsResponse
    if (!Array.isArray(payload.bars) || payload.bars.length === 0) {
      throw new Error('PandaData 返回空 K 线；未使用演示图形替代。')
    }
    if (barsAbort !== controller) return
    bars.value = payload.bars
    barsFrequency.value = payload.frequency
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    if (barsAbort !== controller) return
    bars.value = []
    barsFrequency.value = null
    barsError.value = error instanceof Error ? error.message : String(error)
  } finally {
    if (barsAbort === controller) {
      barsAbort = null
      barsLoading.value = false
    }
  }
}

function refreshAll(): void {
  void loadMarketOverview()
  void loadBars()
}

function startPolling(): void {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(() => {
    void loadMarketOverview()
  }, MARKET_POLL_INTERVAL_MS)
}

function stopPolling(): void {
  if (!pollTimer) return
  clearInterval(pollTimer)
  pollTimer = null
}

function onVisibilityChange(): void {
  if (document.hidden) {
    stopPolling()
    return
  }
  refreshAll()
  startPolling()
}

function pushAlert(input: Omit<AlertRecord, 'id' | 'createdAt' | 'read'>): void {
  if (alertKeys.has(input.key)) return
  alertKeys.add(input.key)
  const record: AlertRecord = {
    ...input,
    id: ++alertSequence,
    createdAt: new Date().toISOString(),
    read: false,
  }
  alerts.value = [record, ...alerts.value]
  activeToast.value = record
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    activeToast.value = null
  }, 8_000)
}

function dismissToast(): void {
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = null
  activeToast.value = null
}

function markAllAlertsRead(): void {
  alerts.value = alerts.value.map((alert) => ({ ...alert, read: true }))
}

function addMessage(role: ConversationMessage['role'], text: string): void {
  messages.value.push({
    id: ++messageSequence,
    role,
    text,
    at: new Date().toISOString(),
  })
  void nextTick(() => {
    const transcript = document.querySelector<HTMLElement>('[data-agent-transcript]')
    transcript?.scrollTo({ top: transcript.scrollHeight, behavior: 'smooth' })
  })
}

function flashAction(actionId: AgentActionId): void {
  activeAgentAction.value = actionId
  if (highlightTimer) clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => {
    activeAgentAction.value = null
  }, 520)
}

function performAction(actionId: AgentActionId, value?: string | number): void {
  flashAction(actionId)
  switch (actionId) {
    case 'navigate_information':
      currentSection.value = 'information'
      return
    case 'navigate_portfolio':
      currentSection.value = 'portfolio'
      return
    case 'navigate_watchlist':
      currentSection.value = 'watchlist'
      return
    case 'navigate_history':
      currentSection.value = 'history'
      return
    case 'navigate_wallet':
      currentSection.value = 'wallet'
      return
    case 'show_market':
      currentSection.value = 'information'
      informationMode.value = 'market'
      return
    case 'refresh_market':
      refreshAll()
      return
    case 'show_trade':
      currentSection.value = 'information'
      informationMode.value = 'trade'
      return
    case 'show_strategy':
      currentSection.value = 'information'
      informationMode.value = 'strategy'
      return
    case 'select_symbol': {
      const normalized = normalizeSymbol(String(value ?? ''))
      if (!symbols.value.includes(normalized)) {
        symbols.value = [normalized, ...symbols.value]
      }
      selectedSymbol.value = normalized
      currentSection.value = 'information'
      return
    }
    case 'fill_order_quantity':
      currentSection.value = 'information'
      informationMode.value = 'trade'
      orderQuantity.value = Number(value)
      return
    case 'fill_limit_price':
      currentSection.value = 'information'
      informationMode.value = 'trade'
      orderLimitPrice.value = Number(value)
      return
    case 'set_order_side_buy':
      currentSection.value = 'information'
      informationMode.value = 'trade'
      orderSide.value = 'buy'
      return
    case 'set_order_side_sell':
      currentSection.value = 'information'
      informationMode.value = 'trade'
      orderSide.value = 'sell'
      return
  }
}

function startWorkflow(key: WorkflowKey, title: string): void {
  if (activeWorkflow.value?.status === 'running') {
    addMessage('agent', '当前已有工作流运行中。完成或失败后才能启动下一条工作流。')
    return
  }
  const definition = workflowDefinitions[key]
  const runId = `${definition.code}-${Date.now().toString(36).toUpperCase()}`
  activeWorkflow.value = {
    runId,
    key,
    code: definition.code,
    title,
    status: 'running',
    startedAt: new Date().toISOString(),
    endedAt: null,
    steps: definition.steps.map((label, index) => ({
      id: `${runId}:${index}`,
      label,
      status: index === 0 ? 'running' : 'pending',
    })),
  }
  workflowExpanded.value = true
  addMessage('agent', `已启动 ${definition.code}「${title}」。运行状态会保留在当前对话中。`)

  let currentStep = 0
  if (workflowTimer) clearInterval(workflowTimer)
  workflowTimer = setInterval(() => {
    const run = activeWorkflow.value
    if (!run || run.runId !== runId) return
    run.steps[currentStep]!.status = 'completed'
    currentStep += 1
    if (currentStep < run.steps.length) {
      run.steps[currentStep]!.status = 'running'
      return
    }
    run.status = 'completed'
    run.endedAt = new Date().toISOString()
    workflowExpanded.value = false
    if (workflowTimer) clearInterval(workflowTimer)
    workflowTimer = null
    addMessage(
      'agent',
      `${definition.code} 原型运行已完成。这里仅展示编排状态；真实结论必须由后端版本化产物、证据和质量门返回。`,
    )
  }, 760)
}

function submitPrompt(preset?: string): void {
  const text = (preset ?? composer.value).trim()
  if (!text) return
  composer.value = ''
  addMessage('user', text)
  const resolved = resolveAgentCommand(text)
  if (resolved.kind === 'ui_action') {
    performAction(resolved.actionId, resolved.value)
    addMessage('agent', resolved.response)
    return
  }
  if (resolved.kind === 'workflow') {
    startWorkflow(resolved.workflowKey, resolved.title)
    return
  }
  addMessage('agent', resolved.response)
}

function runCurrentAnalysis(): void {
  if (currentSection.value === 'portfolio') {
    startWorkflow('portfolio_stress', '持仓与组合压力分析')
    return
  }
  if (informationMode.value === 'trade') {
    startWorkflow('order_review', '仿真订单草稿复核')
    return
  }
  if (informationMode.value === 'strategy') {
    startWorkflow('strategy_validation', '策略条件验证')
    return
  }
  startWorkflow('market_context', '当前行情与市场环境分析')
}

function onWorkflowToggle(event: Event): void {
  workflowExpanded.value = (event.currentTarget as HTMLDetailsElement).open
}

function toggleAgentPanel(): void {
  hasExplicitAgentPreference = true
  agentCollapsed.value = !agentCollapsed.value
  window.localStorage.setItem(
    AGENT_COLLAPSE_KEY,
    agentCollapsed.value ? 'true' : 'false',
  )
}

function resizeHandler(): void {
  currentWidth.value = window.innerWidth
  if (!hasExplicitAgentPreference) {
    agentCollapsed.value = currentWidth.value < 1280
  }
}

watch(selectedSymbol, () => {
  void loadBars()
})

onMounted(() => {
  resizeHandler()
  window.addEventListener('resize', resizeHandler)
  document.addEventListener('visibilitychange', onVisibilityChange)
  refreshAll()
  startPolling()
  pushAlert({
    key: 'prototype-boundary',
    severity: 'info',
    title: '原型提醒能力已初始化',
    detail: '提醒记录当前保存在原型内存中；生产版本需由后端事件消费者与通知表接管。',
    source: 'Agent 交易台原型',
  })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeHandler)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  stopPolling()
  overviewAbort?.abort()
  barsAbort?.abort()
  if (workflowTimer) clearInterval(workflowTimer)
  if (highlightTimer) clearTimeout(highlightTimer)
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<template>
  <div class="prototype-root">
    <section v-if="currentWidth < MINIMUM_DESKTOP_WIDTH" class="desktop-notice">
      <p class="eyebrow">DESKTOP WORKBENCH</p>
      <h1>请使用更宽的桌面窗口</h1>
      <p>
        当前宽度 {{ currentWidth }} px；交易台最低支持 {{ MINIMUM_DESKTOP_WIDTH }} px。
        本产品不生成移动交易布局。
      </p>
    </section>

    <template v-else>
      <header class="masthead">
        <div class="brand-block">
          <span class="brand">FINANCE GOD</span>
          <span class="prototype-mark">AGENT WORKBENCH · ISOLATED PROTOTYPE</span>
        </div>

        <nav class="product-nav" aria-label="产品导航">
          <button type="button">总览</button>
          <button type="button">行情</button>
          <button type="button" class="current" aria-current="page">交易台</button>
          <button type="button">组合</button>
          <button type="button">订单</button>
          <button type="button">复盘</button>
          <button type="button">数据</button>
        </nav>

        <div class="global-status">
          <span class="status-fact"><b>仿真</b> 账户</span>
          <span class="status-fact">
            <i :class="marketError ? 'error-dot' : 'status-dot'" />
            PandaData
          </span>
          <span class="status-fact">请求间隔 60 秒</span>
          <button
            type="button"
            class="plain-action reminder-button"
            :aria-expanded="remindersOpen"
            @click="remindersOpen = !remindersOpen; settingsOpen = false"
          >
            提醒
            <span v-if="unreadAlertCount" class="alert-count">{{ unreadAlertCount }}</span>
          </button>
          <button
            type="button"
            class="plain-action settings-button"
            data-agent-excluded="true"
            aria-label="用户设置（不对 Agent 开放）"
            :aria-expanded="settingsOpen"
            @click="settingsOpen = !settingsOpen; remindersOpen = false"
          >
            用户设置
          </button>
        </div>

        <section
          v-if="remindersOpen"
          class="header-panel reminder-history"
          aria-label="提醒记录"
        >
          <div class="panel-heading">
            <div>
              <span class="eyebrow">NOTIFICATION HISTORY</span>
              <h2>提醒记录</h2>
            </div>
            <button type="button" class="text-action" @click="markAllAlertsRead">
              全部标为已读
            </button>
          </div>
          <p class="panel-note">
            当前为原型 UI 事件记录；生产版本由服务端通知表留存并关联唯一业务对象。
          </p>
          <p v-if="alerts.length === 0" class="empty-state">暂无提醒。</p>
          <ol v-else class="alert-list">
            <li
              v-for="alert in alerts"
              :key="alert.id"
              :class="[`severity-${alert.severity}`, { unread: !alert.read }]"
            >
              <span class="alert-time">{{ formatDateTime(alert.createdAt) }}</span>
              <strong>{{ alert.title }}</strong>
              <p>{{ alert.detail }}</p>
              <small>{{ alert.source }}</small>
            </li>
          </ol>
        </section>

        <section
          v-if="settingsOpen"
          class="header-panel settings-boundary"
          aria-label="用户设置边界"
        >
          <span class="eyebrow">USER-OWNED CONTROL</span>
          <h2>用户设置</h2>
          <p>
            画像、通知偏好、Agent 暂停、仿真账户与工作区设置由用户本人操作，
            不暴露到 Agent 动作目录。
          </p>
          <button type="button" class="ink-button" data-agent-excluded="true">
            进入用户设置
          </button>
        </section>
      </header>

      <div class="workbench" :class="{ 'agent-collapsed': agentCollapsed }">
        <section class="left-workbench" aria-label="交易台信息工作区">
          <aside class="workspace-nav" aria-label="工作区导航">
            <div class="nav-caption">
              <span class="eyebrow">WORKSPACE</span>
              <strong>交易台</strong>
            </div>
            <button
              v-for="item in sectionItems"
              :key="item.id"
              type="button"
              class="section-link"
              :class="{
                active: currentSection === item.id,
                'agent-focus': activeAgentAction === item.action,
              }"
              :aria-current="currentSection === item.id ? 'page' : undefined"
              :data-agent-action="item.action"
              data-agent-object="workspace"
              :data-agent-description="item.hint"
              @click="performAction(item.action)"
            >
              <span>{{ item.label }}</span>
              <small>{{ item.hint }}</small>
            </button>
            <div class="nav-boundary">
              <span>Agent 可寻址</span>
              <strong>{{ AGENT_ACTIONS.length }} 项安全动作</strong>
              <small>设置、复核确认、提交与撤单已排除</small>
            </div>
          </aside>

          <main class="workspace-main">
            <header class="context-bar">
              <div>
                <span class="eyebrow">CURRENT OBJECT · workspace-context/v1</span>
                <h1>{{ contextLabel }}</h1>
              </div>
              <div class="context-facts">
                <span>PandaData 时点 {{ providerTimeLabel }}</span>
                <span>实际频率 {{ selectedQuote?.frequency ?? barsFrequency ?? '等待响应' }}</span>
                <span :class="{ error: marketError }">
                  {{ marketError ? '行情不可用' : (selectedQuote?.freshness ?? '等待新鲜度') }}
                </span>
              </div>
            </header>

            <template v-if="currentSection === 'information'">
              <div class="mode-tabs" role="tablist" aria-label="信息工作态">
                <button
                  v-for="mode in informationModes"
                  :key="mode.id"
                  type="button"
                  role="tab"
                  :aria-selected="informationMode === mode.id"
                  :class="{
                    active: informationMode === mode.id,
                    'agent-focus': activeAgentAction === mode.action,
                  }"
                  :data-agent-action="mode.action"
                  data-agent-object="workspace"
                  :data-agent-description="`切换到${mode.label}栏目`"
                  @click="performAction(mode.action)"
                >
                  {{ mode.label }}
                </button>
                <button
                  type="button"
                  class="refresh-action"
                  data-agent-action="refresh_market"
                  data-agent-object="workspace"
                  data-agent-description="刷新当前 PandaData 行情"
                  :disabled="marketLoading || barsLoading"
                  @click="performAction('refresh_market')"
                >
                  {{ marketLoading || barsLoading ? '正在刷新' : '刷新行情' }}
                </button>
              </div>

              <section v-if="informationMode === 'market'" class="market-workspace">
                <aside class="symbol-tape" aria-label="观察标的">
                  <div class="section-heading">
                    <span>观察标的</span>
                    <small>真实行情</small>
                  </div>
                  <button
                    v-for="symbol in symbols"
                    :key="symbol"
                    type="button"
                    class="symbol-row"
                    :class="{
                      active: selectedSymbol === symbol,
                      'agent-focus': activeAgentAction === 'select_symbol' && selectedSymbol === symbol,
                    }"
                    data-agent-action="select_symbol"
                    data-agent-object="symbol"
                    :data-agent-value="symbol"
                    :data-agent-description="`选择 ${symbol}`"
                    @click="performAction('select_symbol', symbol)"
                  >
                    <span>
                      <strong>{{ quotes.find((item) => item.symbol === symbol)?.name ?? symbol }}</strong>
                      <small>{{ symbol }}</small>
                    </span>
                    <span class="numeric">
                      {{ formatNumber(quotes.find((item) => item.symbol === symbol)?.last) }}
                    </span>
                  </button>
                  <p v-if="marketError" class="inline-error" role="alert">
                    {{ marketError }}
                  </p>
                  <p v-else-if="marketLoading && quotes.length === 0" class="loading-line" role="status">
                    正在读取 PandaData…
                  </p>
                </aside>

                <article class="market-canvas">
                  <header class="quote-lead">
                    <div>
                      <span class="eyebrow">PANDADATA · {{ selectedQuote?.market_status ?? 'MARKET STATUS UNKNOWN' }}</span>
                      <h2>{{ selectedQuote?.name ?? selectedSymbol }}</h2>
                      <p>{{ selectedSymbol }} · {{ selectedQuote?.provider ?? 'PandaData' }}</p>
                    </div>
                    <div class="lead-price" :class="changeDirection">
                      <strong>{{ formatNumber(selectedQuote?.last) }}</strong>
                      <span>{{ formatPercent(selectedQuote?.change_percent) }}</span>
                    </div>
                  </header>

                  <div class="chart-frame">
                    <div class="chart-meta">
                      <span>{{ barsFrequency ?? '频率待定' }}</span>
                      <span>{{ bars.length ? `${bars.length} 条` : '无可用序列' }}</span>
                    </div>
                    <svg
                      v-if="chartPoints"
                      class="price-chart"
                      viewBox="0 0 760 246"
                      role="img"
                      :aria-label="chartSummary"
                    >
                      <line x1="16" y1="18" x2="744" y2="18" />
                      <line x1="16" y1="123" x2="744" y2="123" />
                      <line x1="16" y1="228" x2="744" y2="228" />
                      <polyline :points="chartPoints" />
                    </svg>
                    <div v-else-if="barsLoading" class="chart-state" role="status">
                      正在读取真实 K 线…
                    </div>
                    <div v-else-if="barsError" class="chart-state error" role="alert">
                      <strong>K 线不可用</strong>
                      <span>{{ barsError }}</span>
                    </div>
                    <div v-else class="chart-state">
                      当前没有可绘制的 PandaData K 线。
                    </div>
                  </div>
                  <p class="chart-summary">{{ chartSummary }}</p>

                  <dl class="quote-facts">
                    <div><dt>今开</dt><dd>{{ formatNumber(selectedQuote?.open) }}</dd></div>
                    <div><dt>最高</dt><dd>{{ formatNumber(selectedQuote?.high) }}</dd></div>
                    <div><dt>最低</dt><dd>{{ formatNumber(selectedQuote?.low) }}</dd></div>
                    <div><dt>昨收</dt><dd>{{ formatNumber(selectedQuote?.previous_close) }}</dd></div>
                    <div><dt>成交量</dt><dd>{{ formatNumber(selectedQuote?.volume, 0) }}</dd></div>
                  </dl>
                </article>
              </section>

              <section v-else-if="informationMode === 'trade'" class="task-workspace">
                <header class="task-heading">
                  <div>
                    <span class="eyebrow">SIMULATION ORDER DRAFT</span>
                    <h2>仿真订单草稿</h2>
                  </div>
                  <span class="simulation-label">仿真 · 未提交</span>
                </header>
                <p class="task-note">
                  Agent 可以切换方向和填充字段，但不能进入最终复核、提交订单或修改账户事实。
                </p>

                <form class="order-form" @submit.prevent="runCurrentAnalysis">
                  <fieldset>
                    <legend>交易方向</legend>
                    <div class="side-switch">
                      <button
                        type="button"
                        :class="{ selected: orderSide === 'buy', 'agent-focus': activeAgentAction === 'set_order_side_buy' }"
                        data-agent-action="set_order_side_buy"
                        data-agent-object="order_draft"
                        data-agent-description="将未提交草稿设为买入方向"
                        @click="performAction('set_order_side_buy')"
                      >
                        买入
                      </button>
                      <button
                        type="button"
                        :class="{ selected: orderSide === 'sell', 'agent-focus': activeAgentAction === 'set_order_side_sell' }"
                        data-agent-action="set_order_side_sell"
                        data-agent-object="order_draft"
                        data-agent-description="将未提交草稿设为卖出方向"
                        @click="performAction('set_order_side_sell')"
                      >
                        卖出
                      </button>
                    </div>
                  </fieldset>

                  <label>
                    <span>标的</span>
                    <input :value="selectedSymbol" readonly aria-readonly="true" />
                  </label>
                  <label>
                    <span>数量</span>
                    <input
                      v-model.number="orderQuantity"
                      type="number"
                      min="1"
                      step="1"
                      placeholder="由用户或 Agent 填写"
                      :class="{ 'agent-focus': activeAgentAction === 'fill_order_quantity' }"
                      data-agent-action="fill_order_quantity"
                      data-agent-object="order_draft"
                      data-agent-description="填写未提交订单草稿数量"
                    />
                  </label>
                  <label>
                    <span>限价</span>
                    <input
                      v-model.number="orderLimitPrice"
                      type="number"
                      min="0.01"
                      step="0.01"
                      placeholder="由用户或 Agent 填写"
                      :class="{ 'agent-focus': activeAgentAction === 'fill_limit_price' }"
                      data-agent-action="fill_limit_price"
                      data-agent-object="order_draft"
                      data-agent-description="填写未提交订单草稿限价"
                    />
                  </label>

                  <section class="draft-status">
                    <span>草稿状态</span>
                    <strong>等待后端计算与正式风控</strong>
                    <p>行情、费用、资金、授权和组合影响尚未形成同一版本，不能进入 T06。</p>
                  </section>

                  <button
                    type="submit"
                    class="ink-button primary-task"
                    data-agent-workflow="order_review"
                    data-agent-description="运行订单草稿复核工作流"
                  >
                    运行订单草稿复核
                  </button>
                </form>
              </section>

              <section v-else class="task-workspace strategy-workspace">
                <header class="task-heading">
                  <div>
                    <span class="eyebrow">STRATEGY CONTEXT</span>
                    <h2>当前策略条件</h2>
                  </div>
                  <span class="version-label">strategy-draft/v1</span>
                </header>
                <p class="task-note">
                  这里只展示策略输入结构；指标、回测、费用和失效判断必须由后端工作流产物返回。
                </p>
                <dl class="strategy-ledger">
                  <div><dt>目标</dt><dd>等待用户定义</dd></div>
                  <div><dt>适用周期</dt><dd>等待工作流校验</dd></div>
                  <div><dt>入场条件</dt><dd>未形成版本化条件</dd></div>
                  <div><dt>失效条件</dt><dd>必须在产物中显式返回</dd></div>
                  <div><dt>数据版本</dt><dd>{{ selectedQuote ? selectedQuote.provider_time : '行情不可用' }}</dd></div>
                </dl>
                <button
                  type="button"
                  class="ink-button primary-task"
                  data-agent-workflow="strategy_validation"
                  data-agent-description="运行策略验证工作流"
                  @click="runCurrentAnalysis"
                >
                  运行策略条件验证
                </button>
              </section>
            </template>

            <section v-else-if="currentSection === 'portfolio'" class="section-workspace">
              <header class="task-heading">
                <div>
                  <span class="eyebrow">SIMULATION PORTFOLIO</span>
                  <h2>当前仿真持仓</h2>
                </div>
                <span class="simulation-label">仿真结构数据</span>
              </header>
              <p class="task-note">
                数量用于展示页面结构；估值、收益、集中度和可用数量必须来自后端组合 View DTO。
              </p>
              <table>
                <thead>
                  <tr><th>标的</th><th>数量</th><th>可用</th><th>成本来源</th><th>市值估算</th></tr>
                </thead>
                <tbody>
                  <tr v-for="position in simulatedPositions" :key="position.symbol">
                    <td><button type="button" data-agent-action="select_symbol" data-agent-object="symbol" :data-agent-value="position.symbol" @click="performAction('select_symbol', position.symbol)">{{ position.symbol }}</button></td>
                    <td>{{ position.quantity }}</td>
                    <td>{{ position.available }}</td>
                    <td>{{ position.cost }}</td>
                    <td>{{ position.valuation }}</td>
                  </tr>
                </tbody>
              </table>
              <button
                type="button"
                class="ink-button primary-task"
                data-agent-workflow="portfolio_stress"
                data-agent-description="运行持仓与组合压力分析"
                @click="runCurrentAnalysis"
              >
                运行持仓分析
              </button>
            </section>

            <section v-else-if="currentSection === 'watchlist'" class="section-workspace">
              <header class="task-heading">
                <div>
                  <span class="eyebrow">WATCHLIST CONTEXT</span>
                  <h2>我的自选</h2>
                </div>
                <span class="version-label">PandaData 行情</span>
              </header>
              <p class="task-note">选择一行会同步当前标的与右侧 Agent 上下文，不会自动创建订单。</p>
              <table>
                <thead>
                  <tr><th>标的</th><th>名称</th><th>最新价</th><th>涨跌幅</th><th>供应商时点</th></tr>
                </thead>
                <tbody>
                  <tr v-for="symbol in symbols" :key="symbol">
                    <td>
                      <button
                        type="button"
                        data-agent-action="select_symbol"
                        data-agent-object="symbol"
                        :data-agent-value="symbol"
                        @click="performAction('select_symbol', symbol)"
                      >
                        {{ symbol }}
                      </button>
                    </td>
                    <td>{{ quotes.find((item) => item.symbol === symbol)?.name ?? '等待 PandaData' }}</td>
                    <td>{{ formatNumber(quotes.find((item) => item.symbol === symbol)?.last) }}</td>
                    <td>{{ formatPercent(quotes.find((item) => item.symbol === symbol)?.change_percent) }}</td>
                    <td>{{ formatDateTime(quotes.find((item) => item.symbol === symbol)?.provider_time ?? null) }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-if="marketError" class="inline-error" role="alert">{{ marketError }}</p>
            </section>

            <section v-else-if="currentSection === 'history'" class="section-workspace">
              <header class="task-heading">
                <div>
                  <span class="eyebrow">SIMULATION EXECUTION HISTORY</span>
                  <h2>仿真交易记录</h2>
                </div>
                <span class="simulation-label">结构示例 · 非后端事实</span>
              </header>
              <p class="task-note">生产版本必须直接读取订单、成交和事件时间线；前端不推断最终状态。</p>
              <table>
                <thead><tr><th>订单</th><th>标的</th><th>方向</th><th>状态</th><th>时点</th></tr></thead>
                <tbody>
                  <tr v-for="record in simulatedHistory" :key="record.id">
                    <td>{{ record.id }}</td>
                    <td>{{ record.symbol }}</td>
                    <td>{{ record.side }}</td>
                    <td>{{ record.status }}</td>
                    <td>{{ record.time }}</td>
                  </tr>
                </tbody>
              </table>
            </section>

            <section v-else class="section-workspace">
              <header class="task-heading">
                <div>
                  <span class="eyebrow">SIMULATION WALLET</span>
                  <h2>仿真钱包</h2>
                </div>
                <span class="simulation-label">结构示例 · 非后端事实</span>
              </header>
              <p class="task-note">
                钱包只显示账本服务返回的余额、冻结和占用；原型不在浏览器计算可用资金。
              </p>
              <dl class="wallet-ledger">
                <div><dt>总现金</dt><dd>等待仿真账户 View DTO</dd></div>
                <div><dt>可用资金</dt><dd>等待仿真账本</dd></div>
                <div><dt>订单冻结</dt><dd>等待执行服务</dd></div>
                <div><dt>基准币种</dt><dd>人民币 CNY</dd></div>
              </dl>
            </section>
          </main>
        </section>

        <aside v-if="agentCollapsed" class="agent-rail" aria-label="已折叠的上下文 Agent">
          <button
            type="button"
            aria-label="展开交易台 Agent"
            :aria-expanded="false"
            @click="toggleAgentPanel"
          >
            <span>AI</span>
            <i :class="activeWorkflow?.status === 'running' ? 'running-dot' : 'status-dot'" />
          </button>
        </aside>

        <aside v-else class="agent-panel" aria-label="上下文 Agent">
          <header class="agent-header">
            <div>
              <span class="eyebrow">CONTEXT AGENT</span>
              <h2>交易台 Agent</h2>
            </div>
            <div class="agent-header-actions">
              <span class="agent-state">
                <i :class="activeWorkflow?.status === 'running' ? 'running-dot' : 'status-dot'" />
                {{ activeWorkflow?.status === 'running' ? '工作流运行中' : '可用' }}
              </span>
              <button
                type="button"
                class="agent-collapse-button"
                aria-label="折叠交易台 Agent"
                :aria-expanded="true"
                @click="toggleAgentPanel"
              >
                收起
              </button>
            </div>
          </header>

          <section class="agent-context">
            <span>当前上下文</span>
            <strong>{{ contextLabel }}</strong>
            <small>页面对象版本 workspace-context/v1</small>
          </section>

          <details
            v-if="activeWorkflow"
            class="workflow-status"
            :open="workflowExpanded"
            @toggle="onWorkflowToggle"
          >
            <summary>
              <span>
                <i :class="`workflow-${activeWorkflow.status}`" />
                {{ activeWorkflow.code }} · {{ activeWorkflow.title }}
              </span>
              <small>{{ activeWorkflow.status === 'running' ? '运行中' : '已完成，可展开' }}</small>
            </summary>
            <ol>
              <li v-for="step in activeWorkflow.steps" :key="step.id" :data-status="step.status">
                <i />
                <span>{{ step.label }}</span>
                <small>{{ step.status }}</small>
              </li>
            </ol>
            <p class="run-meta">
              Run {{ activeWorkflow.runId }} ·
              {{ formatDateTime(activeWorkflow.startedAt) }}
            </p>
          </details>

          <section class="transcript" data-agent-transcript aria-label="Agent 对话">
            <article
              v-for="message in messages"
              :key="message.id"
              :class="['message', message.role]"
            >
              <span>{{ message.role === 'agent' ? 'Agent' : '你' }}</span>
              <p>{{ message.text }}</p>
              <time>{{ formatDateTime(message.at) }}</time>
            </article>
          </section>

          <details class="action-catalog">
            <summary>查看 Agent 可控动作（{{ AGENT_ACTIONS.length }}）</summary>
            <ul>
              <li v-for="action in AGENT_ACTIONS" :key="action.id">
                <code>{{ action.id }}</code>
                <span>{{ action.description }}</span>
              </li>
            </ul>
          </details>

          <form class="agent-composer" @submit.prevent="submitPrompt()">
            <label for="agent-command">告诉 Agent 要查看、分析或填写什么</label>
            <div class="composer-field">
              <textarea
                id="agent-command"
                v-model="composer"
                rows="2"
                placeholder="例如：查看我的持仓；把数量填写成 200 股"
              />
              <button type="submit" aria-label="发送指令" :disabled="!composer.trim()">
                发送
              </button>
            </div>

            <div class="quick-commands" aria-label="推荐快捷指令">
              <button
                v-for="command in quickCommands"
                :key="command"
                type="button"
                @click="submitPrompt(command)"
              >
                <svg
                  class="prompt-icon"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path d="M21 14a4 4 0 0 1-4 4H9l-5 3v-3a4 4 0 0 1-2-3.46V7a4 4 0 0 1 4-4h11a4 4 0 0 1 4 4Z" />
                </svg>
                <span>{{ command }}</span>
              </button>
            </div>
          </form>
        </aside>
      </div>

      <aside
        v-if="activeToast"
        class="alert-toast"
        :class="`severity-${activeToast.severity}`"
        role="status"
        aria-live="polite"
      >
        <div>
          <span class="eyebrow">REMINDER · {{ activeToast.source }}</span>
          <strong>{{ activeToast.title }}</strong>
          <p>{{ activeToast.detail }}</p>
        </div>
        <button type="button" aria-label="关闭提醒" @click="dismissToast">关闭</button>
      </aside>
    </template>
  </div>
</template>
