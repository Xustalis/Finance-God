import axios from 'axios'
import type { ProfileWithRecommendations } from '@/types/api'

const client = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '/api', timeout: 30_000 })

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('finance-god-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export interface DeskQuote {
  symbol: string
  name: string
  last: number
  change: number | null
  change_percent: number | null
  provider: string
  provider_time: string
  frequency: string
  freshness: string
  market_status: string
}

export interface DeskWorkflowRun {
  run_id: string
  status: 'queued' | 'running' | 'completed' | 'attention_required' | 'failed' | 'timed_out' | 'blocked' | 'cancelled'
  workflow_key: string
  workflow_version: string
  revision: number
  created_at?: string
  updated_at?: string
  errors?: readonly unknown[]
}

export interface DeskNotification {
  notification_id: string
  severity: string
  title: string
  message: string
  created_at: string
  status: string
}

export interface DeskFact {
  scope: string
  source?: {
    endpoint: string
    data_time: string
    ingested_at: string
    evidence_ref: string
  }
  freshness?: { status: string }
  fields: Array<{ name: string; value: string | number | boolean | null }>
}

export interface CrawlerSentiment {
  score: number
  level: 'extreme_fear' | 'fear' | 'neutral' | 'greed' | 'extreme_greed'
  breadth: {
    up_count: number
    down_count: number
    flat_count: number
    limit_up: number
    limit_down: number
    up_ratio: number
  }
  north_flow: number
  sector_flows: Array<{
    sector_name: string
    change_percent: number
    net_inflow: number
  }>
  hot_sectors: string[]
  risk_sectors: string[]
  retrieved_at: string
  data_source: string
}

export interface DeskFactBatch {
  provider: string
  fact_kind: 'company_disclosure' | 'margin_balance' | 'market_sentiment' | 'industry_news'
  symbol: string
  requested_at: string
  facts: DeskFact[]
  sentiment?: CrawlerSentiment
  news?: Array<{
    title: string
    summary: string
    source: string
    url: string
    publish_time: string | null
    sector: string
    tags: string[]
  }>
}

export type IdempotencyKey = string
export type SimulationOrderSide = 'buy' | 'sell' | 'short' | 'cover' | 'subscribe' | 'redeem' | 'convert' | 'recurring_invest'
export type SimulationOrderType = 'market' | 'limit' | 'fund'
export type SimulationDraftMode = 'manual' | 'planned'

export interface RiskReason {
  code: string
  severity: 'soft' | 'hard'
  message: string
}

export interface VersionReference {
  object_type: string
  object_id: string
  version: string
}

export interface SimulationAccount {
  account_id: string
  owner_id: string
  status: string
  cash_total_rmb: string
  cash_available_rmb: string
  cash_frozen_rmb: string
  margin_rmb: string
  revision: number
}

export interface SimulationPosition {
  instrument_id: string
  currency: string
  quantity: string
  settled_quantity: string
  frozen_quantity: string
  available_quantity: string
  cost_basis_rmb: string
  average_cost_rmb: string | null
  realized_pnl_rmb: string
  revision: number
}

export interface SimulationPortfolio {
  account_id: string
  owner_id: string
  as_of: string
  rule_version: string
  positions: SimulationPosition[]
  realized_pnl_rmb: string
}

export interface SimulationDraftInput {
  mode: SimulationDraftMode
  account_id: string
  instrument_id: string
  side: SimulationOrderSide
  order_type: SimulationOrderType
  quantity?: string
  amount?: string
  limit_price?: string
  reference_price?: string
  time_in_force?: 'day' | 'good_til_cancelled' | 'immediate_or_cancel'
  fund_rule_version?: VersionReference
  valid_until: string
  input_versions: VersionReference[]
  plan_reference?: VersionReference
}

export interface SimulationDraft {
  record_revision: number
  owner_id: string
  mode: SimulationDraftMode
  draft: {
    draft_id: string
    status: string
    revision: number
    account_id: string
    instrument_id: string
    side: SimulationOrderSide
    order_type: SimulationOrderType
    quantity: string | null
    amount: string | null
    limit_price: string | null
    time_in_force: string | null
    valid_until: string
    input_versions: VersionReference[]
  }
  reference_price: string | null
  review: { succeeded: boolean; summary: string | null; error: string | null } | null
  risk_result: {
    status: string
    reason_hash?: string
    reasons?: RiskReason[]
    summary_hash?: string
    soft_confirmation?: unknown | null
    [key: string]: unknown
  } | null
  cost_estimate: {
    reference_price: string
    quantity: string
    notional: string
    fee: string
    total: string
    cash_flow: string
    currency: string
    rule_version: string
  } | null
  immutable_summary_hash: string | null
  confirmed_at: string | null
}

