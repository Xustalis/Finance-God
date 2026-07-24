/* ═══════════════════════════════════════════════════
   交易台 API 客户端
   直接调用后端 /api/* 端点（无 envelope 包装）
   ═══════════════════════════════════════════════════ */

import axios, { AxiosError } from 'axios'
import type {
  AgentRun,
  AgentResearchRequest,
  BarsResponse,
  BackendError,
  CandidateIgnoreReason,
  CandidateResponse,
  CatalogResponse,
  DecisionInboxView,
  EvidenceCompareView,
  EvidenceExportView,
  EvidenceLineageView,
  EvidenceTier,
  EvidenceView,
  HealthResponse,
  InstrumentSearchResponse,
  InvestmentMandate,
  MandateImpact,
  MandateSavePayload,
  MarketQuote,
  MarketOverviewView,
  NotificationPreference,
  OrderDraftCreate,
  PortfolioView,
  QuoteBatch,
  SimulationFill,
  SimulationAccount,
  SimulationPosition,
  StoredDraft,
  StoredOrder,
  StoredOrderView,
  TradePlanActionRevision,
  TradePlanPageView,
  WatchlistGroup,
  WatchlistInstrument,
} from '@/types/desk'

const USER_TOKEN_KEY = 'finance-god-token'

/** 独立 axios 实例：baseURL=/api，与登录会话共享 Bearer JWT。 */
const desk = axios.create({
  baseURL: '/api',
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
})

