import { computed, onScopeDispose, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  consumeNotificationStream,
  NotificationStreamError,
  type NotificationCreatedEvent,
} from '@/services/notificationStream'
import {
  addWatchlistInstrument,
  applyDeskUiAction,
  confirmSimulationDraft,
  confirmSimulationSoftRisk,
  confirmTradePlan,
  createSimulationAccount,
  createSimulationDraft,
  createTradePlanFromCandidate,
  createTradePlanFromPortfolioDeviation,
  createWatchlistGroup,
  createWorkflow,
  cancelWorkflow,
  deleteWatchlistGroup,
  fetchDeskBootstrap,
  fetchDeskQuickCommands,
  fetchInformationFacts,
  fetchBars,
  fetchMarketOverview,
  fetchMarketNews,
  fetchNotificationHistory,
  fetchNotifications,
  fetchProfile,
  fetchResearchCandidates,
  fetchSentimentFacts,
  fetchSimulationAccount,
  fetchSimulationClock,
  fetchSimulationBars,
  fetchSimulationMarketOverview,
  fetchSimulationFills,
  fetchSimulationOrders,
  fetchSimulationPortfolio,
  fetchTradePlan,
  fetchTradeEpisodes,
  fetchTradeEpisodeDecisions,
  fetchTradeEpisodeReview,
  fetchAgentLearningSummary,
  fetchWatchlistGroups,
  fetchWatchlistInstruments,
  fetchWorkflow,
  fetchWorkflowHistory,
  fetchWorkflowEvidence,
  fetchWorkflowProgress,
  retryWorkflow,
  retryTradeEpisodeReview,
  ignoreResearchCandidate,
  isDeskCapabilityEnabled,
  markNotificationRead,
  previewDeskAgent,
  reconcileSimulationOrder,
  resumeSimulationClock,
  removeWatchlistInstrument,
  reviewSimulationDraft,
  reviseTradePlan,
  submitSimulationDraft,
  submitSimulationMarketOrder,
  streamDeskAgentDecision,
  unignoreResearchCandidate,
  updateWatchlistGroup,
  type DeskBootstrap,
  type DeskAgentDecision,
  type DeskAgentPreview,
  DeskApiError,
  type DeskEvidenceBundle,
  type DeskFactBatch,
  type DeskMarketNewsBatch,
  type DeskBar,
  type DeskNotification,
  type DeskQuote,
  type DeskUiActionReceipt,
  type DeskWorkflowRun,
  type DeskWorkflowProgress,
  type QuickCommandStage,
  type ResearchCandidateResponse,
  type SimulationAccount,
  type SimulationClock,
  type SimulationDraft,
  type SimulationDraftInput,
  type SimulationFill,
  type SimulationOrder,
  type SimulationPortfolio,
  type TradePlan,
  type TradePlanActionRevision,
  type TradeDecisionContextInput,
  type TradeDecisionSnapshot,
  type TradeEpisode,
  type TradeReview,
  type AgentLearningSummary,
  type WatchlistGroup,
  type WatchlistInstrument,
} from '@/services/tradingDesk'
import type { ProfileWithRecommendations } from '@/types/api'
import { parseInstrumentId } from '@/domain/instrumentId'
import { makeRequestId } from '@/utils/requestId'

export type DeskSection = 'information' | 'portfolio' | 'watchlist' | 'trading' | 'review'
export type DeskAccountState = 'unknown' | 'absent' | 'available' | 'error'
export type DeskBootstrapStatus = 'loading' | 'ready' | 'error'
export interface QueuedWorkflowIntent {
  id: string
  intent: string
  createdAt: string
}
export type AgentThreadMessage =
  | { id: string; role: 'user'; kind: 'text'; createdAt: string; text: string; status?: never; chunks?: never }
  | { id: string; role: 'assistant'; kind: 'text'; createdAt: string; text: string; status: 'pending' | 'complete'; chunks?: string[] }
  | { id: string; role: 'assistant'; kind: 'workflow'; createdAt: string; runId: string; intent: string; status: DeskWorkflowRun['status'] }
  | { id: string; role: 'assistant'; kind: 'research_report'; createdAt: string; runId: string; evidence: DeskEvidenceBundle }
  | { id: string; role: 'assistant'; kind: 'order_draft'; createdAt: string; draft: SimulationDraft }
  | { id: string; role: 'assistant'; kind: 'order_receipt'; createdAt: string; order: SimulationOrder }
  | { id: string; role: 'assistant'; kind: 'trade_guide'; createdAt: string; guideId: string }
  | { id: string; role: 'assistant'; kind: 'error'; createdAt: string; text: string }

export type GuidedTradeStep = 'symbol' | 'side' | 'quantity' | 'confirm'
export interface GuidedTradeState {
  id: string
  step: GuidedTradeStep
  symbol: string | null
  symbolName: string | null
  side: 'buy' | 'sell' | null
  quantity: string | null
  lastPrice: number | null
  estimatedAmount: number | null
  availableCash: number | null
}

const DEFAULT_SYMBOL = '000001.SZ'
const BASELINE_SYMBOLS = ['000001.SH', '399001.SZ', '000300.SH'] as const
const INDEX_SYMBOLS = new Set<string>(BASELINE_SYMBOLS)
const POLL_INTERVAL_MS = 60_000
const AGENT_THREAD_STORAGE_KEY = 'finance-god:agent-thread:v1'
const WORKFLOW_QUEUE_STORAGE_KEY = 'finance-god:workflow-queue:v1'
const DESK_CONTEXT_STORAGE_PREFIX = 'finance-god:desk-context:v1'
const DESK_SECTIONS = new Set<DeskSection>(['information', 'portfolio', 'watchlist', 'trading', 'review'])
const ACTIVE_WORKFLOW_STATUSES = new Set<DeskWorkflowRun['status']>([
  'queued',
  'running',
  'cancel_requested',
  'cancelling',
])

function failureText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function isMissingSimulationAccount(errorMessage: string): boolean {
  return /not found|账户不存在|simulation account (?:does not exist|was not found|not found)/i.test(errorMessage)
}

function newIdempotencyKey(scope: string): string {
  return `${scope}-${makeRequestId()}`
}

function deskContextStorageKey(): string {
  try {
    const user = JSON.parse(localStorage.getItem('finance-god-user') || 'null') as { id?: unknown } | null
    return `${DESK_CONTEXT_STORAGE_PREFIX}:${typeof user?.id === 'string' ? user.id : 'anonymous'}`
  } catch {
    return `${DESK_CONTEXT_STORAGE_PREFIX}:anonymous`
  }
}

function restoreDeskContext(): { section: DeskSection; symbol: string; reviewEpisodeId: string | null } {
  const fallback = { section: 'information' as DeskSection, symbol: DEFAULT_SYMBOL, reviewEpisodeId: null }
  try {
    const saved = JSON.parse(localStorage.getItem(deskContextStorageKey()) || 'null') as {
      section?: unknown
      symbol?: unknown
      reviewEpisodeId?: unknown
    } | null
    if (
      !saved
      || typeof saved.section !== 'string'
      || !DESK_SECTIONS.has(saved.section as DeskSection)
      || typeof saved.symbol !== 'string'
    ) return fallback
    const instrumentId = parseInstrumentId(saved.symbol)
    const reviewEpisodeId = typeof saved.reviewEpisodeId === 'string' ? saved.reviewEpisodeId : null
    return instrumentId
      ? { section: saved.section as DeskSection, symbol: instrumentId, reviewEpisodeId }
      : fallback
  } catch {
    localStorage.removeItem(deskContextStorageKey())
    return fallback
  }
}

