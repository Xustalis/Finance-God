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
  CatalogResponse,
  DecisionInboxView,
  HealthResponse,
  InstrumentSearchResponse,
  MarketQuote,
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

/** 从后端 {error:{code,message}} 格式提取错误消息 */
function extractError(error: unknown): DeskApiError {
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

/** 获取 K 线数据 */
export async function fetchBars(symbol: string, limit = 80): Promise<BarsResponse> {
  try {
    const { data } = await desk.get<BarsResponse>('/market/bars', {
      params: { symbol, limit },
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

export async function fetchWatchlists() {
  try {
    const { data } = await desk.get('/workspace/watchlists')
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function createWatchlistGroup(name: string, description?: string) {
  try {
    const { data } = await desk.post('/workspace/watchlists', { name, description: description ?? null })
    return data
  } catch (err) {
    throw extractError(err)
  }
}

export async function addWatchlistInstrument(groupId: string, instrumentId: string) {
  try {
    const { data } = await desk.post(`/workspace/watchlists/${groupId}/instruments`, { instrument_id: instrumentId })
    return data
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