desk.interceptors.request.use((config) => {
  const token = localStorage.getItem(USER_TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export class DeskApiError extends Error {
  constructor(
    message: string,
    public status?: number,
    public code?: string,
  ) {
    super(message)
  }
}

/** 请求被主动取消（例如被更新的请求取代）时使用的错误码。 */
export const REQUEST_CANCELED = 'REQUEST_CANCELED'

/** 判断错误是否源于请求取消（AbortController.abort），供调用方静默忽略。 */
export function isCanceledError(error: unknown): boolean {
  return error instanceof DeskApiError && error.code === REQUEST_CANCELED
}

/** 从后端 {error:{code,message}} 格式提取错误消息 */
function extractError(error: unknown): DeskApiError {
  if (axios.isCancel(error)) {
    return new DeskApiError('请求已取消', undefined, REQUEST_CANCELED)
  }
  if (error instanceof AxiosError) {
    const body = error.response?.data as BackendError | undefined
    return new DeskApiError(
      body?.error?.message || error.message,
      error.response?.status,
      body?.error?.code,
    )
  }
  return new DeskApiError(error instanceof Error ? error.message : String(error))
}

export function isDeskApiError(error: unknown, status?: number): error is DeskApiError {
  if (!(error instanceof Error) || !('status' in error)) return false
  return status === undefined || (error as DeskApiError).status === status
}

export function newIdempotencyKey(scope: string): string {
  if (typeof crypto.randomUUID !== 'function') {
    throw new Error('当前浏览器不支持安全请求标识，无法执行仿真写入')
  }
  return `${scope}:${crypto.randomUUID()}`
}

function decimalNumber(value: unknown, field: string): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) {
    throw new DeskApiError(`后端字段 ${field} 不是有效数值`, 502, 'INVALID_NUMERIC_RESPONSE')
  }
  return parsed
}

function normalizedQuote(quote: MarketQuote): MarketQuote {
  return {
    ...quote,
    last: decimalNumber(quote.last, 'quote.last'),
    open: decimalNumber(quote.open, 'quote.open'),
    high: decimalNumber(quote.high, 'quote.high'),
    low: decimalNumber(quote.low, 'quote.low'),
    previous_close: quote.previous_close === null
      ? null
      : decimalNumber(quote.previous_close, 'quote.previous_close'),
    change: quote.change === null ? null : decimalNumber(quote.change, 'quote.change'),
    change_percent: quote.change_percent === null
      ? null
      : decimalNumber(quote.change_percent, 'quote.change_percent'),
    volume: decimalNumber(quote.volume, 'quote.volume'),
    amount: quote.amount === null ? null : decimalNumber(quote.amount, 'quote.amount'),
  }
}

function normalizedAccount(account: SimulationAccount): SimulationAccount {
  return {
    ...account,
    cash_total_rmb: decimalNumber(account.cash_total_rmb, 'account.cash_total_rmb'),
    cash_available_rmb: decimalNumber(account.cash_available_rmb, 'account.cash_available_rmb'),
    cash_frozen_rmb: decimalNumber(account.cash_frozen_rmb, 'account.cash_frozen_rmb'),
    margin_rmb: decimalNumber(account.margin_rmb, 'account.margin_rmb'),
  }
}

function normalizedDraft(stored: StoredDraft): StoredDraft {
  return {
    ...stored,
    draft: {
      ...stored.draft,
      quantity: stored.draft.quantity === null
        ? null
        : decimalNumber(stored.draft.quantity, 'draft.quantity'),
      amount: stored.draft.amount === null
        ? null
        : decimalNumber(stored.draft.amount, 'draft.amount'),
      limit_price: stored.draft.limit_price === null
        ? null
        : decimalNumber(stored.draft.limit_price, 'draft.limit_price'),
    },
    cost_estimate: stored.cost_estimate
      ? {
          ...stored.cost_estimate,
          reference_price: decimalNumber(stored.cost_estimate.reference_price, 'cost_estimate.reference_price'),
          quantity: decimalNumber(stored.cost_estimate.quantity, 'cost_estimate.quantity'),
          notional: decimalNumber(stored.cost_estimate.notional, 'cost_estimate.notional'),
          fee: decimalNumber(stored.cost_estimate.fee, 'cost_estimate.fee'),
          total: decimalNumber(stored.cost_estimate.total, 'cost_estimate.total'),
          fee_bps: decimalNumber(stored.cost_estimate.fee_bps, 'cost_estimate.fee_bps'),
          slippage_bps: decimalNumber(stored.cost_estimate.slippage_bps, 'cost_estimate.slippage_bps'),
        }
      : null,
  }
}

function normalizedOrder(stored: StoredOrder): StoredOrder {
  return {
    ...stored,
    exchange_order: stored.exchange_order
      ? {
          ...stored.exchange_order,
          quantity: decimalNumber(stored.exchange_order.quantity, 'order.quantity'),
          cumulative_filled: decimalNumber(
            stored.exchange_order.cumulative_filled,
            'order.cumulative_filled',
          ),
        }
      : null,
    fund_order: stored.fund_order
      ? {
          ...stored.fund_order,
          requested_amount: stored.fund_order.requested_amount === null
            ? null
            : decimalNumber(stored.fund_order.requested_amount, 'order.requested_amount'),
          requested_units: stored.fund_order.requested_units === null
            ? null
            : decimalNumber(stored.fund_order.requested_units, 'order.requested_units'),
        }
      : null,
  }
}

function normalizedFill(fill: SimulationFill): SimulationFill {
  return {
    ...fill,
    quantity: decimalNumber(fill.quantity, 'fill.quantity'),
    price: decimalNumber(fill.price, 'fill.price'),
    fee: decimalNumber(fill.fee, 'fill.fee'),
    slippage_bps: decimalNumber(fill.slippage_bps, 'fill.slippage_bps'),
  }
}

function normalizedOrderView(view: StoredOrderView): StoredOrderView {
  return {
    ...view,
    limit_price: view.limit_price === null
      ? null
      : decimalNumber(view.limit_price, 'order.limit_price'),
    quantity: decimalNumber(view.quantity, 'order.quantity'),
    cumulative_filled: decimalNumber(view.cumulative_filled, 'order.cumulative_filled'),
    remaining_quantity: decimalNumber(view.remaining_quantity, 'order.remaining_quantity'),
    average_fill_price: view.average_fill_price === null
      ? null
      : decimalNumber(view.average_fill_price, 'order.average_fill_price'),
    total_fee_rmb: decimalNumber(view.total_fee_rmb, 'order.total_fee_rmb'),
    filled_notional_rmb: decimalNumber(view.filled_notional_rmb, 'order.filled_notional_rmb'),
    fills: view.fills.map(normalizedFill),
  }
}

function normalizedPortfolio(view: PortfolioView): PortfolioView {
  return {
    ...view,
    realized_pnl_rmb: decimalNumber(view.realized_pnl_rmb, 'portfolio.realized_pnl_rmb'),
    positions: view.positions.map((position) => ({
      ...position,
      quantity: decimalNumber(position.quantity, 'position.quantity'),
      settled_quantity: decimalNumber(position.settled_quantity, 'position.settled_quantity'),
      frozen_quantity: decimalNumber(position.frozen_quantity, 'position.frozen_quantity'),
      available_quantity: decimalNumber(position.available_quantity, 'position.available_quantity'),
      cost_basis_rmb: decimalNumber(position.cost_basis_rmb, 'position.cost_basis_rmb'),
      average_cost_rmb: position.average_cost_rmb === null
        ? null
        : decimalNumber(position.average_cost_rmb, 'position.average_cost_rmb'),
      realized_pnl_rmb: decimalNumber(position.realized_pnl_rmb, 'position.realized_pnl_rmb'),
    })),
  }
}

function normalizedTradePlan(view: TradePlanPageView): TradePlanPageView {
  return {
    ...view,
    object: {
      ...view.object,
      estimated_fee_rmb: decimalNumber(
        view.object.estimated_fee_rmb,
        'trade_plan.estimated_fee_rmb',
      ),
      actions: view.object.actions.map((action) => ({
        ...action,
        quantity: action.quantity === null
          ? null
          : decimalNumber(action.quantity, 'trade_plan.actions.quantity'),
        limit_price: action.limit_price === null
          ? null
          : decimalNumber(action.limit_price, 'trade_plan.actions.limit_price'),
        reference_price: action.reference_price === null
          ? null
          : decimalNumber(action.reference_price, 'trade_plan.actions.reference_price'),
      })),
    },
  }
}

// ─── 行情数据 ──────────────────────────────────────

/** 批量获取实时行情报价 */
export async function fetchQuotes(symbols: string[]): Promise<QuoteBatch> {
  try {
    const { data } = await desk.get<QuoteBatch>('/market/quotes', {
      params: { symbols: symbols.join(',') },
    })
    return { ...data, quotes: data.quotes.map(normalizedQuote) }
  } catch (err) {
    throw extractError(err)
  }
}

/** 获取总览页权威市场指标；浏览器只展示，不计算交易判断。 */
export async function fetchMarketOverview(symbols: string[]): Promise<MarketOverviewView> {
  try {
    const { data } = await desk.get<MarketOverviewView>('/market/overview', {
      params: { symbols: symbols.join(',') },
    })
    return {
      ...data,
      data: {
        ...data.data,
        quotes: data.data.quotes.map(normalizedQuote),
        signal: {
          ...data.data.signal,
          consistency_percent: data.data.signal.consistency_percent === null
            ? null
            : decimalNumber(
              data.data.signal.consistency_percent,
              'overview.signal.consistency_percent',
            ),
        },
        indicators: data.data.indicators.map((indicator) => ({
          ...indicator,
          value: indicator.value === null
            ? null
            : decimalNumber(indicator.value, `overview.indicators.${indicator.code}`),
        })),
      },
    }
  } catch (err) {
    throw extractError(err)
  }
}

/** 获取 K 线数据；可选 signal 用于取消被更新请求取代的在途拉取。 */
export async function fetchBars(
  symbol: string,
  limit = 80,
  signal?: AbortSignal,
): Promise<BarsResponse> {
  try {
    const { data } = await desk.get<BarsResponse>('/market/bars', {
      params: { symbol, limit },
      signal,
    })
    return {
      ...data,
      bars: data.bars.map((bar) => ({
        ...bar,
        open: decimalNumber(bar.open, 'bar.open'),
        high: decimalNumber(bar.high, 'bar.high'),
        low: decimalNumber(bar.low, 'bar.low'),
        close: decimalNumber(bar.close, 'bar.close'),
        volume: decimalNumber(bar.volume, 'bar.volume'),
        amount: bar.amount === null ? null : decimalNumber(bar.amount, 'bar.amount'),
      })),
    }
  } catch (err) {
    throw extractError(err)
  }
}

/** 获取数据目录 */
export async function fetchCatalog(): Promise<CatalogResponse> {
  try {
    const { data } = await desk.get<CatalogResponse>('/market/catalog')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

/** 搜索标的主数据（代码/别名/市场/资产类型）。 */
export async function searchInstruments(query = ''): Promise<InstrumentSearchResponse> {
  try {
    const params = query.trim() ? { q: query.trim() } : undefined
    const { data } = await desk.get<InstrumentSearchResponse>('/market/instruments', { params })
    return data
  } catch (err) {
    throw extractError(err)
  }
}

// ─── 健康检查 ──────────────────────────────────────

/** 检查后端健康状态 */
export async function fetchHealth(): Promise<HealthResponse> {
  try {
    const { data } = await desk.get<HealthResponse>('/health')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

// ─── 仿真交易（owner 仅来自 Bearer JWT subject） ───

export async function fetchCurrentAccount(): Promise<SimulationAccount> {
  try {
    const { data } = await desk.get<SimulationAccount>('/simulation/accounts/current')
    return normalizedAccount(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function createSimulationAccount(
  initialCashRmb: number,
  idempotencyKey: string,
): Promise<SimulationAccount> {
  try {
    const { data } = await desk.post<SimulationAccount>(
      '/simulation/accounts',
      { initial_cash_rmb: initialCashRmb },
      { headers: { 'idempotency-key': idempotencyKey } },
    )
    return normalizedAccount(data)
  } catch (err) {
    throw extractError(err)
  }
}

/** 重置仿真账户（关闭当前账户并以固定现金重建）。返回新账户。 */
export async function resetSimulationAccount(
  accountId: string,
  initialCashRmb: number,
  idempotencyKey: string,
): Promise<SimulationAccount> {
  try {
    const { data } = await desk.post<SimulationAccount>(
      `/simulation/accounts/${accountId}/reset`,
      { initial_cash_rmb: initialCashRmb },
      { headers: { 'idempotency-key': idempotencyKey } },
    )
    return normalizedAccount(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function createOrderDraft(
  request: OrderDraftCreate,
  idempotencyKey: string,
): Promise<StoredDraft> {
  try {
    const { data } = await desk.post<StoredDraft>(
      '/simulation/drafts',
      request,
      { headers: { 'idempotency-key': idempotencyKey } },
    )
    return normalizedDraft(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function reviewOrderDraft(
  draftId: string,
  expectedRevision: number,
): Promise<StoredDraft> {
  try {
    const { data } = await desk.post<StoredDraft>(
      `/simulation/drafts/${draftId}/review`,
      { expected_revision: expectedRevision },
    )
    return normalizedDraft(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function confirmSoftRisk(
  draftId: string,
  seenReasonHash: string,
): Promise<StoredDraft> {
  try {
    const { data } = await desk.post<StoredDraft>(
      `/simulation/drafts/${draftId}/soft-risk-confirmations`,
      { seen_reason_hash: seenReasonHash },
    )
    return normalizedDraft(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function confirmOrderDraft(
  draftId: string,
  expectedRevision: number,
  seenSummaryHash: string,
): Promise<StoredDraft> {
  try {
    const { data } = await desk.post<StoredDraft>(
      `/simulation/drafts/${draftId}/confirm`,
      {
        expected_revision: expectedRevision,
        seen_summary_hash: seenSummaryHash,
      },
    )
    return normalizedDraft(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function submitOrderDraft(
  draftId: string,
  idempotencyKey: string,
): Promise<StoredOrder> {
  try {
    const { data } = await desk.post<StoredOrder>(
      `/simulation/drafts/${draftId}/submit`,
      {},
      { headers: { 'idempotency-key': idempotencyKey } },
    )
    return normalizedOrder(data)
  } catch (err) {
    throw extractError(err)
  }
}

/** 订单执行中心列表：完整字段 + 状态时间线（StoredOrderView）。 */
export async function fetchOrders(): Promise<StoredOrderView[]> {
  try {
    const { data } = await desk.get<StoredOrderView[]>('/simulation/orders')
    return data.map(normalizedOrderView)
  } catch (err) {
    throw extractError(err)
  }
}

/**
 * 权威持仓与估值事实（数量/成本/已实现盈亏）。
 * 无账户（404）视为空组合，返回空 positions，与其他失败态解耦。
 * 市值与浮动盈亏由前端用实时行情计算，不在此返回。
 */
export async function fetchPortfolio(): Promise<PortfolioView | null> {
  try {
    const { data } = await desk.get<PortfolioView>('/simulation/portfolio')
    return normalizedPortfolio(data)
  } catch (err) {
    if (isDeskApiError(err, 404)) return null
    throw extractError(err)
  }
}

/** 决策收件箱：聚合订单异常与未读通知，按 P0-P3 优先级排序。 */
export async function fetchDecisionInbox(): Promise<DecisionInboxView> {
  try {
    const { data } = await desk.get<DecisionInboxView>('/simulation/decision-inbox')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

/**
 * 获取当前账户持仓 projection。
 * 无账户（404）视为空账户，返回空数组，与其他失败态解耦。
 */
export async function fetchPositions(): Promise<SimulationPosition[]> {
  try {
    const { data } = await desk.get<SimulationPosition[]>(
      '/simulation/accounts/current/positions',
    )
    return data.map((position) => ({
      ...position,
      long_quantity: decimalNumber(position.long_quantity, 'position.long_quantity'),
      settled_quantity: decimalNumber(position.settled_quantity, 'position.settled_quantity'),
      frozen_quantity: decimalNumber(position.frozen_quantity, 'position.frozen_quantity'),
      cost_rmb: decimalNumber(position.cost_rmb, 'position.cost_rmb'),
    }))
  } catch (err) {
    if (isDeskApiError(err, 404)) return []
    throw extractError(err)
  }
}

export async function fetchFills(orderId?: string): Promise<SimulationFill[]> {
  try {
    const { data } = await desk.get<SimulationFill[]>('/simulation/fills', {
      params: orderId ? { order_id: orderId } : undefined,
    })
    return data.map((fill) => ({
      ...fill,
      quantity: decimalNumber(fill.quantity, 'fill.quantity'),
      price: decimalNumber(fill.price, 'fill.price'),
      fee: decimalNumber(fill.fee, 'fill.fee'),
      slippage_bps: decimalNumber(fill.slippage_bps, 'fill.slippage_bps'),
    }))
  } catch (err) {
    throw extractError(err)
  }
}

// ─── 工作区（自选股等） ────────────────────────────

export async function fetchWatchlists(): Promise<WatchlistGroup[]> {
  try {
    const { data } = await desk.get<WatchlistGroup[]>('/workspace/watchlists')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function createWatchlistGroup(
  name: string,
  description?: string,
): Promise<WatchlistGroup> {
  try {
    const { data } = await desk.post<WatchlistGroup>('/workspace/watchlists', {
      name,
      description: description ?? null,
    })
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function updateWatchlistGroup(
  groupId: string,
  name: string,
  expectedRevision: number,
  description?: string,
): Promise<WatchlistGroup> {
  try {
    const { data } = await desk.patch<WatchlistGroup>(`/workspace/watchlists/${groupId}`, {
      name,
      description: description ?? null,
      expected_revision: expectedRevision,
    })
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function deleteWatchlistGroup(
  groupId: string,
  expectedRevision: number,
): Promise<void> {
  try {
    await desk.delete(`/workspace/watchlists/${groupId}`, {
      data: { expected_revision: expectedRevision },
    })
  } catch (err) {
    throw extractError(err)
  }
}

export async function fetchWatchlistInstruments(
  groupId: string,
): Promise<WatchlistInstrument[]> {
  try {
    const { data } = await desk.get<WatchlistInstrument[]>(
      `/workspace/watchlists/${groupId}/instruments`,
    )
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function addWatchlistInstrument(
  groupId: string,
  instrumentId: string,
): Promise<WatchlistInstrument> {
  try {
    const { data } = await desk.post<WatchlistInstrument>(
      `/workspace/watchlists/${groupId}/instruments`,
      { instrument_id: instrumentId },
    )
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function removeWatchlistInstrument(
  groupId: string,
  instrumentId: string,
): Promise<void> {
  try {
    await desk.delete(`/workspace/watchlists/${groupId}/instruments/${instrumentId}`)
  } catch (err) {
    throw extractError(err)
  }
}

// ─── 系统候选（确定性五维评分，无综合分） ──────────
// 后端 /workspace/candidates 基于真实持仓 + 实时行情逐维解释；
// 行情不可用时返回 unavailable_reason，由页面显式降级呈现。

export async function fetchCandidates(): Promise<CandidateResponse> {
  try {
    const { data } = await desk.get<CandidateResponse>('/workspace/candidates')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

// ─── 交易计划（版本化 T04 闭环）──────────────────

export async function createCandidateTradePlan(
  instrumentId: string,
  idempotencyKey: string,
): Promise<TradePlanPageView> {
  try {
    const { data } = await desk.post<TradePlanPageView>(
      '/trade-plans/from-candidate',
      { instrument_id: instrumentId },
      { headers: { 'idempotency-key': idempotencyKey } },
    )
    return normalizedTradePlan(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function createPortfolioDeviationTradePlan(
  idempotencyKey: string,
): Promise<TradePlanPageView> {
  try {
    const { data } = await desk.post<TradePlanPageView>(
      '/trade-plans/from-portfolio-deviation',
      {},
      { headers: { 'idempotency-key': idempotencyKey } },
    )
    return normalizedTradePlan(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function fetchTradePlan(planId: string): Promise<TradePlanPageView> {
  try {
    const { data } = await desk.get<TradePlanPageView>(`/trade-plans/${planId}`)
    return normalizedTradePlan(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function saveTradePlanVersion(
  planId: string,
  expectedRevision: number,
  actions: TradePlanActionRevision[],
): Promise<TradePlanPageView> {
  try {
    const { data } = await desk.post<TradePlanPageView>(
      `/trade-plans/${planId}/versions`,
      { expected_revision: expectedRevision, actions },
    )
    return normalizedTradePlan(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function confirmTradePlanAndGenerateDrafts(
  planId: string,
  expectedRevision: number,
  idempotencyKey: string,
): Promise<TradePlanPageView> {
  try {
    const { data } = await desk.post<TradePlanPageView>(
      `/trade-plans/${planId}/confirm-and-generate`,
      { expected_revision: expectedRevision },
      { headers: { 'idempotency-key': idempotencyKey } },
    )
    return normalizedTradePlan(data)
  } catch (err) {
    throw extractError(err)
  }
}

/** 忽略某候选（持久化反馈，不删证据）。 */
export async function ignoreCandidate(
  instrumentId: string,
  reason: CandidateIgnoreReason,
  note?: string,
): Promise<void> {
  try {
    await desk.post(`/workspace/candidates/${instrumentId}/ignore`, {
      reason,
      note: note ?? null,
    })
  } catch (err) {
    throw extractError(err)
  }
}

/** 撤销忽略某候选。 */
export async function unignoreCandidate(instrumentId: string): Promise<void> {
  try {
    await desk.delete(`/workspace/candidates/${instrumentId}/ignore`)
  } catch (err) {
    throw extractError(err)
  }
}

// ─── 通知 ──────────────────────────────────────────

export async function fetchNotifications() {
  try {
    const { data } = await desk.get('/workspace/notifications')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function markNotificationRead(notificationId: string) {
  try {
    const { data } = await desk.post(`/workspace/notifications/${notificationId}/read`)
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function fetchNotificationPreferences(): Promise<NotificationPreference> {
  try {
    const { data } = await desk.get<NotificationPreference>('/workspace/notification-preferences')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function updateNotificationPreferences(categoryPreferences: Record<string, boolean>) {
  try {
    const { data } = await desk.put('/workspace/notification-preferences', { category_preferences: categoryPreferences })
    return data
  } catch (err) {
    throw extractError(err)
  }
}

// ─── 仿真交易扩展 ──────────────────────────────────

export async function cancelOrder(orderId: string) {
  try {
    const { data } = await desk.post(`/simulation/orders/${orderId}/cancel`, {})
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function fetchOrder(orderId: string): Promise<StoredOrderView> {
  try {
    const { data } = await desk.get<StoredOrderView>(`/simulation/orders/${orderId}`)
    return normalizedOrderView(data)
  } catch (err) {
    throw extractError(err)
  }
}

export async function reconcileOrder(orderId: string) {
  try {
    const { data } = await desk.post(`/simulation/orders/${orderId}/reconcile`, {})
    return data
  } catch (err) {
    throw extractError(err)
  }
}

// ─── AI 研究（Multi-Agent 运行时） ──────────────
// 真实 Agent 编排结果；不可用时抛出 DeskApiError（status 503，
// code=AI_RUNTIME_UNAVAILABLE），由调用方渲染显式失败状态。

/** 按当前对象发起一次真实 Agent 研究运行。 */
export async function runAgentResearch(request: AgentResearchRequest): Promise<AgentRun> {
  try {
    const { data } = await desk.post<AgentRun>('/agent/research', request, {
      // Agent 运行含真实模型调用，需更长超时。
      timeout: 120_000,
    })
    return data
  } catch (err) {
    throw extractError(err)
  }
}

/** 读取当前运行时已注册的 Agent 目录。 */
export async function fetchAgentCatalog(): Promise<{ agents: Array<{ agent_id: string; title: string; source: string }> }> {
  try {
    const { data } = await desk.get<{ agents: Array<{ agent_id: string; title: string; source: string }> }>('/agent/catalog')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

// ─── 交易授权（T00，仿真业务数据） ──────────────
// 与后端 /mandate/* 对齐。授权变化均创建新版本、不覆盖历史；
// 保存/暂停/恢复/撤销用 expected_revision 做乐观并发。

/** 读取当前生效授权（不存在时后端自动创建默认 L0 后返回）。 */
export async function fetchCurrentMandate(): Promise<InvestmentMandate> {
  try {
    const { data } = await desk.get<InvestmentMandate>('/mandate/current')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

/** 读取授权版本历史（版本号降序）。 */
export async function fetchMandateHistory(): Promise<InvestmentMandate[]> {
  try {
    const { data } = await desk.get<InvestmentMandate[]>('/mandate/history')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

/** 保存新版本授权（校验通过后追加新版本）。 */
export async function saveMandate(
  payload: MandateSavePayload,
  idempotencyKey: string,
): Promise<InvestmentMandate> {
  try {
    const { data } = await desk.post<InvestmentMandate>('/mandate/versions', payload, {
      headers: { 'idempotency-key': idempotencyKey },
    })
    return data
  } catch (err) {
    throw extractError(err)
  }
}

async function changeMandateStatus(
  action: 'pause' | 'resume' | 'revoke',
  expectedRevision: number,
  note?: string | null,
): Promise<InvestmentMandate> {
  try {
    const { data } = await desk.post<InvestmentMandate>(`/mandate/${action}`, {
      expected_revision: expectedRevision,
      note: note ?? null,
    })
    return data
  } catch (err) {
    throw extractError(err)
  }
}

/** 紧急暂停当前授权（创建 paused 新版本）。 */
export function pauseMandate(expectedRevision: number, note?: string | null) {
  return changeMandateStatus('pause', expectedRevision, note)
}

/** 恢复授权为 active（创建新版本）。 */
export function resumeMandate(expectedRevision: number, note?: string | null) {
  return changeMandateStatus('resume', expectedRevision, note)
}

/** 撤销授权（创建 revoked 新版本，之后新订单意图将被拦截）。 */
export function revokeMandate(expectedRevision: number, note?: string | null) {
  return changeMandateStatus('revoke', expectedRevision, note)
}

/** 读取受影响面：现存订单意图中会被当前授权拦截的项与失效字段。 */
export async function fetchMandateImpact(): Promise<MandateImpact> {
  try {
    const { data } = await desk.get<MandateImpact>('/mandate/impact')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

// ─── 过程与证据（T10 只读） ────────────────────────
// 与后端 /evidence/* 对齐。证据按 (object_type, object_id, version) 只读检索；
// 内部错误栈永不经 HTTP 返回（internal tier 保留给进程内运维工具）。

/** 读取某对象某版本的证据抽屉内容；version 省略时取最新。 */
export async function fetchEvidence(
  objectType: string,
  objectId: string,
  options: { version?: string; tier?: EvidenceTier } = {},
): Promise<EvidenceView> {
  try {
    const params: Record<string, string> = {}
    if (options.version) params.version = options.version
    if (options.tier) params.tier = options.tier
    const { data } = await desk.get<EvidenceView>(
      `/evidence/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}`,
      { params: Object.keys(params).length ? params : undefined },
    )
    return data
  } catch (err) {
    throw extractError(err)
  }
}

/** 读取某对象某版本的数据血缘（上游对象版本与来源时点）。 */
export async function fetchEvidenceLineage(
  objectType: string,
  objectId: string,
  version?: string,
): Promise<EvidenceLineageView> {
  try {
    const { data } = await desk.get<EvidenceLineageView>(
      `/evidence/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/lineage`,
      { params: version ? { version } : undefined },
    )
    return data
  } catch (err) {
    throw extractError(err)
  }
}

/** 比较同一对象两个不可变版本的证据差异。 */
export async function compareEvidenceVersions(
  objectType: string,
  objectId: string,
  versionA: string,
  versionB: string,
): Promise<EvidenceCompareView> {
  try {
    const { data } = await desk.get<EvidenceCompareView>(
      `/evidence/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/versions/compare`,
      { params: { a: versionA, b: versionB } },
    )
    return data
  } catch (err) {
    throw extractError(err)
  }
}

/** 导出证据包目录（含全部版本与生成时间）与指定版本的完整证据。 */
export async function exportEvidence(
  objectType: string,
  objectId: string,
  options: { version?: string; tier?: EvidenceTier } = {},
): Promise<EvidenceExportView> {
  try {
    const { data } = await desk.post<EvidenceExportView>(
      `/evidence/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/export`,
      { version: options.version ?? null, tier: options.tier ?? 'normal' },
    )
    return data
  } catch (err) {
    throw extractError(err)
  }
}