export const useTradingDeskStore = defineStore('trading-desk', () => {
  const restoredContext = restoreDeskContext()
  const section = ref<DeskSection>(restoredContext.section)
  const symbol = ref<string>(restoredContext.symbol)
  const quotes = ref<DeskQuote[]>([])
  const profile = ref<ProfileWithRecommendations | null>(null)
  const informationFacts = ref<DeskFactBatch | null>(null)
  const sentimentFacts = ref<DeskFactBatch | null>(null)
  const marketNews = ref<DeskMarketNewsBatch | null>(null)
  const bars = ref<DeskBar[]>([])
  const notifications = ref<DeskNotification[]>([])
  const account = ref<SimulationAccount | null>(null)
  const simulationClock = ref<SimulationClock | null>(null)
  const portfolio = ref<SimulationPortfolio | null>(null)
  const orders = ref<SimulationOrder[]>([])
  const fills = ref<SimulationFill[]>([])
  const tradeEpisodes = ref<TradeEpisode[]>([])
  const selectedTradeEpisode = ref<TradeEpisode | null>(null)
  const tradeEpisodeDecisions = ref<TradeDecisionSnapshot[]>([])
  const tradeEpisodeReview = ref<TradeReview | null>(null)
  const tradeReviewLoading = ref(false)
  const tradeReviewError = ref<string | null>(null)
  const agentLearningSummary = ref<AgentLearningSummary | null>(null)
  const agentLearningLoading = ref(false)
  const agentLearningError = ref<string | null>(null)
  const watchlistGroups = ref<WatchlistGroup[]>([])
  const watchlistInstruments = ref<Record<string, WatchlistInstrument[]>>({})
  const selectedWatchlistId = ref<string | null>(null)
  const candidates = ref<ResearchCandidateResponse | null>(null)
  const activeDraft = ref<SimulationDraft | null>(null)
  const activeOrder = ref<SimulationOrder | null>(null)
  const activeTradePlan = ref<TradePlan | null>(null)

  const marketError = ref<string | null>(null)
  const profileError = ref<string | null>(null)
  const informationFactsError = ref<string | null>(null)
  const sentimentFactsError = ref<string | null>(null)
  const marketNewsError = ref<string | null>(null)
  const barsError = ref<string | null>(null)
  const notificationError = ref<string | null>(null)
  const notificationStreamError = ref<string | null>(null)
  const simulationError = ref<string | null>(null)
  const accountError = ref<string | null>(null)
  const ordersError = ref<string | null>(null)
  const fillsError = ref<string | null>(null)
  const watchlistError = ref<string | null>(null)
  const candidateError = ref<string | null>(null)
  const orderError = ref<string | null>(null)
  const tradePlanError = ref<string | null>(null)
  const loadingMarket = ref(false)
  const marketLoadedAt = ref<string | null>(null)
  const loadingSimulation = ref(false)
  const simulationLoadedAt = ref<string | null>(null)
  const loadingWatchlists = ref(false)
  const loadingCandidates = ref(false)
  const hasSimulationAccount = ref<boolean | null>(null)
  const accountState = ref<DeskAccountState>('unknown')
  const activeWorkflow = ref<DeskWorkflowRun | null>(null)
  const workflowHistory = ref<DeskWorkflowRun[]>([])
  const workflowHistoryCursor = ref<string | null>(null)
  const workflowHistoryLoading = ref(false)
  const workflowHistoryError = ref<string | null>(null)
  const selectedHistoricalWorkflow = ref<DeskWorkflowRun | null>(null)
  const selectedHistoricalProgress = ref<DeskWorkflowProgress | null>(null)
  const selectedHistoricalEvidence = ref<DeskEvidenceBundle | null>(null)
  const queuedWorkflowIntents = ref<QueuedWorkflowIntent[]>([])
  const agentMessages = ref<AgentThreadMessage[]>([])
  const activeWorkflowProgress = ref<DeskWorkflowProgress | null>(null)
  const activeWorkflowEvidence = ref<DeskEvidenceBundle | null>(null)
  const agentDecision = ref<DeskAgentDecision | null>(null)
  const agentPreview = ref<DeskAgentPreview | null>(null)
  const agentPreviewLoading = ref(false)
  const agentPreviewError = ref<string | null>(null)
  const directReply = ref<string | null>(null)
  const directAnswerError = ref<string | null>(null)
  const agentRequestCount = ref(0)
  const workflowIntent = ref<string | null>(null)
  const workflowError = ref<string | null>(null)
  const workflowEvidenceError = ref<string | null>(null)
  const workflowSubmitting = ref(false)
  const contextVersion = ref(0)
  const serverContextVersion = ref<string | null>(null)
  const serverQuickCommands = ref<readonly string[]>([])
  const quickCommandsError = ref<string | null>(null)
  const quickCommandsLoading = ref(false)
  const uiActionCatalog = ref<DeskBootstrap['ui_action_catalog']>([])
  const deskCapabilities = ref<Record<string, boolean>>({})
  const profileProjection = ref<DeskBootstrap['profile_projection'] | null>(null)
  const bootstrapStatus = ref<DeskBootstrapStatus>('loading')
  const bootstrapError = ref<string | null>(null)
  const notificationHistory = ref<DeskNotification[]>([])
  const uiActionError = ref<string | null>(null)
  const lastUiActionReceipt = ref<DeskUiActionReceipt | null>(null)
  const workspaceControl = ref<{ section: DeskSection; kind: 'filter' | 'sort'; field: string; value: string } | null>(null)
  const openedRecord = ref<{ type: string; id: string } | null>(null)
  const candidateLocation = ref<{ symbol: string; target: 'watchlist' | 'research' } | null>(null)
  const tradeDraftPrefill = ref<{
    side: 'buy' | 'sell'
    quantity: string
    priceType: 'market' | 'limit'
    limitPrice: string | null
    source?: 'agent_strategy'
    planId?: string
  } | null>(null)
  const requestedArtifactId = ref<string | null>(null)
  const requestedReminderId = ref<string | null>(null)
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let simulationClockTimer: ReturnType<typeof setInterval> | null = null
  let simulationClockRefreshing = false
  let workflowObserver: AbortController | null = null
  let bootstrapRequestId = 0
  let agentPreviewRequestId = 0
  let barsRequestId = 0
  let marketNewsRequestId = 0
  const appliedTradePlanPrefills = new Set<string>()

  function persistDeskContext() {
    localStorage.setItem(deskContextStorageKey(), JSON.stringify({
      section: section.value,
      symbol: symbol.value,
    }))
  }

  function persistAgentMessages() {
    sessionStorage.setItem(AGENT_THREAD_STORAGE_KEY, JSON.stringify(agentMessages.value.slice(-80)))
  }

  function persistWorkflowQueue() {
    sessionStorage.setItem(WORKFLOW_QUEUE_STORAGE_KEY, JSON.stringify(queuedWorkflowIntents.value))
  }

  function restoreWorkflowQueue() {
    const raw = sessionStorage.getItem(WORKFLOW_QUEUE_STORAGE_KEY)
    if (!raw) return
    try {
      const parsed = JSON.parse(raw)
      queuedWorkflowIntents.value = Array.isArray(parsed) ? parsed : []
    } catch {
      sessionStorage.removeItem(WORKFLOW_QUEUE_STORAGE_KEY)
    }
  }

  function restoreAgentMessages() {
    const raw = sessionStorage.getItem(AGENT_THREAD_STORAGE_KEY)
    if (!raw) return
    try {
      const parsed = JSON.parse(raw)
      agentMessages.value = Array.isArray(parsed) ? parsed : []
    } catch {
      sessionStorage.removeItem(AGENT_THREAD_STORAGE_KEY)
    }
  }

  function appendAgentMessage(message: AgentThreadMessage) {
    agentMessages.value = [...agentMessages.value, message]
    persistAgentMessages()
  }

  function replaceAgentMessage(id: string, message: AgentThreadMessage) {
    agentMessages.value = agentMessages.value.map((item) => item.id === id ? message : item)
    persistAgentMessages()
  }

  function nextMessageId(kind: string) {
    return `${kind}-${makeRequestId()}`
  }

  const portfolioSymbols = computed(() => portfolio.value?.positions.map((item) => item.instrument_id) ?? [])
  const watchlistSymbols = computed(() => Object.values(watchlistInstruments.value).flat().map((item) => item.instrument_id))
  const extraQuoteSymbols = ref<string[]>([])
  const quoteSymbols = computed(() => {
    const symbols = [...new Set([
      ...BASELINE_SYMBOLS,
      symbol.value,
      ...portfolioSymbols.value,
      ...watchlistSymbols.value,
      ...extraQuoteSymbols.value,
    ].filter(Boolean))]
    if (!simulationClock.value) return symbols
    return [...new Set([
      DEFAULT_SYMBOL,
      ...symbols.filter(instrumentId => !INDEX_SYMBOLS.has(instrumentId)),
    ])]
  })
  const selectedQuote = computed(() => quotes.value.find((item) => item.symbol === symbol.value) ?? null)
  const unreadCount = computed(() => notifications.value.filter((item) => item.status !== 'read').length)
  const agentSubmitting = computed(() => agentRequestCount.value > 0)
  const workflowActive = computed(() => (
    workflowSubmitting.value
    || (activeWorkflow.value ? ACTIVE_WORKFLOW_STATUSES.has(activeWorkflow.value.status) : false)
  ))
  const profileSummary = computed(() => {
    // Prefer desensitized desk projection for shell fields. objective_profile is
    // never part of the projection contract; only attach real full-profile values.
    if (profileProjection.value?.available) {
      return {
        version: profileProjection.value.version,
        archetype_code: profileProjection.value.archetype_code,
        archetype_title: profileProjection.value.archetype_title,
        risk_level: profileProjection.value.risk_level,
        loss_tolerance_percent: profileProjection.value.loss_tolerance_percent,
        confidence: profileProjection.value.confidence,
        completeness: profileProjection.value.completeness,
        education_only: profileProjection.value.education_only,
        selected_direction: profileProjection.value.selected_direction,
        recommended_directions: profileProjection.value.recommended_directions,
        objective_profile: profile.value?.profile?.objective_profile ?? null,
      }
    }
    return profile.value?.profile ?? null
  })
  const selectedWatchlist = computed(() => watchlistGroups.value.find((item) => item.group_id === selectedWatchlistId.value) ?? null)
  const selectedWatchlistInstruments = computed(() => selectedWatchlistId.value ? watchlistInstruments.value[selectedWatchlistId.value] ?? [] : [])
  const quickCommands = computed<readonly string[]>(() => serverQuickCommands.value)

  /** Contextual quick actions: direct left-panel operations based on current state */
  const contextualActions = computed<{ id: string; label: string; icon: 'navigate' | 'fill' | 'add' | 'refresh' }[]>(() => {
    const actions: { id: string; label: string; icon: 'navigate' | 'fill' | 'add' | 'refresh' }[] = []
    if (section.value !== 'trading' && accountState.value === 'available') {
      actions.push({ id: 'goto_trading', label: '跳转到交易', icon: 'navigate' })
    }
    if (section.value !== 'portfolio' && accountState.value === 'available') {
      actions.push({ id: 'goto_portfolio', label: '查看持仓', icon: 'navigate' })
    }
    if (section.value === 'trading' && accountState.value === 'available' && selectedQuote.value) {
      actions.push({ id: 'prefill_buy', label: `买入 ${symbol.value}`, icon: 'fill' })
      const pos = portfolio.value?.positions.find((p) => p.instrument_id === symbol.value)
      if (pos && Number(pos.available_quantity) > 0) {
        actions.push({ id: 'prefill_sell', label: `卖出 ${symbol.value}`, icon: 'fill' })
      }
    }
    if (accountState.value === 'available' && !guidedTrade.value) {
      actions.push({ id: 'start_guided_trade', label: '引导下单', icon: 'fill' })
    }
    if (section.value !== 'trading' && selectedQuote.value && accountState.value === 'available') {
      actions.push({ id: 'trade_current', label: `交易 ${symbol.value}`, icon: 'fill' })
    }
    if (section.value !== 'watchlist') {
      actions.push({ id: 'goto_watchlist', label: '查看自选', icon: 'navigate' })
    }
    if (watchlistGroups.value.length > 0) {
      const allInstruments = Object.values(watchlistInstruments.value).flat()
      const isInWatchlist = allInstruments.some((item) => item.instrument_id === symbol.value)
      if (!isInWatchlist) {
        actions.push({ id: 'add_watchlist', label: `${symbol.value} 加入自选`, icon: 'add' })
      }
    }
    return actions.slice(0, 4)
  })

  /** Execute a quick action directly on the left panel without going through agent intent */
  function executeQuickAction(actionId: string) {
    switch (actionId) {
      case 'goto_trading':
        setSection('trading')
        appendAgentMessage({
          id: nextMessageId('action'),
          role: 'assistant',
          kind: 'text',
          createdAt: new Date().toISOString(),
          text: `已跳转到交易工作区，当前标的 ${symbol.value}。`,
          status: 'complete',
        })
        break
      case 'goto_portfolio':
        setSection('portfolio')
        appendAgentMessage({
          id: nextMessageId('action'),
          role: 'assistant',
          kind: 'text',
          createdAt: new Date().toISOString(),
          text: '已跳转到持仓工作区。',
          status: 'complete',
        })
        break
      case 'goto_watchlist':
        setSection('watchlist')
        appendAgentMessage({
          id: nextMessageId('action'),
          role: 'assistant',
          kind: 'text',
          createdAt: new Date().toISOString(),
          text: '已跳转到自选工作区。',
          status: 'complete',
        })
        break
      case 'prefill_buy':
        tradeDraftPrefill.value = {
          side: 'buy',
          quantity: '',
          priceType: 'market',
          limitPrice: null,
        }
        if (section.value !== 'trading') setSection('trading')
        appendAgentMessage({
          id: nextMessageId('action'),
          role: 'assistant',
          kind: 'text',
          createdAt: new Date().toISOString(),
          text: `已为 ${symbol.value} 填写买入方向，请输入数量后手动提交。`,
          status: 'complete',
        })
        break
      case 'prefill_sell': {
        const pos = portfolio.value?.positions.find((p) => p.instrument_id === symbol.value)
        tradeDraftPrefill.value = {
          side: 'sell',
          quantity: pos ? String(pos.available_quantity) : '',
          priceType: 'market',
          limitPrice: null,
        }
        if (section.value !== 'trading') setSection('trading')
        appendAgentMessage({
          id: nextMessageId('action'),
          role: 'assistant',
          kind: 'text',
          createdAt: new Date().toISOString(),
          text: `已为 ${symbol.value} 填写卖出方向${pos ? `（可卖 ${pos.available_quantity}）` : ''}，请确认后手动提交。`,
          status: 'complete',
        })
        break
      }
      case 'trade_current':
        setSymbol(symbol.value)
        setSection('trading')
        appendAgentMessage({
          id: nextMessageId('action'),
          role: 'assistant',
          kind: 'text',
          createdAt: new Date().toISOString(),
          text: `已跳转到交易工作区，标的 ${symbol.value}，请填写方向和数量。`,
          status: 'complete',
        })
        break
      case 'add_watchlist': {
        const targetGroupId = selectedWatchlistId.value ?? watchlistGroups.value[0]?.group_id
        if (!targetGroupId) break
        void addToWatchlist(targetGroupId, symbol.value).then(() => {
          setSection('watchlist')
          appendAgentMessage({
            id: nextMessageId('action'),
            role: 'assistant',
            kind: 'text',
            createdAt: new Date().toISOString(),
            text: `已将 ${symbol.value} 加入自选，已跳转到自选工作区。`,
            status: 'complete',
          })
        })
        break
      }
      case 'start_guided_trade':
        startGuidedTrade()
        break
    }
  }

  /** Apply evidence-based follow-up action (e.g. from research report) */
  function applyReportAction(actionType: 'trade' | 'watchlist', evidence: DeskEvidenceBundle) {
    const targetSymbol = symbol.value
    if (actionType === 'trade') {
      setSymbol(targetSymbol)
      const buySignal = evidence.conclusion?.toLowerCase().includes('买入')
        || evidence.conclusion?.toLowerCase().includes('buy')
      tradeDraftPrefill.value = {
        side: buySignal ? 'buy' : 'sell',
        quantity: '',
        priceType: 'market',
        limitPrice: null,
        source: 'agent_strategy',
      }
      setSection('trading')
      appendAgentMessage({
        id: nextMessageId('report-action'),
        role: 'assistant',
        kind: 'text',
        createdAt: new Date().toISOString(),
        text: `已根据研究报告跳转到交易，标的 ${targetSymbol}。请核对行情后填写数量并手动提交。`,
        status: 'complete',
      })
    } else if (actionType === 'watchlist') {
      const targetGroupId = selectedWatchlistId.value ?? watchlistGroups.value[0]?.group_id
      if (!targetGroupId) return
      void addToWatchlist(targetGroupId, targetSymbol).then(() => {
        setSymbol(targetSymbol)
        setSection('watchlist')
        appendAgentMessage({
          id: nextMessageId('report-action'),
          role: 'assistant',
          kind: 'text',
          createdAt: new Date().toISOString(),
          text: `已将 ${targetSymbol} 加入自选并跳转到自选工作区。`,
          status: 'complete',
        })
      })
    }
  }

  // ── Guided Trade Flow (引导式下单) ──────────────────────────────────────
  const guidedTrade = ref<GuidedTradeState | null>(null)

  function startGuidedTrade(presetSymbol?: string) {
    const guideId = makeRequestId()
    const startSymbol = presetSymbol ?? symbol.value
    const quote = quotes.value.find((q) => q.symbol === startSymbol)
    guidedTrade.value = {
      id: guideId,
      step: 'symbol',
      symbol: startSymbol,
      symbolName: quote?.name ?? null,
      side: null,
      quantity: null,
      lastPrice: quote?.last ?? null,
      estimatedAmount: null,
      availableCash: account.value ? Number(account.value.cash_available_rmb) : null,
    }
    // Navigate to trading workspace
    if (section.value !== 'trading') setSection('trading')
    setSymbol(startSymbol)
    // Add guide message to thread
    appendAgentMessage({
      id: `trade-guide-${guideId}`,
      role: 'assistant',
      kind: 'trade_guide',
      createdAt: new Date().toISOString(),
      guideId,
    })
  }

  function advanceGuidedTrade(field: 'symbol' | 'side' | 'quantity', value: string) {
    if (!guidedTrade.value) return
    const guide = guidedTrade.value

    if (field === 'symbol') {
      const normalizedSymbol = value.trim().toUpperCase()
      const quote = quotes.value.find((q) => q.symbol === normalizedSymbol)
      guide.symbol = normalizedSymbol
      guide.symbolName = quote?.name ?? null
      guide.lastPrice = quote?.last ?? null
      guide.step = 'side'
      setSymbol(normalizedSymbol)
      // Auto-fill symbol on left side
      tradeDraftPrefill.value = {
        side: 'buy',
        quantity: '',
        priceType: 'market',
        limitPrice: null,
        source: 'agent_strategy',
      }
    } else if (field === 'side') {
      guide.side = value as 'buy' | 'sell'
      guide.step = 'quantity'
      // Update left side direction
      tradeDraftPrefill.value = {
        side: guide.side,
        quantity: guide.quantity ?? '',
        priceType: 'market',
        limitPrice: null,
        source: 'agent_strategy',
      }
    } else if (field === 'quantity') {
      guide.quantity = value
      const qty = Number(value)
      guide.estimatedAmount = guide.lastPrice && qty > 0 ? guide.lastPrice * qty : null
      guide.availableCash = account.value ? Number(account.value.cash_available_rmb) : null
      guide.step = 'confirm'
      // Fill quantity on left side
      tradeDraftPrefill.value = {
        side: guide.side ?? 'buy',
        quantity: value,
        priceType: 'market',
        limitPrice: null,
        source: 'agent_strategy',
      }
    }
    guidedTrade.value = { ...guide }
  }

  function confirmGuidedTrade() {
    if (!guidedTrade.value || guidedTrade.value.step !== 'confirm') return
    const guide = guidedTrade.value
    // Ensure final prefill is complete
    tradeDraftPrefill.value = {
      side: guide.side ?? 'buy',
      quantity: guide.quantity ?? '',
      priceType: 'market',
      limitPrice: null,
      source: 'agent_strategy',
    }
    appendAgentMessage({
      id: nextMessageId('guide-done'),
      role: 'assistant',
      kind: 'text',
      createdAt: new Date().toISOString(),
      text: `交易信息已全部填入左侧：${guide.side === 'buy' ? '买入' : '卖出'} ${guide.symbol} ${guide.quantity} 股。请核对行情后点击提交按钮完成交易。`,
      status: 'complete',
    })
    guidedTrade.value = null
  }

  function cancelGuidedTrade() {
    if (!guidedTrade.value) return
    guidedTrade.value = null
    tradeDraftPrefill.value = null
    appendAgentMessage({
      id: nextMessageId('guide-cancel'),
      role: 'assistant',
      kind: 'text',
      createdAt: new Date().toISOString(),
      text: '已取消引导式下单。',
      status: 'complete',
    })
  }

  let quickCommandRequestId = 0
  let quickCommandStage: QuickCommandStage = 'initial'
  let quickCommandReference: string | null = null
  let notificationStream: AbortController | null = null
  let notificationStreamOwnerId: string | null = null

  function notificationCursorKey(): string {
    return `finance-god:notification-cursor:v1:${notificationStreamOwnerId ?? 'anonymous'}`
  }

  function applyBootstrap(bootstrap: DeskBootstrap) {
    notificationStreamOwnerId = bootstrap.owner_id
    serverContextVersion.value = bootstrap.context_version
    uiActionCatalog.value = bootstrap.ui_action_catalog
    deskCapabilities.value = { ...bootstrap.capabilities }
    profileProjection.value = bootstrap.profile_projection
    quickCommandStage = 'initial'
    quickCommandReference = null
    if (bootstrap.section && bootstrap.section !== section.value) {
      section.value = bootstrap.section
    }
    if (bootstrap.symbol && bootstrap.symbol !== symbol.value) {
      symbol.value = bootstrap.symbol
    }
    bootstrapStatus.value = 'ready'
    bootstrapError.value = null
  }

  function resetBootstrapFacts() {
    quickCommandRequestId += 1
    serverContextVersion.value = null
    agentDecision.value = null
    agentPreviewRequestId += 1
    agentPreview.value = null
    agentPreviewLoading.value = false
    agentPreviewError.value = null
    serverQuickCommands.value = []
    quickCommandsError.value = null
    quickCommandsLoading.value = false
    uiActionCatalog.value = []
    profileProjection.value = null
    // Missing keys must not be treated as enabled.
    deskCapabilities.value = {
      workflow_create: false,
      workflow_worker: false,
      agent_answer: false,
      market_data: false,
      ui_actions: false,
      order_submit: false,
      order_cancel: false,
      fund_transfer: false,
    }
  }

  async function previewAgentIntent(intent: string) {
    const message = intent.trim()
    const requestId = ++agentPreviewRequestId
    agentPreview.value = null
    agentPreviewError.value = null
    if (!message || !serverContextVersion.value) {
      agentPreviewLoading.value = false
      return
    }
    agentPreviewLoading.value = true
    const requestedContext = serverContextVersion.value
    try {
      const preview = await previewDeskAgent({
        message,
        section: section.value,
        symbol: symbol.value,
        contextVersion: requestedContext,
        activeWorkflow: workflowActive.value,
        orderDraft: activeDraft.value
          ? {
              id: activeDraft.value.draft.draft_id,
              version: String(activeDraft.value.draft.revision),
            }
          : undefined,
      })
      if (
        requestId !== agentPreviewRequestId
        || serverContextVersion.value !== requestedContext
      ) return
      agentPreview.value = preview
    } catch (error) {
      if (requestId !== agentPreviewRequestId) return
      agentPreviewError.value = failureText(error, '执行方式预览失败')
    } finally {
      if (requestId === agentPreviewRequestId) agentPreviewLoading.value = false
    }
  }

  function clearBootstrapState(reason: string) {
    resetBootstrapFacts()
    bootstrapStatus.value = 'error'
    bootstrapError.value = reason
  }

  async function refreshQuickCommands(
    stage: QuickCommandStage = quickCommandStage,
    reference: string | null = quickCommandReference,
    force = false,
  ) {
    if (!serverContextVersion.value) return
    if (!force && stage === quickCommandStage && reference === quickCommandReference) {
      return
    }
    const requestId = ++quickCommandRequestId
    const requestedContext = serverContextVersion.value
    const requestedSection = section.value
    const requestedSymbol = symbol.value
    quickCommandsLoading.value = true
    serverQuickCommands.value = []
    quickCommandsError.value = null
    try {
      const response = await fetchDeskQuickCommands({
        stage,
        section: requestedSection,
        symbol: requestedSymbol,
        contextVersion: requestedContext,
        ...(stage === 'after_answer' && reference
          ? { decisionId: reference }
          : {}),
        ...(stage === 'after_workflow' && reference
          ? { runId: reference }
          : {}),
      })
      if (
        requestId !== quickCommandRequestId
        || serverContextVersion.value !== requestedContext
        || section.value !== requestedSection
        || symbol.value !== requestedSymbol
      ) return
      serverQuickCommands.value = response.quick_commands
      quickCommandsError.value = response.quick_commands_error
      quickCommandStage = stage
      quickCommandReference = reference
    } catch (error) {
      if (requestId !== quickCommandRequestId) return
      serverQuickCommands.value = []
      quickCommandsError.value = failureText(error, '快捷指令生成暂时不可用，请直接输入任务。')
    } finally {
      if (requestId === quickCommandRequestId) quickCommandsLoading.value = false
    }
  }

  function rerollQuickCommands() {
    return refreshQuickCommands(quickCommandStage, quickCommandReference, true)
  }

  function setSection(next: DeskSection) {
    const switchedFromIndexToTradableStock = next === 'trading' && INDEX_SYMBOLS.has(symbol.value)
    if (switchedFromIndexToTradableStock) {
      barsRequestId += 1
      bars.value = []
      symbol.value = DEFAULT_SYMBOL
      barsFrequency.value = 'daily'
    }
    quickCommandRequestId += 1
    section.value = next
    persistDeskContext()
    contextVersion.value += 1
    serverQuickCommands.value = []
    quickCommandsError.value = null
    quickCommandsLoading.value = false
    if (next === 'portfolio') void loadSimulationData()
    if (next === 'watchlist') void Promise.all([loadWatchlists(), loadCandidates()])
    if (next === 'trading') void loadSimulationData()
    if (switchedFromIndexToTradableStock) {
      void refreshMarket()
      void loadBars()
    }
    if (next === 'review') {
      void loadReviewWorkspace()
      return
    }
    void refreshBootstrap()
  }

  async function loadTradeEpisodes() {
    tradeReviewLoading.value = true
    tradeReviewError.value = null
    try {
      tradeEpisodes.value = await fetchTradeEpisodes()
      if (selectedTradeEpisode.value) {
        selectedTradeEpisode.value = tradeEpisodes.value.find(
          (item) => item.episode_id === selectedTradeEpisode.value?.episode_id,
        ) ?? null
      } else if (restoredContext.reviewEpisodeId) {
        // Restore previously-selected episode after page refresh
        const restored = tradeEpisodes.value.find(
          (item) => item.episode_id === restoredContext.reviewEpisodeId,
        )
        if (restored) void selectTradeEpisode(restored)
      }
    } catch (error) {
      tradeReviewError.value = failureText(error, '交易案例读取失败')
    } finally {
      tradeReviewLoading.value = false
    }
  }

  async function loadAgentLearningSummary() {
    agentLearningLoading.value = true
    agentLearningError.value = null
    try {
      agentLearningSummary.value = await fetchAgentLearningSummary()
    } catch (error) {
      agentLearningError.value = failureText(error, 'Agent 自学习状态读取失败')
    } finally {
      agentLearningLoading.value = false
    }
  }

  async function loadReviewWorkspace() {
    await Promise.all([loadTradeEpisodes(), loadAgentLearningSummary()])
  }

  async function selectTradeEpisode(episode: TradeEpisode) {
    selectedTradeEpisode.value = episode
    persistDeskContext()
    tradeEpisodeDecisions.value = []
    tradeEpisodeReview.value = null
    tradeReviewLoading.value = true
    tradeReviewError.value = null
    try {
      tradeEpisodeDecisions.value = await fetchTradeEpisodeDecisions(episode.episode_id)
      if (episode.review_status === 'completed' || episode.review_status === 'failed') {
        tradeEpisodeReview.value = await fetchTradeEpisodeReview(episode.episode_id)
      }
    } catch (error) {
      tradeReviewError.value = failureText(error, '交易案例详情读取失败')
    } finally {
      tradeReviewLoading.value = false
    }
  }

  async function retrySelectedTradeReview() {
    if (!selectedTradeEpisode.value) throw new Error('未选择交易案例')
    tradeReviewLoading.value = true
    tradeReviewError.value = null
    try {
      tradeEpisodeReview.value = await retryTradeEpisodeReview(
        selectedTradeEpisode.value.episode_id,
        newIdempotencyKey('trade-review-retry'),
      )
      await loadTradeEpisodes()
    } catch (error) {
      tradeReviewError.value = failureText(error, '复盘重试失败')
      throw error
    } finally {
      tradeReviewLoading.value = false
    }
  }

  const barsFrequency = ref<string | undefined>('daily')
  const marketFactsNotice = computed(() => (
    INDEX_SYMBOLS.has(symbol.value)
      ? '当前标的是指数；融资余额与公司披露事实仅支持 A 股个股。切换至个股后可读取 PandaData 真实数据。'
      : null
  ))
  const minuteBarsSupported = computed(() => !INDEX_SYMBOLS.has(symbol.value))
  const indexSwitchNotice = computed(() => (
    section.value === 'trading' && symbol.value === DEFAULT_SYMBOL && INDEX_SYMBOLS.has(restoredContext.symbol)
      ? `指数标的不能用于模拟交易，已自动切换至 ${DEFAULT_SYMBOL}。`
      : null
  ))

  function setSymbol(next: string) {
    const normalized = parseInstrumentId(next)
    if (!normalized || normalized === symbol.value) return
    if (INDEX_SYMBOLS.has(normalized)) barsFrequency.value = 'daily'
    quickCommandRequestId += 1
    barsRequestId += 1
    bars.value = []
    symbol.value = normalized
    persistDeskContext()
    contextVersion.value += 1
    serverQuickCommands.value = []
    quickCommandsError.value = null
    quickCommandsLoading.value = false
    void loadMarketFacts()
    void loadBars()
    void refreshBootstrap()
  }

  function setBarsFrequency(freq: string | undefined) {
    if (barsFrequency.value === freq) return
    barsFrequency.value = freq
    bars.value = []
    void loadBars()
  }

  async function refreshMarket(options: { withBars?: boolean } = {}) {
    loadingMarket.value = true
    marketError.value = null
    try {
      const result = simulationClock.value
        ? await fetchSimulationMarketOverview(quoteSymbols.value)
        : await fetchMarketOverview(quoteSymbols.value)
      quotes.value = result.quotes
      marketLoadedAt.value = new Date().toISOString()
      if (result.warnings.length) {
        marketError.value = result.warnings
          .map((warning) => `${warning.symbol ? `${warning.symbol}：` : ''}${warning.message}`)
          .join('；')
      }
    }
    catch (error) { marketError.value = failureText(error, '真实行情不可用') }
    finally { loadingMarket.value = false }
    // 轮询只刷新快照；K线仅在显式要求（手动刷新、切换标的/频率、初始化）时重拉。
    if (options.withBars) void loadBars()
  }

  async function ensureQuote(instrumentId: string): Promise<DeskQuote | null> {
    const cached = quotes.value.find((item) => item.symbol === instrumentId)
    if (cached) return cached
    const result = simulationClock.value
      ? await fetchSimulationMarketOverview([instrumentId])
      : await fetchMarketOverview([instrumentId])
    const fetched = result.quotes
    if (result.warnings.length) {
      marketError.value = result.warnings
        .map((warning) => `${warning.symbol ? `${warning.symbol}：` : ''}${warning.message}`)
        .join('；')
    }
    if (fetched.length) {
      const known = new Set(quotes.value.map((item) => item.symbol))
      quotes.value = [...quotes.value, ...fetched.filter((item) => !known.has(item.symbol))]
    }
    return fetched.find((item) => item.symbol === instrumentId) ?? null
  }

  async function loadBars() {
    const requestId = ++barsRequestId
    const requestedSymbol = symbol.value
    barsError.value = null
    const freq = barsFrequency.value
    bars.value = []
    try {
      const result = simulationClock.value
        ? await fetchSimulationBars(requestedSymbol, freq ?? '1m')
        : await fetchBars(requestedSymbol, freq)
      if (requestId === barsRequestId && symbol.value === requestedSymbol && barsFrequency.value === freq) {
        bars.value = result
      }
    } catch (error) {
      if (requestId === barsRequestId) barsError.value = failureText(error, 'K线数据不可用')
    }
  }

  async function ensureQuoteSymbol(next: string) {
    const symbolId = next.trim()
    if (!symbolId) return
    if (!extraQuoteSymbols.value.includes(symbolId)) {
      extraQuoteSymbols.value = [...extraQuoteSymbols.value, symbolId]
    }
    if (!quotes.value.some((item) => item.symbol === symbolId)) {
      await refreshMarket()
    }
  }

  async function refreshPortfolioWorkspace() {
    await Promise.all([loadSimulationData(), refreshMarket()])
  }

  async function refreshTradingWorkspace() {
    await Promise.all([loadSimulationData(), refreshMarket()])
  }

  async function loadProfile() {
    profileError.value = null
    try {
      profile.value = await fetchProfile()
    } catch (error) {
      profile.value = null
      const message = failureText(error, '画像不可用')
      profileError.value = message === 'PROFILE_NOT_FOUND' || /PROFILE_NOT_FOUND/.test(message)
        ? 'PROFILE_NOT_FOUND'
        : message
    }
  }

  async function loadMarketFacts() {
    const requestedSymbol = symbol.value
    informationFactsError.value = null
    sentimentFactsError.value = null
    if (simulationClock.value || marketFactsNotice.value) {
      informationFacts.value = null
      sentimentFacts.value = null
      return
    }
    if (informationFacts.value?.symbol !== requestedSymbol) informationFacts.value = null
    if (sentimentFacts.value?.symbol !== requestedSymbol) sentimentFacts.value = null
    const [information, sentiment] = await Promise.allSettled([
      fetchInformationFacts(requestedSymbol),
      fetchSentimentFacts(requestedSymbol),
    ])
    if (symbol.value !== requestedSymbol) return
    if (information.status === 'fulfilled' && information.value.symbol === requestedSymbol) {
      informationFacts.value = information.value
    } else {
      informationFactsError.value = information.status === 'rejected'
        ? failureText(information.reason, '市场资讯不可用')
        : `服务端返回了其他标的的披露事实（${information.value.symbol || '未知标的'}）。`
    }
    if (sentiment.status === 'fulfilled' && sentiment.value.symbol === requestedSymbol) {
      sentimentFacts.value = sentiment.value
    } else {
      sentimentFactsError.value = sentiment.status === 'rejected'
        ? failureText(sentiment.reason, '市场情绪事实不可用')
        : `服务端返回了其他标的的融资事实（${sentiment.value.symbol || '未知标的'}）。`
    }
  }

  async function loadMarketNews(forceRefresh = false) {
    const requestId = ++marketNewsRequestId
    marketNewsError.value = null
    if (simulationClock.value) {
      marketNews.value = null
      return
    }
    try {
      const result = await fetchMarketNews(8, forceRefresh)
      if (requestId !== marketNewsRequestId || simulationClock.value) return
      marketNews.value = result
    } catch (error) {
      if (requestId !== marketNewsRequestId || simulationClock.value) return
      marketNews.value = null
      marketNewsError.value = failureText(error, '市场资讯抓取不可用')
    }
  }

  async function refreshOverviewWorkspace() {
    await Promise.all([
      refreshMarket({ withBars: true }),
      loadMarketFacts(),
      loadMarketNews(true),
    ])
  }

  async function loadNotifications() {
    notificationError.value = null
    try { notifications.value = await fetchNotifications() }
    catch (error) { notificationError.value = failureText(error, '提醒不可用') }
  }

  function applyNotificationEvent(event: NotificationCreatedEvent) {
    const notification: DeskNotification = {
      ...event.payload,
      notification_id: event.notification_id,
    }
    if (!notifications.value.some((item) => item.notification_id === event.notification_id)) {
      notifications.value = [notification, ...notifications.value]
    }
    if (
      notificationHistory.value.length
      && !notificationHistory.value.some((item) => item.notification_id === event.notification_id)
    ) {
      notificationHistory.value = [notification, ...notificationHistory.value]
    }
    localStorage.setItem(notificationCursorKey(), event.cursor)
    notificationStreamError.value = null
  }

  function stopNotificationStream() {
    notificationStream?.abort()
    notificationStream = null
  }

  function startNotificationStream() {
    stopNotificationStream()
    if (!notificationStreamOwnerId || document.hidden) return
    const controller = new AbortController()
    notificationStream = controller
    void observeNotificationStream(controller)
  }

  async function observeNotificationStream(controller: AbortController) {
    while (!controller.signal.aborted && !document.hidden) {
      try {
        await consumeNotificationStream({
          cursor: localStorage.getItem(notificationCursorKey()),
          signal: controller.signal,
          onEvent: applyNotificationEvent,
        })
        if (!controller.signal.aborted) {
          notificationStreamError.value = '实时提醒已断开，正在重连。'
        }
      } catch (error) {
        if (controller.signal.aborted) return
        if (
          error instanceof NotificationStreamError
          && (error.code === 'EVENT_CURSOR_EXPIRED' || error.code === 'INVALID_EVENT_CURSOR')
        ) {
          localStorage.removeItem(notificationCursorKey())
          await Promise.all([loadNotifications(), loadNotificationHistory()])
        }
        notificationStreamError.value = failureText(error, '实时提醒已断开，正在重连。')
      }
      await new Promise<void>((resolve) => {
        const finish = () => {
          window.clearTimeout(timer)
          controller.signal.removeEventListener('abort', finish)
          resolve()
        }
        const timer = window.setTimeout(finish, 3_000)
        controller.signal.addEventListener('abort', finish, { once: true })
      })
    }
  }

  async function loadNotificationHistory(limit = 50) {
    notificationError.value = null
    try {
      notificationHistory.value = await fetchNotificationHistory({ limit, includeRead: true })
    } catch (error) {
      notificationError.value = failureText(error, '提醒历史不可用')
    }
  }

  async function dismissNotification(notification: DeskNotification) {
    // Toast hide is client-only; this path is explicit read (≠ toast dismiss).
    try {
      await markNotificationRead(notification.notification_id)
      notifications.value = notifications.value.map((item) => item.notification_id === notification.notification_id ? { ...item, status: 'read' } : item)
      notificationHistory.value = notificationHistory.value.map((item) => item.notification_id === notification.notification_id ? { ...item, status: 'read' } : item)
    } catch (error) { notificationError.value = failureText(error, '无法标记提醒') }
  }

  async function applyUiAction(
    actionId: string,
    parameters: Record<string, string> = {},
    actionContextVersion = serverContextVersion.value,
  ): Promise<DeskUiActionReceipt> {
    uiActionError.value = null
    lastUiActionReceipt.value = null
    const allowed = uiActionCatalog.value.some((item) => item.id === actionId)
    if (!allowed) {
      const receipt: DeskUiActionReceipt = {
        receipt: 'rejected',
        action_id: actionId,
        reason: 'action_not_in_catalog',
        owner_id: '',
        parameters,
        applied_at: new Date().toISOString(),
      }
      lastUiActionReceipt.value = receipt
      uiActionError.value = '动作不在交易台白名单'
      return receipt
    }
    const context = serverContextVersion.value
    if (!context) {
      uiActionError.value = '缺少服务端 context_version，无法应用动作'
      const receipt: DeskUiActionReceipt = {
        receipt: 'stale_context', action_id: actionId, reason: 'missing_context',
        owner_id: '', parameters, applied_at: new Date().toISOString(),
      }
      lastUiActionReceipt.value = receipt
      return receipt
    }
    if (actionContextVersion !== context) {
      const receipt: DeskUiActionReceipt = {
        receipt: 'stale_context', action_id: actionId, reason: 'context_version_mismatch',
        owner_id: '', parameters, applied_at: new Date().toISOString(),
      }
      lastUiActionReceipt.value = receipt
      uiActionError.value = '页面上下文已经变化，动作未应用'
      return receipt
    }
    try {
      const receipt = await applyDeskUiAction({
        actionId,
        contextVersion: context,
        parameters,
      })
      lastUiActionReceipt.value = receipt
      if (receipt.receipt === 'applied') {
        if (actionId === 'select_symbol' && parameters.symbol) {
          setSymbol(parameters.symbol)
        } else if (actionId.startsWith('navigate_')) {
          const next = actionId.replace('navigate_', '') as DeskSection
          if (['information', 'portfolio', 'watchlist', 'trading'].includes(next)) {
            setSection(next)
          }
        } else if (actionId === 'refresh_market') {
          await refreshMarket()
        } else if (actionId === 'set_workspace_filter' || actionId === 'set_workspace_sort') {
          workspaceControl.value = {
            section: parameters.section as DeskSection,
            kind: actionId === 'set_workspace_filter' ? 'filter' : 'sort',
            field: parameters.field,
            value: parameters.value,
          }
          if (parameters.section !== section.value) setSection(parameters.section as DeskSection)
        } else if (actionId === 'open_record') {
          openedRecord.value = { type: parameters.record_type, id: parameters.record_id }
        } else if (actionId === 'locate_candidate') {
          candidateLocation.value = {
            symbol: parameters.symbol,
            target: parameters.target as 'watchlist' | 'research',
          }
          setSymbol(parameters.symbol)
          setSection('watchlist')
        } else if (actionId === 'add_to_watchlist') {
          const targetGroupId = selectedWatchlistId.value ?? watchlistGroups.value[0]?.group_id
          if (!targetGroupId) throw new Error('尚无自选分组，请先创建一个分组')
          const normalizedSymbol = parameters.symbol.trim().toUpperCase()
          const alreadyAdded = (watchlistInstruments.value[targetGroupId] ?? [])
            .some((item) => item.instrument_id === normalizedSymbol)
          if (!alreadyAdded) await addToWatchlist(targetGroupId, normalizedSymbol)
          setSymbol(normalizedSymbol)
          setSection('watchlist')
        } else if (actionId === 'fill_trade_draft') {
          tradeDraftPrefill.value = {
            side: parameters.side as 'buy' | 'sell',
            quantity: parameters.quantity,
            priceType: parameters.price_type as 'market' | 'limit',
            limitPrice: parameters.limit_price || null,
          }
          setSection('trading')
        } else if (actionId === 'open_workflow_artifact') {
          requestedArtifactId.value = parameters.artifact_id
        } else if (actionId === 'open_reminder') {
          requestedReminderId.value = parameters.reminder_id
        } else if (actionId === 'open_trade_plan') {
          await loadTradePlan(parameters.plan_id)
          setSection('trading')
        }
      } else if (receipt.receipt === 'stale_context') {
        uiActionError.value = '上下文已过期，请刷新交易台后再试'
        void refreshBootstrap()
      } else {
        uiActionError.value = receipt.reason ?? '动作被拒绝'
      }
      return receipt
    } catch (error) {
      uiActionError.value = failureText(error, 'UI 动作请求失败')
      const receipt: DeskUiActionReceipt = {
        receipt: 'rejected', action_id: actionId, reason: 'request_failed',
        owner_id: '', parameters, applied_at: new Date().toISOString(),
      }
      lastUiActionReceipt.value = receipt
      return receipt
    }
  }

  async function loadSimulationData() {
    loadingSimulation.value = true
    simulationError.value = null
    accountError.value = null
    ordersError.value = null
    fillsError.value = null
    const [accountResult, portfolioResult, orderResult, fillResult] = await Promise.allSettled([
      fetchSimulationAccount(), fetchSimulationPortfolio(), fetchSimulationOrders(), fetchSimulationFills(),
    ])
    if (accountResult.status === 'fulfilled') {
      account.value = accountResult.value
      hasSimulationAccount.value = accountResult.value !== null
      accountState.value = accountResult.value ? 'available' : 'absent'
    } else {
      const message = failureText(accountResult.reason, '模拟账户不可用')
      if (isMissingSimulationAccount(message)) {
        account.value = null
        hasSimulationAccount.value = false
        accountState.value = 'absent'
      } else {
        hasSimulationAccount.value = account.value ? true : null
        accountState.value = 'error'
        accountError.value = message
        simulationError.value = message
      }
    }
    if (portfolioResult.status === 'fulfilled') {
      portfolio.value = portfolioResult.value
    }
    else if (hasSimulationAccount.value) simulationError.value ||= failureText(portfolioResult.reason, '持仓投影不可用')
    if (orderResult.status === 'fulfilled') {
      orders.value = orderResult.value
      activeOrder.value = (
        activeOrder.value
          ? orderResult.value.find(
            (item) => item.order_id === activeOrder.value?.order_id,
          )
          : null
      ) ?? orderResult.value[0] ?? null
    } else if (hasSimulationAccount.value) {
      ordersError.value = failureText(orderResult.reason, '订单记录不可用')
      simulationError.value ||= ordersError.value
    }
    if (fillResult.status === 'fulfilled') {
      fills.value = fillResult.value
    } else if (hasSimulationAccount.value) {
      fillsError.value = failureText(fillResult.reason, '成交记录不可用')
      simulationError.value ||= fillsError.value
    }
    if ([accountResult, portfolioResult, orderResult, fillResult].some((result) => result.status === 'fulfilled')) {
      simulationLoadedAt.value = new Date().toISOString()
    }
    loadingSimulation.value = false
    // 持仓标的变化后立即补一次快照行情，市值/浮盈无需等待下个轮询周期。
    void refreshMarket()
  }

  async function loadWatchlists() {
    loadingWatchlists.value = true
    watchlistError.value = null
    try {
      const groups = await fetchWatchlistGroups()
      watchlistGroups.value = groups
      if (!selectedWatchlistId.value || !groups.some((item) => item.group_id === selectedWatchlistId.value)) selectedWatchlistId.value = groups[0]?.group_id ?? null
      const entries = await Promise.all(groups.map(async (group) => [group.group_id, await fetchWatchlistInstruments(group.group_id)] as const))
      watchlistInstruments.value = Object.fromEntries(entries)
      // 自选标的变更后补一次快照行情，不触发 K 线重拉。
      void refreshMarket()
    } catch (error) { watchlistError.value = failureText(error, '自选分组不可用') }
    finally { loadingWatchlists.value = false }
  }

  async function loadCandidates() {
    loadingCandidates.value = true
    candidateError.value = null
    if (simulationClock.value) {
      candidates.value = null
      loadingCandidates.value = false
      return
    }
    try { candidates.value = await fetchResearchCandidates() }
    catch (error) { candidateError.value = failureText(error, '研究候选不可用') }
    finally { loadingCandidates.value = false }
  }

  async function createAccount(initialCashRmb: string, simulationStartAt: string) {
    simulationError.value = null
    try {
      account.value = await createSimulationAccount(
        initialCashRmb,
        simulationStartAt,
        newIdempotencyKey('simulation-account'),
      )
      hasSimulationAccount.value = true
      accountState.value = 'available'
      await loadSimulationData()
      simulationClock.value = await fetchSimulationClock()
      await refreshMarket({ withBars: true })
      return account.value
    } catch (error) { simulationError.value = failureText(error, '建立模拟账户失败'); throw error }
  }

  async function refreshSimulationClock() {
    if (simulationClockRefreshing) return
    if (!simulationClock.value) return
    simulationClockRefreshing = true
    try {
      simulationClock.value = await fetchSimulationClock()
      const pending = orders.value.filter((order) => (
        order.status === 'accepted' || order.status === 'partially_filled'
      ))
      if (pending.length) {
        await Promise.all(pending.map((order) => reconcileSimulationOrder(
          order.order_id,
          newIdempotencyKey('simulation-clock-reconcile'),
        )))
        await loadSimulationData()
      }
    } catch (error) {
      simulationError.value = failureText(error, '模拟时钟不可用')
    } finally {
      simulationClockRefreshing = false
    }
  }

  async function bootstrapSimulationClock() {
    try {
      const current = await fetchSimulationAccount()
      account.value = current
      hasSimulationAccount.value = current !== null
      accountState.value = current ? 'available' : 'absent'
      simulationClock.value = null
    } catch (error) {
      const message = failureText(error, '模拟账户不可用')
      if (isMissingSimulationAccount(message)) {
        account.value = null
        hasSimulationAccount.value = false
        accountState.value = 'absent'
        simulationClock.value = null
        return
      }
      accountState.value = 'error'
      accountError.value = message
    }
  }

  async function enterHistoricalMode() {
    if (!hasSimulationAccount.value) throw new Error('请先建立模拟账户')
    simulationClock.value = await fetchSimulationClock()
    marketNewsRequestId += 1
    marketNews.value = null
    informationFacts.value = null
    sentimentFacts.value = null
    candidates.value = null
    await Promise.all([refreshMarket({ withBars: true }), loadSimulationData()])
  }

  async function resumeClock() {
    if (!simulationClock.value) throw new Error('模拟时钟不可用')
    simulationClock.value = await resumeSimulationClock(
      simulationClock.value.revision,
      newIdempotencyKey('simulation-clock-resume'),
    )
    await Promise.all([refreshMarket({ withBars: true }), loadSimulationData()])
  }

  async function createDraft(input: SimulationDraftInput) {
    orderError.value = null
    try {
      activeDraft.value = await createSimulationDraft(input, newIdempotencyKey('simulation-draft'))
      appendAgentMessage({
        id: nextMessageId('order-draft'),
        role: 'assistant',
        kind: 'order_draft',
        createdAt: new Date().toISOString(),
        draft: activeDraft.value,
      })
      return activeDraft.value
    }
    catch (error) { orderError.value = failureText(error, '创建订单草稿失败'); throw error }
  }

  function preparePositionSell(instrumentId: string, availableQuantity: string | number) {
    const normalizedSymbol = instrumentId.trim().toUpperCase()
    const normalizedQuantity = String(availableQuantity)
    const numericQuantity = Number(normalizedQuantity)
    if (!normalizedSymbol || !Number.isFinite(numericQuantity) || numericQuantity <= 0) return
    setSymbol(normalizedSymbol)
    tradeDraftPrefill.value = {
      side: 'sell',
      quantity: normalizedQuantity,
      priceType: 'market',
      limitPrice: null,
    }
    setSection('trading')
  }

  function openPositionTrading(instrumentId: string) {
    const normalizedSymbol = instrumentId.trim().toUpperCase()
    if (!normalizedSymbol) return
    setSymbol(normalizedSymbol)
    setSection('trading')
  }

  async function reviewDraft() {
    if (!activeDraft.value) throw new Error('没有可复核的订单草稿')
    orderError.value = null
    try { activeDraft.value = await reviewSimulationDraft(activeDraft.value.draft.draft_id, activeDraft.value.record_revision, newIdempotencyKey('simulation-review')); return activeDraft.value }
    catch (error) { orderError.value = failureText(error, '风控复核失败'); throw error }
  }

  async function acknowledgeSoftRisk(seenReasonHash: string) {
    if (!activeDraft.value) throw new Error('没有可确认的订单草稿')
    orderError.value = null
    try { activeDraft.value = await confirmSimulationSoftRisk(activeDraft.value.draft.draft_id, seenReasonHash, newIdempotencyKey('simulation-soft-risk')); return activeDraft.value }
    catch (error) { orderError.value = failureText(error, '软风险确认失败'); throw error }
  }

  async function confirmDraft(seenSummaryHash: string) {
    if (!activeDraft.value) throw new Error('没有可确认的订单草稿')
    orderError.value = null
    try { activeDraft.value = await confirmSimulationDraft(activeDraft.value.draft.draft_id, activeDraft.value.record_revision, seenSummaryHash, newIdempotencyKey('simulation-confirm')); return activeDraft.value }
    catch (error) { orderError.value = failureText(error, '订单确认失败'); throw error }
  }

  async function submitDraft() {
    if (!activeDraft.value) throw new Error('没有可提交的订单草稿')
    orderError.value = null
    try {
      activeOrder.value = await submitSimulationDraft(
        activeDraft.value.draft.draft_id,
        newIdempotencyKey('simulation-submit'),
      )
      appendAgentMessage({
        id: nextMessageId('order-receipt'),
        role: 'assistant',
        kind: 'order_receipt',
        createdAt: new Date().toISOString(),
        order: activeOrder.value,
      })
      await loadSimulationData()
      return activeOrder.value
    } catch (error) { orderError.value = failureText(error, '提交模拟订单失败'); throw error }
  }

  async function submitMarketOrder(input: {
    accountId: string
    instrumentId: string
    side: 'buy' | 'sell'
    quantity: string
    decisionContext: TradeDecisionContextInput
  }) {
    orderError.value = null
    try {
      activeOrder.value = await submitSimulationMarketOrder({
        account_id: input.accountId,
        instrument_id: input.instrumentId,
        side: input.side,
        quantity: input.quantity,
        market_mode: simulationClock.value ? 'historical' : 'live',
        decision_context: input.decisionContext,
      }, newIdempotencyKey('simulation-market-order'))
      await loadSimulationData()
      return activeOrder.value
    } catch (error) {
      orderError.value = failureText(error, '模拟交易失败')
      throw error
    }
  }

  async function reconcileOrder() {
    if (!activeOrder.value) throw new Error('没有可撮合的模拟订单')
    orderError.value = null
    try {
      activeOrder.value = await reconcileSimulationOrder(
        activeOrder.value.order_id,
        newIdempotencyKey('simulation-reconcile'),
      )
      await loadSimulationData()
      return activeOrder.value
    } catch (error) {
      orderError.value = failureText(error, '模拟订单撮合失败')
      throw error
    }
  }

  async function createWatchlist(name: string, description: string | null) {
    watchlistError.value = null
    try {
      const group = await createWatchlistGroup({ name, description }, newIdempotencyKey('watchlist-create'))
      watchlistGroups.value = [...watchlistGroups.value, group]
      watchlistInstruments.value = { ...watchlistInstruments.value, [group.group_id]: [] }
      selectedWatchlistId.value = group.group_id
      return group
    } catch (error) { watchlistError.value = failureText(error, '创建自选分组失败'); throw error }
  }

  async function renameWatchlist(group: WatchlistGroup, name: string, description: string | null) {
    watchlistError.value = null
    try {
      const updated = await updateWatchlistGroup(group.group_id, { name, description, revision: group.revision }, newIdempotencyKey('watchlist-update'))
      watchlistGroups.value = watchlistGroups.value.map((item) => item.group_id === updated.group_id ? updated : item)
      return updated
    } catch (error) { watchlistError.value = failureText(error, '更新自选分组失败'); throw error }
  }

  async function removeWatchlist(group: WatchlistGroup) {
    watchlistError.value = null
    try {
      await deleteWatchlistGroup(group.group_id, group.revision, newIdempotencyKey('watchlist-delete'))
      watchlistGroups.value = watchlistGroups.value.filter((item) => item.group_id !== group.group_id)
      const { [group.group_id]: _removed, ...remaining } = watchlistInstruments.value
      watchlistInstruments.value = remaining
      if (selectedWatchlistId.value === group.group_id) selectedWatchlistId.value = watchlistGroups.value[0]?.group_id ?? null
    } catch (error) { watchlistError.value = failureText(error, '删除自选分组失败'); throw error }
  }

  async function addToWatchlist(groupId: string, instrumentId: string) {
    watchlistError.value = null
    try {
      const instrument = await addWatchlistInstrument(groupId, instrumentId, newIdempotencyKey('watchlist-add'))
      watchlistInstruments.value = { ...watchlistInstruments.value, [groupId]: [...(watchlistInstruments.value[groupId] ?? []), instrument] }
      void refreshMarket()
      return instrument
    } catch (error) { watchlistError.value = failureText(error, '添加自选标的失败'); throw error }
  }

  async function removeFromWatchlist(groupId: string, instrumentId: string) {
    watchlistError.value = null
    try {
      await removeWatchlistInstrument(groupId, instrumentId, newIdempotencyKey('watchlist-remove'))
      watchlistInstruments.value = { ...watchlistInstruments.value, [groupId]: (watchlistInstruments.value[groupId] ?? []).filter((item) => item.instrument_id !== instrumentId) }
      void refreshMarket()
    } catch (error) { watchlistError.value = failureText(error, '移除自选标的失败'); throw error }
  }

  async function ignoreCandidate(instrumentId: string, reason: 'not_now' | 'already_covered' | 'disagree' | 'data_error', note: string | null = null) {
    candidateError.value = null
    try { await ignoreResearchCandidate(instrumentId, reason, note, newIdempotencyKey('candidate-ignore')); await loadCandidates() }
    catch (error) { candidateError.value = failureText(error, '忽略研究候选失败'); throw error }
  }

  async function restoreCandidate(instrumentId: string) {
    candidateError.value = null
    try { await unignoreResearchCandidate(instrumentId, newIdempotencyKey('candidate-restore')); await loadCandidates() }
    catch (error) { candidateError.value = failureText(error, '恢复研究候选失败'); throw error }
  }

  async function startCandidateTradePlan(instrumentId: string) {
    tradePlanError.value = null
    try { activeTradePlan.value = await createTradePlanFromCandidate(instrumentId, newIdempotencyKey('plan-candidate')); return activeTradePlan.value }
    catch (error) { tradePlanError.value = failureText(error, '创建候选交易计划失败'); throw error }
  }

  async function startPortfolioDeviationTradePlan() {
    tradePlanError.value = null
    try { activeTradePlan.value = await createTradePlanFromPortfolioDeviation(newIdempotencyKey('plan-portfolio')); return activeTradePlan.value }
    catch (error) { tradePlanError.value = failureText(error, '创建持仓偏离计划失败'); throw error }
  }

  async function loadTradePlan(planId: string) {
    tradePlanError.value = null
    try { activeTradePlan.value = await fetchTradePlan(planId); return activeTradePlan.value }
    catch (error) { tradePlanError.value = failureText(error, '读取交易计划失败'); throw error }
  }

  async function reviseActiveTradePlan(actions: TradePlanActionRevision[]) {
    if (!activeTradePlan.value) throw new Error('没有可修订的交易计划')
    tradePlanError.value = null
    try {
      activeTradePlan.value = await reviseTradePlan(activeTradePlan.value.object.plan_id, activeTradePlan.value.object.revision, actions, newIdempotencyKey('plan-revise'))
      return activeTradePlan.value
    } catch (error) { tradePlanError.value = failureText(error, '修订交易计划失败'); throw error }
  }

  async function confirmActiveTradePlan() {
    if (!activeTradePlan.value) throw new Error('没有可确认的交易计划')
    tradePlanError.value = null
    try {
      activeTradePlan.value = await confirmTradePlan(activeTradePlan.value.object.plan_id, activeTradePlan.value.object.revision, newIdempotencyKey('plan-confirm'))
      return activeTradePlan.value
    } catch (error) { tradePlanError.value = failureText(error, '确认交易计划失败'); throw error }
  }

  async function prefillTradeFormFromCompletedStrategy(
    run: DeskWorkflowRun,
    progress: DeskWorkflowProgress,
  ) {
    if (
      run.workflow_key !== 'trade_plan_generation'
      || run.scope?.requested_ui_action !== 'fill_trade_draft'
      || appliedTradePlanPrefills.has(run.run_id)
    ) return
    const planReference = [
      ...(progress.completed_node_artifacts ?? []),
      ...(run.completed_node_artifacts ?? []),
    ].find((item) => item.object_type === 'trade_plan')
    if (!planReference) {
      tradePlanError.value = '交易策略已完成，但没有返回可填写的版本化交易计划。'
      return
    }
    let plan: TradePlan
    try {
      plan = await loadTradePlan(planReference.object_id)
    } catch {
      return
    }
    const actions = plan.object.actions.filter((item) => item.included)
    if (actions.length !== 1) {
      tradePlanError.value = '交易策略包含多个交易动作，不能自动映射到单张交易单。'
      return
    }
    const action = actions[0]
    if (action.side !== 'buy' && action.side !== 'sell') {
      tradePlanError.value = '交易计划方向无法填写到当前交易单。'
      return
    }
    if ((action.order_type ?? 'market') !== 'market') {
      tradePlanError.value = '交易计划使用限价单，当前模拟交易表单仅支持市价单，未自动填写。'
      return
    }
    appliedTradePlanPrefills.add(run.run_id)
    setSymbol(action.instrument_id)
    tradeDraftPrefill.value = {
      side: action.side,
      quantity: action.quantity ?? '',
      priceType: 'market',
      limitPrice: null,
      source: 'agent_strategy',
      planId: plan.object.plan_id,
    }
    setSection('trading')
    if (!agentMessages.value.some((item) => item.id === `strategy-prefill-${run.run_id}`)) {
      appendAgentMessage({
        id: `strategy-prefill-${run.run_id}`,
        role: 'assistant',
        kind: 'text',
        createdAt: new Date().toISOString(),
        text: action.quantity
          ? '已根据版本化交易计划填写模拟交易单，请核对真实行情后手动提交。'
          : '已根据版本化交易计划填写标的与方向；计划未确定数量，请补充数量并手动提交。',
        status: 'complete',
      })
    }
  }

  async function runWorkflow(intent: string): Promise<'started' | 'active_conflict' | 'failed'> {
    const normalizedIntent = intent.trim()
    if (!normalizedIntent) return 'failed'
    if (workflowActive.value) {
      workflowError.value = '当前任务仍在运行，请等待终态后再创建新任务。'
      return 'active_conflict'
    }
    if (!serverContextVersion.value) {
      workflowError.value = '缺少服务端 context_version，无法创建可审计工作流。'
      return 'failed'
    }
    if (!isDeskCapabilityEnabled(deskCapabilities.value, 'workflow_create')) {
      workflowError.value = '服务端未确认工作流创建能力（需实际连接 workflow runtime）。'
      return 'failed'
    }
    if (!isDeskCapabilityEnabled(deskCapabilities.value, 'workflow_worker')) {
      workflowError.value = '服务端未确认 Workflow Worker 正在运行，当前不能执行新任务。'
      return 'failed'
    }
    workflowError.value = null
    workflowEvidenceError.value = null
    workflowSubmitting.value = true
    activeWorkflowEvidence.value = null
    activeWorkflowProgress.value = null
    try {
      activeWorkflow.value = await createWorkflow({
        intent: normalizedIntent,
        section: section.value,
        symbol: symbol.value,
        contextVersion: serverContextVersion.value,
        idempotencyKey: newIdempotencyKey('desk'),
        orderDraft: activeDraft.value
          ? {
              id: activeDraft.value.draft.draft_id,
              version: String(activeDraft.value.draft.revision),
            }
          : undefined,
      })
      workflowIntent.value = normalizedIntent
      await refreshWorkflow()
      if (activeWorkflow.value && ACTIVE_WORKFLOW_STATUSES.has(activeWorkflow.value.status)) {
        startWorkflowPolling()
      }
      return 'started'
    } catch (error) {
      if (
        error instanceof DeskApiError
        && error.code === 'WORKFLOW_ALREADY_ACTIVE'
        && error.activeRunId
      ) {
        try {
          activeWorkflow.value = await fetchWorkflow(error.activeRunId)
          workflowIntent.value = activeWorkflow.value.request_intent?.trim() || null
          await refreshWorkflow()
          if (ACTIVE_WORKFLOW_STATUSES.has(activeWorkflow.value.status)) {
            startWorkflowPolling()
          }
          return 'active_conflict'
        } catch (recoveryError) {
          workflowError.value = failureText(recoveryError, '活动工作流恢复失败')
          activeWorkflow.value = null
          workflowIntent.value = null
          return 'failed'
        }
      }
      workflowError.value = failureText(error, '工作流请求失败')
      activeWorkflow.value = null
      workflowIntent.value = null
      return 'failed'
    } finally {
      workflowSubmitting.value = false
    }
  }

  async function submitAgentIntent(intent: string) {
    const normalizedIntent = intent.trim()
    if (!normalizedIntent) return
    if (!serverContextVersion.value) {
      workflowError.value = '缺少服务端 context_version，无法判断执行方式。'
      return
    }

    const createdAt = new Date().toISOString()
    const pendingId = nextMessageId('assistant')
    appendAgentMessage({ id: nextMessageId('user'), role: 'user', kind: 'text', createdAt, text: normalizedIntent })
    appendAgentMessage({ id: pendingId, role: 'assistant', kind: 'text', createdAt, text: '正在生成回复…', status: 'pending' })
    quickCommandRequestId += 1
    serverQuickCommands.value = []
    quickCommandsError.value = null
    quickCommandsLoading.value = true
    agentRequestCount.value += 1
    agentDecision.value = null
    directReply.value = null
    directAnswerError.value = null
    workflowError.value = null
    try {
      let streamedText = ''
      const streamedChunks: string[] = []
      const decision = await streamDeskAgentDecision({
        message: normalizedIntent,
        section: section.value,
        symbol: symbol.value,
        contextVersion: serverContextVersion.value,
        activeWorkflow: workflowActive.value,
        orderDraft: activeDraft.value
          ? {
              id: activeDraft.value.draft.draft_id,
              version: String(activeDraft.value.draft.revision),
            }
          : undefined,
      }, (delta) => {
        streamedText += delta
        streamedChunks.push(delta)
        replaceAgentMessage(pendingId, {
          id: pendingId,
          role: 'assistant',
          kind: 'text',
          createdAt,
          text: streamedText,
          status: 'pending',
          chunks: [...streamedChunks],
        })
      })
      agentDecision.value = decision
      const actionReceipts = await Promise.all(
        decision.ui_actions.map((action) => applyUiAction(
          action.action_id,
          action.parameters,
          action.context_version,
        )),
      )
      const failedAction = actionReceipts.find((receipt) => receipt.receipt !== 'applied')
      if (failedAction) {
        throw new Error(
          failedAction.receipt === 'stale_context'
            ? '页面上下文已经变化，Agent 动作未执行'
            : `Agent 动作未执行：${failedAction.reason ?? '服务端拒绝'}`,
        )
      }
      if (decision.mode === 'answer') {
        if (!decision.answer_text?.trim()) {
          throw new Error('Agent 未返回可展示的直接回复')
        }
        directReply.value = decision.answer_text.trim()
        replaceAgentMessage(pendingId, { id: pendingId, role: 'assistant', kind: 'text', createdAt, text: directReply.value, status: 'complete' })
        quickCommandsLoading.value = false
        await refreshQuickCommands('after_answer', decision.decision_id)
        return
      }
      if (decision.mode === 'workflow' && workflowActive.value) {
        queuedWorkflowIntents.value = [
          ...queuedWorkflowIntents.value,
          { id: makeRequestId(), intent: normalizedIntent, createdAt },
        ]
        persistWorkflowQueue()
        replaceAgentMessage(pendingId, {
          id: pendingId,
          role: 'assistant',
          kind: 'text',
          createdAt,
          text: '这需要正式工作流，已加入待办；当前任务完成后会自动开始。',
          status: 'complete',
        })
        quickCommandsLoading.value = false
        return
      }
      if (!decision.can_start) {
        workflowError.value = decision.message
        replaceAgentMessage(pendingId, { id: pendingId, role: 'assistant', kind: 'error', createdAt, text: decision.message })
        quickCommandsLoading.value = false
        return
      }
      replaceAgentMessage(pendingId, { id: pendingId, role: 'assistant', kind: 'text', createdAt, text: '正在创建研究任务…', status: 'complete' })
    } catch (error) {
      directAnswerError.value = failureText(error, 'Agent 执行方式判断失败')
      replaceAgentMessage(pendingId, { id: pendingId, role: 'assistant', kind: 'error', createdAt, text: directAnswerError.value })
      quickCommandsLoading.value = false
      return
    } finally {
      agentRequestCount.value = Math.max(0, agentRequestCount.value - 1)
    }
    const startResult = await runWorkflow(normalizedIntent)
    if (startResult === 'active_conflict') {
      queuedWorkflowIntents.value = [
        ...queuedWorkflowIntents.value,
        { id: makeRequestId(), intent: normalizedIntent, createdAt },
      ]
      persistWorkflowQueue()
      replaceAgentMessage(pendingId, {
        id: pendingId,
        role: 'assistant',
        kind: 'text',
        createdAt,
        text: '服务端已有活动任务，本次正式任务已加入待办；当前任务完成后会自动开始。',
        status: 'complete',
      })
      quickCommandsLoading.value = false
      return
    }
    if (startResult === 'failed' || !activeWorkflow.value) {
      quickCommandsLoading.value = false
      replaceAgentMessage(pendingId, {
        id: pendingId,
        role: 'assistant',
        kind: 'error',
        createdAt,
        text: workflowError.value || '研究任务创建失败',
      })
      return
    }
    replaceAgentMessage(pendingId, {
      id: pendingId,
      role: 'assistant',
      kind: 'text',
      createdAt,
      text: '研究任务已创建，以下状态来自服务端。',
      status: 'complete',
    })
    appendAgentMessage({
      id: `workflow-${activeWorkflow.value.run_id}`,
      role: 'assistant',
      kind: 'workflow',
      createdAt: new Date().toISOString(),
      runId: activeWorkflow.value.run_id,
      intent: normalizedIntent,
      status: activeWorkflow.value.status,
    })
  }

  async function refreshWorkflow() {
    if (!activeWorkflow.value) return
    const runId = activeWorkflow.value.run_id
    workflowError.value = null
    try {
      const [run, progress] = await Promise.all([
        fetchWorkflow(runId),
        fetchWorkflowProgress(runId),
      ])
      if (activeWorkflow.value?.run_id !== runId) return
      await applyWorkflowSnapshot(run, progress)
    } catch (error) {
      workflowError.value = failureText(error, '工作流状态不可用')
    }
  }

  async function applyWorkflowSnapshot(run: DeskWorkflowRun, progress: DeskWorkflowProgress) {
    const runId = run.run_id
    activeWorkflow.value = run
    activeWorkflowProgress.value = progress
    const workflowMessage = agentMessages.value.find((item) => item.kind === 'workflow' && item.runId === runId)
    if (workflowMessage?.kind === 'workflow') {
      replaceAgentMessage(workflowMessage.id, { ...workflowMessage, status: run.status })
    }
    if (ACTIVE_WORKFLOW_STATUSES.has(run.status)) return
    stopWorkflowPolling()
    if (run.status === 'completed' && run.final_artifact) {
      await Promise.all([
        loadWorkflowEvidence(run.final_artifact),
        ...(run.workflow_key === 'research_candidates' ? [loadCandidates()] : []),
      ])
      await prefillTradeFormFromCompletedStrategy(run, progress)
      if (activeWorkflowEvidence.value && !agentMessages.value.some((item) => item.kind === 'research_report' && item.runId === runId)) {
        appendAgentMessage({
          id: `report-${runId}`,
          role: 'assistant',
          kind: 'research_report',
          createdAt: new Date().toISOString(),
          runId,
          evidence: activeWorkflowEvidence.value,
        })
      }
      quickCommandsLoading.value = false
      void refreshQuickCommands('after_workflow', runId)
      void startNextQueuedWorkflow()
      return
    }
    activeWorkflowEvidence.value = null
    quickCommandsLoading.value = false
    serverQuickCommands.value = []
    quickCommandsError.value = null
    void startNextQueuedWorkflow()
  }

  async function startNextQueuedWorkflow() {
    if (workflowActive.value || !queuedWorkflowIntents.value.length) return
    const [next, ...remaining] = queuedWorkflowIntents.value
    queuedWorkflowIntents.value = remaining
    persistWorkflowQueue()
    const startResult = await runWorkflow(next.intent)
    if (
      startResult !== 'started'
      || !activeWorkflow.value
      || !ACTIVE_WORKFLOW_STATUSES.has(activeWorkflow.value.status)
    ) {
      queuedWorkflowIntents.value = [next, ...queuedWorkflowIntents.value]
      persistWorkflowQueue()
      return
    }
    appendAgentMessage({
      id: `workflow-${activeWorkflow.value.run_id}`,
      role: 'assistant',
      kind: 'workflow',
      createdAt: new Date().toISOString(),
      runId: activeWorkflow.value.run_id,
      intent: next.intent,
      status: activeWorkflow.value.status,
    })
  }

  function removeQueuedWorkflow(id: string) {
    queuedWorkflowIntents.value = queuedWorkflowIntents.value.filter((item) => item.id !== id)
    persistWorkflowQueue()
  }

  async function loadWorkflowEvidence(reference: { object_type: string; object_id: string; version: string }) {
    workflowEvidenceError.value = null
    try {
      activeWorkflowEvidence.value = await fetchWorkflowEvidence(reference)
    } catch (error) {
      activeWorkflowEvidence.value = null
      workflowEvidenceError.value = failureText(error, '工作流产物不可用')
    }
  }

  async function restoreActiveWorkflow() {
    try {
      const page = await fetchWorkflowHistory({ limit: 20 })
      workflowHistory.value = page.items
      workflowHistoryCursor.value = page.next_cursor
      activeWorkflow.value = page.items.find((item) => ACTIVE_WORKFLOW_STATUSES.has(item.status)) ?? null
      workflowIntent.value = activeWorkflow.value?.request_intent?.trim() || null
      if (!activeWorkflow.value) {
        return
      }
      await refreshWorkflow()
      if (activeWorkflow.value && ACTIVE_WORKFLOW_STATUSES.has(activeWorkflow.value.status)) {
        startWorkflowPolling()
      }
    } catch (error) {
      activeWorkflow.value = null
      activeWorkflowProgress.value = null
      activeWorkflowEvidence.value = null
      workflowIntent.value = null
      agentDecision.value = null
      if (error instanceof Error && !/not found|404/i.test(error.message)) {
        workflowError.value = failureText(error, '无法恢复上次工作流')
      }
    }
  }

  async function loadWorkflowHistory(reset = true, status: DeskWorkflowRun['status'] | '' = '') {
    workflowHistoryLoading.value = true
    workflowHistoryError.value = null
    try {
      const page = await fetchWorkflowHistory({
        cursor: reset ? null : workflowHistoryCursor.value,
        limit: 20,
        status,
      })
      workflowHistory.value = reset ? page.items : [...workflowHistory.value, ...page.items]
      workflowHistoryCursor.value = page.next_cursor
    } catch (error) {
      workflowHistoryError.value = failureText(error, '任务历史不可用')
    } finally {
      workflowHistoryLoading.value = false
    }
  }

  async function openHistoricalWorkflow(run: DeskWorkflowRun | string) {
    const runId = typeof run === 'string' ? run : run.run_id
    workflowHistoryLoading.value = true
    workflowHistoryError.value = null
    try {
      const [workflow, progress] = await Promise.all([
        fetchWorkflow(runId),
        fetchWorkflowProgress(runId),
      ])
      selectedHistoricalWorkflow.value = workflow
      selectedHistoricalProgress.value = progress
      selectedHistoricalEvidence.value = workflow.final_artifact
        ? await fetchWorkflowEvidence(workflow.final_artifact)
        : null
    } catch (error) {
      selectedHistoricalWorkflow.value = null
      selectedHistoricalProgress.value = null
      selectedHistoricalEvidence.value = null
      workflowHistoryError.value = failureText(error, '任务运行信息不可用')
    } finally {
      workflowHistoryLoading.value = false
    }
  }

  function closeHistoricalWorkflow() {
    selectedHistoricalWorkflow.value = null
    selectedHistoricalProgress.value = null
    selectedHistoricalEvidence.value = null
  }

  async function cancelActiveWorkflow() {
    if (!activeWorkflow.value) return
    workflowSubmitting.value = true
    workflowError.value = null
    try {
      activeWorkflow.value = await cancelWorkflow(
        activeWorkflow.value.run_id,
        newIdempotencyKey('workflow-cancel'),
      )
      await refreshWorkflow()
      await loadWorkflowHistory()
    } catch (error) {
      workflowError.value = failureText(error, '取消任务失败')
    } finally {
      workflowSubmitting.value = false
    }
  }

  async function retryHistoricalWorkflow(mode: 'full' | 'resume_failed') {
    if (!selectedHistoricalWorkflow.value) return
    workflowSubmitting.value = true
    workflowError.value = null
    try {
      activeWorkflow.value = await retryWorkflow(
        selectedHistoricalWorkflow.value.run_id,
        mode,
        newIdempotencyKey(`workflow-retry-${mode}`),
      )
      workflowIntent.value = activeWorkflow.value.request_intent ?? selectedHistoricalWorkflow.value.request_intent ?? null
      closeHistoricalWorkflow()
      await refreshWorkflow()
      startWorkflowPolling()
      await loadWorkflowHistory()
    } catch (error) {
      workflowHistoryError.value = failureText(error, '重试任务失败')
    } finally {
      workflowSubmitting.value = false
    }
  }

  function startWorkflowPolling() {
    stopWorkflowPolling()
    const controller = new AbortController()
    workflowObserver = controller
    void observeWorkflow(controller)
  }

  function stopWorkflowPolling() {
    workflowObserver?.abort()
    workflowObserver = null
  }

  async function observeWorkflow(controller: AbortController) {
    while (
      !controller.signal.aborted
      && !document.hidden
      && activeWorkflow.value
      && ACTIVE_WORKFLOW_STATUSES.has(activeWorkflow.value.status)
    ) {
      const runId = activeWorkflow.value.run_id
      const revision = activeWorkflowProgress.value?.revision ?? activeWorkflow.value.revision
      try {
        const progress = await fetchWorkflowProgress(runId, {
          afterRevision: revision,
          waitSeconds: 20,
          signal: controller.signal,
        })
        if (controller.signal.aborted || activeWorkflow.value?.run_id !== runId) return
        const run = await fetchWorkflow(runId)
        if (controller.signal.aborted || activeWorkflow.value?.run_id !== runId) return
        await applyWorkflowSnapshot(run, progress)
      } catch (error) {
        if (controller.signal.aborted) return
        workflowError.value = failureText(error, '工作流状态不可用')
        return
      }
    }
  }

  async function refreshBootstrap() {
    const requestId = ++bootstrapRequestId
    resetBootstrapFacts()
    bootstrapStatus.value = 'loading'
    bootstrapError.value = null
    const requestedSection = section.value
    const requestedSymbol = symbol.value
    try {
      const bootstrap = await fetchDeskBootstrap({
        section: requestedSection,
        symbol: requestedSymbol,
      })
      if (
        requestId !== bootstrapRequestId
        || section.value !== requestedSection
        || symbol.value !== requestedSymbol
      ) return
      applyBootstrap(bootstrap)
      void refreshQuickCommands('initial', null, true)
    } catch (error) {
      if (requestId !== bootstrapRequestId) return
      clearBootstrapState(failureText(error, '交易台引导状态不可用'))
    }
  }

  function startPolling() {
    stopPolling()
    pollTimer = setInterval(() => { if (!document.hidden) void refreshMarket() }, POLL_INTERVAL_MS)
    simulationClockTimer = setInterval(() => {
      if (!document.hidden && simulationClock.value) void refreshSimulationClock()
    }, 1_000)
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer)
    if (simulationClockTimer) clearInterval(simulationClockTimer)
    pollTimer = null
    simulationClockTimer = null
  }
  function onVisibilityChange() {
    if (document.hidden) {
      stopWorkflowPolling()
      stopNotificationStream()
      return
    }
    void refreshMarket()
    void refreshSimulationClock()
    void Promise.all([loadNotifications(), loadNotificationHistory()]).finally(
      startNotificationStream,
    )
    if (activeWorkflow.value && ACTIVE_WORKFLOW_STATUSES.has(activeWorkflow.value.status)) {
      void refreshWorkflow().finally(() => {
        if (activeWorkflow.value && ACTIVE_WORKFLOW_STATUSES.has(activeWorkflow.value.status)) {
          startWorkflowPolling()
        }
      })
    }
  }

  async function initialize() {
    sessionStorage.removeItem('finance-god:active-workflow:v1')
    restoreAgentMessages()
    restoreWorkflowQueue()
    // Shell state only after a successful bootstrap response — never declare capabilities locally.
    await refreshBootstrap()
    await bootstrapSimulationClock()
    await Promise.all([
      refreshMarket({ withBars: true }),
      loadProfile(),
      loadNotifications(),
      loadMarketFacts(),
      loadMarketNews(),
    ])
    // Load section-specific data based on the restored active workspace.
    if (section.value === 'review') void loadReviewWorkspace()
    else if (section.value === 'portfolio' || section.value === 'trading') void loadSimulationData()
    else if (section.value === 'watchlist') void Promise.all([loadWatchlists(), loadCandidates()])
    startNotificationStream()
    await restoreActiveWorkflow()
    // 如果没有活跃工作流但队列中有待执行任务，尝试启动下一个
    if (!workflowActive.value && queuedWorkflowIntents.value.length) {
      void startNextQueuedWorkflow()
    }
    startPolling()
    document.addEventListener('visibilitychange', onVisibilityChange)
  }

  function dispose() {
    stopPolling()
    stopWorkflowPolling()
    stopNotificationStream()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
  onScopeDispose(dispose)

  return {
    section, symbol, quotes, quoteSymbols, profile, informationFacts, sentimentFacts, marketNews, bars, notifications,
    account, accountState, simulationClock, portfolio, orders, fills, tradeEpisodes, selectedTradeEpisode, tradeEpisodeDecisions, tradeEpisodeReview, agentLearningSummary, watchlistGroups, watchlistInstruments, selectedWatchlistId, selectedWatchlist,
    selectedWatchlistInstruments, candidates, activeDraft, activeOrder, activeTradePlan, hasSimulationAccount,
    marketError, profileError, informationFactsError, sentimentFactsError, marketNewsError, marketFactsNotice, minuteBarsSupported, indexSwitchNotice, barsError, notificationError, notificationStreamError, simulationError,
    accountError, ordersError, fillsError, marketLoadedAt, simulationLoadedAt, watchlistError, candidateError,
    orderError, tradePlanError,
    loadingMarket, loadingSimulation, loadingWatchlists, loadingCandidates, tradeReviewLoading, tradeReviewError, agentLearningLoading, agentLearningError,
    activeWorkflow, activeWorkflowProgress, activeWorkflowEvidence, workflowIntent, agentMessages, queuedWorkflowIntents,
    workflowHistory, workflowHistoryCursor, workflowHistoryLoading, workflowHistoryError,
    selectedHistoricalWorkflow, selectedHistoricalProgress, selectedHistoricalEvidence,
    agentDecision, agentPreview, agentPreviewLoading, agentPreviewError, directReply, directAnswerError, agentSubmitting,
    workflowError, workflowEvidenceError, workflowSubmitting, workflowActive,
    contextVersion, serverContextVersion, serverQuickCommands, quickCommandsError, quickCommandsLoading, uiActionCatalog,
    deskCapabilities, profileProjection, bootstrapStatus, bootstrapError, notificationHistory, uiActionError, lastUiActionReceipt,
    workspaceControl, openedRecord, candidateLocation, tradeDraftPrefill, requestedArtifactId, requestedReminderId,
    selectedQuote, unreadCount, profileSummary, quickCommands,
    setSection, setSymbol, setBarsFrequency, refreshMarket, refreshOverviewWorkspace, ensureQuote, ensureQuoteSymbol, refreshPortfolioWorkspace, refreshTradingWorkspace, refreshSimulationClock, enterHistoricalMode, resumeClock,
    loadProfile, loadMarketFacts, loadMarketNews, loadNotifications, loadNotificationHistory,
    dismissNotification, applyUiAction,
    loadSimulationData, loadTradeEpisodes, loadAgentLearningSummary, loadReviewWorkspace, selectTradeEpisode, retrySelectedTradeReview, loadWatchlists, loadCandidates, createAccount, createDraft, openPositionTrading, preparePositionSell, reviewDraft,
    acknowledgeSoftRisk, confirmDraft, submitDraft, submitMarketOrder, reconcileOrder, createWatchlist, renameWatchlist, removeWatchlist,
    addToWatchlist, removeFromWatchlist, ignoreCandidate, restoreCandidate, startCandidateTradePlan,
    startPortfolioDeviationTradePlan, loadTradePlan, reviseActiveTradePlan, confirmActiveTradePlan,
    contextualActions, executeQuickAction, applyReportAction,
    guidedTrade, startGuidedTrade, advanceGuidedTrade, confirmGuidedTrade, cancelGuidedTrade,
    runWorkflow, submitAgentIntent, previewAgentIntent, appendAgentMessage, removeQueuedWorkflow, refreshWorkflow, refreshBootstrap, refreshQuickCommands, rerollQuickCommands,
    loadWorkflowHistory, openHistoricalWorkflow, closeHistoricalWorkflow, cancelActiveWorkflow, retryHistoricalWorkflow,
    initialize, dispose,
  }
})