export interface SimulationOrder {
  order_id: string
  owner_id: string
  order_kind: 'exchange' | 'fund'
  status: string
  instrument_id: string
  side: string
  order_type: string
  time_in_force: string | null
  limit_price: string | null
  quantity: string
  cumulative_filled: string
  remaining_quantity: string
  average_fill_price: string | null
  total_fee_rmb: string
  filled_notional_rmb: string
  revision: number
  confirmed_at: string | null
  updated_at: string
  execution_error: string | null
  fills: Array<{
    fill_id: string
    quantity: string
    price: string
    fee: string
    occurred_at: string
  }>
}

export interface SimulationFill {
  fill_id: string
  order_id: string
  account_id: string
  instrument_id: string
  side: string | null
  quantity: string
  price: string
  fee: string
  slippage_bps: string
  model_version: string
  rule_version: string
  occurred_at: string
  ledger_fill_id: string
}

export interface WatchlistGroup {
  group_id: string
  owner_user_id: string
  name: string
  description: string | null
  revision: number
  created_at: string
  updated_at: string
}

export interface WatchlistInstrument {
  group_id: string
  instrument_id: string
  added_by: string
  added_at: string
}

export interface ResearchCandidate {
  instrument_id: string
  symbol: string
  name: string | null
  asset_type: string | null
  market: string | null
  currency: string | null
  direction: string
  direction_label: string
  purpose: string
  dimensions: Array<{
    dimension: 'portfolio_fit' | 'risk' | 'cost' | 'liquidity' | 'evidence'
    label: string
    rating: 'strong' | 'adequate' | 'weak' | 'missing'
    detail: string
    metrics: Record<string, string>
    missing_fields: string[]
  }>
  exclusions: Array<{ reason_code: string; detail: string }>
  tradable: boolean
  ignored: boolean
  ignore_reason: string | null
  as_of: string | null
  provider: string | null
}

export interface ResearchCandidateResponse {
  generated_at: string
  rule_version: string
  purpose_summary: string
  candidates: ResearchCandidate[]
  unavailable_reason: string | null
}

export interface TradePlanActionRevision {
  action_id: string
  quantity: string | null
  included: boolean
}

export interface TradePlan {
  object: {
    plan_id: string
    status: string
    revision: number
    actions: Array<{
      action_id: string
      instrument_id: string
      side: string
      quantity: string | null
      included: boolean
    }>
  }
  source_type: string
  source_id: string
  capabilities: Array<{ action: string; enabled: boolean; reason?: string | null }>
  history: Array<{ revision: number }>
  [key: string]: unknown
}

function errorText(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const responseError = error.response?.data?.error
    const message = responseError?.message || error.response?.data?.detail
    const code = responseError?.code
    if (typeof message === 'string' && typeof code === 'string') return `${code} · ${message}`
    return typeof message === 'string' ? message : error.message
  }
  return error instanceof Error ? error.message : '请求失败'
}

async function request<T>(call: () => Promise<{ data: T }>): Promise<T> {
  try { return (await call()).data } catch (error) { throw new Error(errorText(error)) }
}

function idempotencyHeaders(idempotencyKey: IdempotencyKey): { 'Idempotency-Key': IdempotencyKey } {
  return { 'Idempotency-Key': idempotencyKey }
}

export async function fetchMarketOverview(symbols: readonly string[]): Promise<DeskQuote[]> {
  const result = await request<{ data?: { quotes?: DeskQuote[] }; quotes?: DeskQuote[] }>(() => client.get('/market/overview', { params: { symbols: symbols.join(',') } }))
  return result.data?.quotes ?? result.quotes ?? []
}

export function fetchInformationFacts(symbol: string): Promise<DeskFactBatch> {
  return request(() => client.get('/market/information-facts', {
    params: { symbol, limit: 10 },
  }))
}

