import { computed, onScopeDispose, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  addWatchlistInstrument,
  confirmSimulationDraft,
  confirmSimulationSoftRisk,
  confirmTradePlan,
  createSimulationAccount,
  createSimulationDraft,
  createTradePlanFromCandidate,
  createTradePlanFromPortfolioDeviation,
  createWatchlistGroup,
  createWorkflow,
  deleteWatchlistGroup,
  fetchInformationFacts,
  fetchMarketOverview,
  fetchNotifications,
  fetchProfile,
  fetchResearchCandidates,
  fetchSentimentFacts,
  fetchSimulationAccount,
  fetchSimulationFills,
  fetchSimulationOrders,
  fetchSimulationPortfolio,
  fetchTradePlan,
  fetchWatchlistGroups,
  fetchWatchlistInstruments,
  fetchWorkflow,
  ignoreResearchCandidate,
  markNotificationRead,
  removeWatchlistInstrument,
  reviewSimulationDraft,
  reviseTradePlan,
  submitSimulationDraft,
  unignoreResearchCandidate,
  updateWatchlistGroup,
  type DeskFactBatch,
  type DeskNotification,
  type DeskQuote,
  type DeskWorkflowRun,
  type ResearchCandidateResponse,
  type SimulationAccount,
  type SimulationDraft,
  type SimulationDraftInput,
  type SimulationFill,
  type SimulationOrder,
  type SimulationPortfolio,
  type TradePlan,
  type TradePlanActionRevision,
  type WatchlistGroup,
  type WatchlistInstrument,
} from '@/services/tradingDesk'
import type { ProfileWithRecommendations } from '@/types/api'

export type DeskSection = 'information' | 'portfolio' | 'watchlist' | 'trading'
export type AgentWorkflow = 'market_context' | 'company_research' | 'portfolio_stress' | 'trade_plan_generation' | 'strategy_validation' | 'event_impact'

const BASELINE_SYMBOLS = ['000001.SZ', '600519.SH', '300750.SZ'] as const
const POLL_INTERVAL_MS = 60_000

function failureText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function newIdempotencyKey(scope: string): string {
  return `${scope}-${crypto.randomUUID()}`
}