export function fetchSentimentFacts(symbol: string): Promise<DeskFactBatch> {
  return request(() => client.get('/market/sentiment-facts', { params: { symbol, limit: 8 } }))
}

export async function fetchProfile(): Promise<ProfileWithRecommendations> {
  const result = await request<{ success: boolean; data: ProfileWithRecommendations | null; error?: { message?: string } }>(() => client.get('/v1/profiles/me/latest'))
  if (!result.success || !result.data) throw new Error(result.error?.message || '画像数据不可用')
  return result.data
}

export async function fetchNotifications(): Promise<DeskNotification[]> {
  const result = await request<DeskNotification[] | { notifications?: DeskNotification[] }>(() => client.get('/workspace/notifications'))
  if (Array.isArray(result)) return result
  return result?.notifications ?? []
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  await request(() => client.post(`/workspace/notifications/${encodeURIComponent(notificationId)}/read`))
}

export async function createWorkflow(input: {
  workflowKey: string
  intent: string
  symbol: string
  contextVersion: string
  idempotencyKey: string
}): Promise<DeskWorkflowRun> {
  return request(() => client.post('/workflows', {
    workflow_key: input.workflowKey,
    request_intent: input.intent,
    symbol: input.symbol,
    context_version: input.contextVersion,
  }, { headers: { 'Idempotency-Key': input.idempotencyKey } }))
}

export async function fetchWorkflow(runId: string): Promise<DeskWorkflowRun> {
  return request(() => client.get(`/workflows/${encodeURIComponent(runId)}`))
}

export function fetchSimulationAccount(): Promise<SimulationAccount | null> {
  return request(() => client.get('/simulation/accounts/current'))
}

export function createSimulationAccount(initialCashRmb: string, idempotencyKey: IdempotencyKey): Promise<SimulationAccount> {
  return request(() => client.post('/simulation/accounts', { initial_cash_rmb: initialCashRmb }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function resetSimulationAccount(accountId: string, initialCashRmb: string, idempotencyKey: IdempotencyKey): Promise<SimulationAccount> {
  return request(() => client.post(`/simulation/accounts/${encodeURIComponent(accountId)}/reset`, { initial_cash_rmb: initialCashRmb }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function fetchSimulationPortfolio(): Promise<SimulationPortfolio> {
  return request(() => client.get('/simulation/portfolio'))
}

export interface SimulationAccountPosition {
  account_id: string
  instrument_id: string
  currency: string
  long_quantity: string
  settled_quantity: string
  frozen_quantity: string
  cost_rmb: string
  revision: number
}

export function fetchSimulationPositions(): Promise<SimulationAccountPosition[]> {
  return request(() => client.get('/simulation/accounts/current/positions'))
}

export function fetchSimulationOrders(): Promise<SimulationOrder[]> {
  return request(() => client.get('/simulation/orders'))
}

export function fetchSimulationFills(): Promise<SimulationFill[]> {
  return request(() => client.get('/simulation/fills'))
}

export function createSimulationDraft(input: SimulationDraftInput, idempotencyKey: IdempotencyKey): Promise<SimulationDraft> {
  return request(() => client.post('/simulation/drafts', input, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function fetchSimulationDraft(draftId: string): Promise<SimulationDraft> {
  return request(() => client.get(`/simulation/drafts/${encodeURIComponent(draftId)}`))
}

export function reviewSimulationDraft(draftId: string, expectedRevision: number, idempotencyKey: IdempotencyKey): Promise<SimulationDraft> {
  return request(() => client.post(`/simulation/drafts/${encodeURIComponent(draftId)}/review`, { expected_revision: expectedRevision }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function confirmSimulationSoftRisk(draftId: string, seenReasonHash: string, idempotencyKey: IdempotencyKey): Promise<SimulationDraft> {
  return request(() => client.post(`/simulation/drafts/${encodeURIComponent(draftId)}/soft-risk-confirmations`, { seen_reason_hash: seenReasonHash }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function confirmSimulationDraft(draftId: string, expectedRevision: number, seenSummaryHash: string, idempotencyKey: IdempotencyKey): Promise<SimulationDraft> {
  return request(() => client.post(`/simulation/drafts/${encodeURIComponent(draftId)}/confirm`, { expected_revision: expectedRevision, seen_summary_hash: seenSummaryHash }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function submitSimulationDraft(draftId: string, idempotencyKey: IdempotencyKey): Promise<SimulationOrder> {
  return request(() => client.post(`/simulation/drafts/${encodeURIComponent(draftId)}/submit`, undefined, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function fetchWatchlistGroups(): Promise<WatchlistGroup[]> {
  return request(() => client.get('/workspace/watchlists'))
}

export function createWatchlistGroup(input: Pick<WatchlistGroup, 'name' | 'description'>, idempotencyKey: IdempotencyKey): Promise<WatchlistGroup> {
  return request(() => client.post('/workspace/watchlists', input, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function updateWatchlistGroup(groupId: string, input: Pick<WatchlistGroup, 'name' | 'description' | 'revision'>, idempotencyKey: IdempotencyKey): Promise<WatchlistGroup> {
  return request(() => client.patch(`/workspace/watchlists/${encodeURIComponent(groupId)}`, { name: input.name, description: input.description, expected_revision: input.revision }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function deleteWatchlistGroup(groupId: string, expectedRevision: number, idempotencyKey: IdempotencyKey): Promise<{ group_id: string; deleted: boolean }> {
  return request(() => client.delete(`/workspace/watchlists/${encodeURIComponent(groupId)}`, { data: { expected_revision: expectedRevision }, headers: idempotencyHeaders(idempotencyKey) }))
}

export function fetchWatchlistInstruments(groupId: string): Promise<WatchlistInstrument[]> {
  return request(() => client.get(`/workspace/watchlists/${encodeURIComponent(groupId)}/instruments`))
}

export function addWatchlistInstrument(groupId: string, instrumentId: string, idempotencyKey: IdempotencyKey): Promise<WatchlistInstrument> {
  return request(() => client.post(`/workspace/watchlists/${encodeURIComponent(groupId)}/instruments`, { instrument_id: instrumentId }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function removeWatchlistInstrument(groupId: string, instrumentId: string, idempotencyKey: IdempotencyKey): Promise<{ group_id: string; instrument_id: string; removed: boolean }> {
  return request(() => client.delete(`/workspace/watchlists/${encodeURIComponent(groupId)}/instruments/${encodeURIComponent(instrumentId)}`, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function fetchResearchCandidates(): Promise<ResearchCandidateResponse> {
  return request(() => client.get('/workspace/candidates'))
}

export function ignoreResearchCandidate(instrumentId: string, reason: 'not_now' | 'already_covered' | 'disagree' | 'data_error', note: string | null, idempotencyKey: IdempotencyKey): Promise<{ instrument_id: string; reason: string; note: string | null }> {
  return request(() => client.post(`/workspace/candidates/${encodeURIComponent(instrumentId)}/ignore`, { reason, note }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function unignoreResearchCandidate(instrumentId: string, idempotencyKey: IdempotencyKey): Promise<{ instrument_id: string; ignored: boolean }> {
  return request(() => client.delete(`/workspace/candidates/${encodeURIComponent(instrumentId)}/ignore`, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function createTradePlanFromCandidate(instrumentId: string, idempotencyKey: IdempotencyKey): Promise<TradePlan> {
  return request(() => client.post('/trade-plans/from-candidate', { instrument_id: instrumentId }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function createTradePlanFromPortfolioDeviation(idempotencyKey: IdempotencyKey): Promise<TradePlan> {
  return request(() => client.post('/trade-plans/from-portfolio-deviation', undefined, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function fetchTradePlan(planId: string): Promise<TradePlan> {
  return request(() => client.get(`/trade-plans/${encodeURIComponent(planId)}`))
}

export function reviseTradePlan(planId: string, expectedRevision: number, actions: TradePlanActionRevision[], idempotencyKey: IdempotencyKey): Promise<TradePlan> {
  return request(() => client.post(`/trade-plans/${encodeURIComponent(planId)}/versions`, { expected_revision: expectedRevision, actions }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function confirmTradePlan(planId: string, expectedRevision: number, idempotencyKey: IdempotencyKey): Promise<TradePlan> {
  return request(() => client.post(`/trade-plans/${encodeURIComponent(planId)}/confirm-and-generate`, { expected_revision: expectedRevision }, { headers: idempotencyHeaders(idempotencyKey) }))
}