export const useTradingDeskStore = defineStore('trading-desk', () => {
  const section = ref<DeskSection>('information')
  const symbol = ref<string>(BASELINE_SYMBOLS[0])
  const quotes = ref<DeskQuote[]>([])
  const profile = ref<ProfileWithRecommendations | null>(null)
  const informationFacts = ref<DeskFactBatch | null>(null)
  const sentimentFacts = ref<DeskFactBatch | null>(null)
  const notifications = ref<DeskNotification[]>([])
  const account = ref<SimulationAccount | null>(null)
  const portfolio = ref<SimulationPortfolio | null>(null)
  const orders = ref<SimulationOrder[]>([])
  const fills = ref<SimulationFill[]>([])
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
  const notificationError = ref<string | null>(null)
  const simulationError = ref<string | null>(null)
  const accountError = ref<string | null>(null)
  const ordersError = ref<string | null>(null)
  const fillsError = ref<string | null>(null)
  const watchlistError = ref<string | null>(null)
  const candidateError = ref<string | null>(null)
  const tradeError = ref<string | null>(null)
  const loadingMarket = ref(false)
  const loadingSimulation = ref(false)
  const simulationLoadedAt = ref<string | null>(null)
  const loadingWatchlists = ref(false)
  const loadingCandidates = ref(false)
  const hasSimulationAccount = ref<boolean | null>(null)
  const activeWorkflow = ref<DeskWorkflowRun | null>(null)
  const workflowError = ref<string | null>(null)
  const contextVersion = ref(0)
  let pollTimer: ReturnType<typeof setInterval> | null = null

  const portfolioSymbols = computed(() => portfolio.value?.positions.map((item) => item.instrument_id) ?? [])
  const watchlistSymbols = computed(() => Object.values(watchlistInstruments.value).flat().map((item) => item.instrument_id))
  const quoteSymbols = computed(() => [...new Set([...BASELINE_SYMBOLS, ...portfolioSymbols.value, ...watchlistSymbols.value])])
  const selectedQuote = computed(() => quotes.value.find((item) => item.symbol === symbol.value) ?? null)
  const unreadCount = computed(() => notifications.value.filter((item) => item.status !== 'read').length)
  const profileSummary = computed(() => profile.value?.profile ?? null)
  const selectedWatchlist = computed(() => watchlistGroups.value.find((item) => item.group_id === selectedWatchlistId.value) ?? null)
  const selectedWatchlistInstruments = computed(() => selectedWatchlistId.value ? watchlistInstruments.value[selectedWatchlistId.value] ?? [] : [])
  const quickCommands = computed<readonly [string, string, string]>(() => {
    if (section.value === 'portfolio') return ['分析当前持仓的集中度与回撤风险', '解释持仓标的的最新异动', '为当前标的生成研究任务']
    if (section.value === 'watchlist') return ['分析当前自选标的行情', '比较自选标的的风险', '为当前标的生成研究任务']
    if (section.value === 'trading') return ['帮我制定当前标的交易方案', '检查仿真订单草稿的风险', '解释计划与画像约束是否匹配']
    return profileSummary.value
      ? ['分析当前标的行情', '结合我的画像生成研究候选', '查看当前标的重大行情提醒']
      : ['查看当前标的行情', '开始完成投资画像', '查看当前标的重大行情提醒']
  })

  function setSection(next: DeskSection) {
    section.value = next
    contextVersion.value += 1
    if (next === 'portfolio') void loadSimulationData()
    if (next === 'watchlist') void Promise.all([loadWatchlists(), loadCandidates()])
    if (next === 'trading') void Promise.all([loadSimulationData(), loadOrders()])
  }

  function setSymbol(next: string) {
    symbol.value = next
    contextVersion.value += 1
    void loadMarketFacts()
  }

  async function refreshMarket() {
    loadingMarket.value = true
    marketError.value = null
    try { quotes.value = await fetchMarketOverview(quoteSymbols.value) }
    catch (error) { marketError.value = failureText(error, '真实行情不可用') }
    finally { loadingMarket.value = false }
  }

  async function loadProfile() {
    profileError.value = null
    try { profile.value = await fetchProfile() }
    catch (error) { profileError.value = failureText(error, '画像不可用') }
  }

  async function loadMarketFacts() {
    const requestedSymbol = symbol.value
    informationFactsError.value = null
    sentimentFactsError.value = null
    const [information, sentiment] = await Promise.allSettled([
      fetchInformationFacts(requestedSymbol),
      fetchSentimentFacts(requestedSymbol),
    ])
    if (symbol.value !== requestedSymbol) return
    if (information.status === 'fulfilled') informationFacts.value = information.value
    else informationFactsError.value = failureText(information.reason, '市场资讯不可用')
    if (sentiment.status === 'fulfilled') sentimentFacts.value = sentiment.value
    else sentimentFactsError.value = failureText(sentiment.reason, '市场情绪事实不可用')
  }

  async function loadNotifications() {
    notificationError.value = null
    try { notifications.value = await fetchNotifications() }
    catch (error) { notificationError.value = failureText(error, '提醒不可用') }
  }

  async function dismissNotification(notification: DeskNotification) {
    try {
      await markNotificationRead(notification.notification_id)
      notifications.value = notifications.value.map((item) => item.notification_id === notification.notification_id ? { ...item, status: 'read' } : item)
    } catch (error) { notificationError.value = failureText(error, '无法标记提醒') }
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
    } else {
      account.value = null
      hasSimulationAccount.value = false
      const message = failureText(accountResult.reason, '仿真账户不可用')
      if (!/not found|账户不存在|simulation account/i.test(message)) {
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
  }

  async function loadOrders() {
    ordersError.value = null
    try { orders.value = await fetchSimulationOrders() }
    catch (error) {
      ordersError.value = failureText(error, '订单记录不可用')
      simulationError.value = ordersError.value
    }
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
      void refreshMarket()
    } catch (error) { watchlistError.value = failureText(error, '自选分组不可用') }
    finally { loadingWatchlists.value = false }
  }

  async function loadCandidates() {
    loadingCandidates.value = true
    candidateError.value = null
    try { candidates.value = await fetchResearchCandidates() }
    catch (error) { candidateError.value = failureText(error, '研究候选不可用') }
    finally { loadingCandidates.value = false }
  }

  async function createAccount(initialCashRmb: string) {
    simulationError.value = null
    try {
      account.value = await createSimulationAccount(initialCashRmb, newIdempotencyKey('simulation-account'))
      hasSimulationAccount.value = true
      await loadSimulationData()
      return account.value
    } catch (error) { simulationError.value = failureText(error, '建立仿真账户失败'); throw error }
  }

  async function createDraft(input: SimulationDraftInput) {
    tradeError.value = null
    try { activeDraft.value = await createSimulationDraft(input, newIdempotencyKey('simulation-draft')); return activeDraft.value }
    catch (error) { tradeError.value = failureText(error, '创建订单草稿失败'); throw error }
  }

  async function reviewDraft() {
    if (!activeDraft.value) throw new Error('没有可复核的订单草稿')
    tradeError.value = null
    try { activeDraft.value = await reviewSimulationDraft(activeDraft.value.draft.draft_id, activeDraft.value.record_revision, newIdempotencyKey('simulation-review')); return activeDraft.value }
    catch (error) { tradeError.value = failureText(error, '风控复核失败'); throw error }
  }

  async function acknowledgeSoftRisk(seenReasonHash: string) {
    if (!activeDraft.value) throw new Error('没有可确认的订单草稿')
    tradeError.value = null
    try { activeDraft.value = await confirmSimulationSoftRisk(activeDraft.value.draft.draft_id, seenReasonHash, newIdempotencyKey('simulation-soft-risk')); return activeDraft.value }
    catch (error) { tradeError.value = failureText(error, '软风险确认失败'); throw error }
  }

  async function confirmDraft(seenSummaryHash: string) {
    if (!activeDraft.value) throw new Error('没有可确认的订单草稿')
    tradeError.value = null
    try { activeDraft.value = await confirmSimulationDraft(activeDraft.value.draft.draft_id, activeDraft.value.record_revision, seenSummaryHash, newIdempotencyKey('simulation-confirm')); return activeDraft.value }
    catch (error) { tradeError.value = failureText(error, '订单确认失败'); throw error }
  }

  async function submitDraft() {
    if (!activeDraft.value) throw new Error('没有可提交的订单草稿')
    tradeError.value = null
    try {
      activeOrder.value = await submitSimulationDraft(activeDraft.value.draft.draft_id, newIdempotencyKey('simulation-submit'))
      await Promise.all([loadSimulationData(), loadOrders()])
      return activeOrder.value
    } catch (error) { tradeError.value = failureText(error, '提交仿真订单失败'); throw error }
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
    tradeError.value = null
    try { activeTradePlan.value = await createTradePlanFromCandidate(instrumentId, newIdempotencyKey('plan-candidate')); return activeTradePlan.value }
    catch (error) { tradeError.value = failureText(error, '创建候选交易计划失败'); throw error }
  }

  async function startPortfolioDeviationTradePlan() {
    tradeError.value = null
    try { activeTradePlan.value = await createTradePlanFromPortfolioDeviation(newIdempotencyKey('plan-portfolio')); return activeTradePlan.value }
    catch (error) { tradeError.value = failureText(error, '创建持仓偏离计划失败'); throw error }
  }

  async function loadTradePlan(planId: string) {
    tradeError.value = null
    try { activeTradePlan.value = await fetchTradePlan(planId); return activeTradePlan.value }
    catch (error) { tradeError.value = failureText(error, '读取交易计划失败'); throw error }
  }

  async function reviseActiveTradePlan(actions: TradePlanActionRevision[]) {
    if (!activeTradePlan.value) throw new Error('没有可修订的交易计划')
    tradeError.value = null
    try {
      activeTradePlan.value = await reviseTradePlan(activeTradePlan.value.object.plan_id, activeTradePlan.value.object.revision, actions, newIdempotencyKey('plan-revise'))
      return activeTradePlan.value
    } catch (error) { tradeError.value = failureText(error, '修订交易计划失败'); throw error }
  }

  async function confirmActiveTradePlan() {
    if (!activeTradePlan.value) throw new Error('没有可确认的交易计划')
    tradeError.value = null
    try {
      activeTradePlan.value = await confirmTradePlan(activeTradePlan.value.object.plan_id, activeTradePlan.value.object.revision, newIdempotencyKey('plan-confirm'))
      return activeTradePlan.value
    } catch (error) { tradeError.value = failureText(error, '确认交易计划失败'); throw error }
  }

  function workflowFor(text: string): AgentWorkflow {
    if (/(持仓|组合|回撤|集中)/.test(text)) return 'portfolio_stress'
    if (/(交易方案|订单|计划)/.test(text)) return 'trade_plan_generation'
    if (/(策略)/.test(text)) return 'strategy_validation'
    if (/(异动|提醒|事件)/.test(text)) return 'event_impact'
    if (/(研究|画像|公司)/.test(text)) return 'company_research'
    return 'market_context'
  }

  async function runWorkflow(intent: string) {
    workflowError.value = null
    try {
      activeWorkflow.value = await createWorkflow({
        workflowKey: workflowFor(intent), intent, symbol: symbol.value,
        contextVersion: String(contextVersion.value), idempotencyKey: newIdempotencyKey('desk'),
      })
    } catch (error) { workflowError.value = failureText(error, '工作流请求失败') }
  }

  async function refreshWorkflow() {
    if (!activeWorkflow.value) return
    try { activeWorkflow.value = await fetchWorkflow(activeWorkflow.value.run_id) }
    catch (error) { workflowError.value = failureText(error, '工作流状态不可用') }
  }

  function startPolling() {
    stopPolling()
    pollTimer = setInterval(() => { if (!document.hidden) void refreshMarket() }, POLL_INTERVAL_MS)
  }

  function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null }
  function onVisibilityChange() { if (!document.hidden) void refreshMarket() }

  async function initialize() {
    await Promise.all([refreshMarket(), loadProfile(), loadNotifications(), loadMarketFacts()])
    startPolling()
    document.addEventListener('visibilitychange', onVisibilityChange)
  }

  function dispose() {
    stopPolling()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
  onScopeDispose(dispose)

  return {
    section, symbol, quotes, quoteSymbols, profile, informationFacts, sentimentFacts, notifications,
    account, portfolio, orders, fills, watchlistGroups, watchlistInstruments, selectedWatchlistId, selectedWatchlist,
    selectedWatchlistInstruments, candidates, activeDraft, activeOrder, activeTradePlan, hasSimulationAccount,
    marketError, profileError, informationFactsError, sentimentFactsError, notificationError, simulationError,
    accountError, ordersError, fillsError, simulationLoadedAt, watchlistError, candidateError, tradeError,
    loadingMarket, loadingSimulation, loadingWatchlists, loadingCandidates,
    activeWorkflow, workflowError, contextVersion, selectedQuote, unreadCount, profileSummary, quickCommands,
    setSection, setSymbol, refreshMarket, loadProfile, loadMarketFacts, loadNotifications, dismissNotification,
    loadSimulationData, loadOrders, loadWatchlists, loadCandidates, createAccount, createDraft, reviewDraft,
    acknowledgeSoftRisk, confirmDraft, submitDraft, createWatchlist, renameWatchlist, removeWatchlist,
    addToWatchlist, removeFromWatchlist, ignoreCandidate, restoreCandidate, startCandidateTradePlan,
    startPortfolioDeviationTradePlan, loadTradePlan, reviseActiveTradePlan, confirmActiveTradePlan,
    runWorkflow, refreshWorkflow, initialize, dispose,
  }
})
