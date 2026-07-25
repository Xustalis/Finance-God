import axios, { type AxiosError } from 'axios'
import { profileApi } from '@/api'
import type { ProfileWithRecommendations } from '@/types/api'
import { financeApiBase } from '@/services/apiBase'
import { expireBrowserSession, USER_SESSION } from '@/services/authSession'

// 交易台裸 JSON 域（/api/market、/api/simulation 等）。与 /api/v1 包络域使用
// 不同的基址变量：VITE_API_BASE_URL 属于 v1 客户端，两者默认值互斥，混用会
// 打断其中一方（见 api/client.ts 与 useRealtimeVoice）。
const client = axios.create({ baseURL: financeApiBase(), timeout: 30_000 })
export const DESK_AGENT_REQUEST_TIMEOUT_MS = 70_000

export class DeskApiError extends Error {
  constructor(
    message: string,
    public readonly code?: string,
    public readonly activeRunId?: string,
  ) {
    super(message)
  }
}

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('finance-god-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
client.interceptors.response.use(undefined, (error: AxiosError) => {
  if (error.response?.status === 401) expireBrowserSession(USER_SESSION)
  return Promise.reject(error)
})

export interface DeskQuote {
  symbol: string
  name: string
  trade_eligible?: boolean
  last: number | null
  open?: number | null
  high?: number | null
  low?: number | null
  previous_close?: number | null
  change: number | null
  change_percent: number | null
  volume?: number | null
  amount?: number | null
  provider: string
  provider_time: string
  frequency: string
  freshness: string
  market_status: string
  session_alignment?: string
}

export interface DeskMarketWarning {
  code: string
  message: string
  symbol?: string
}

export interface DeskMarketOverview {
  quotes: DeskQuote[]
  warnings: DeskMarketWarning[]
}

/** PandaData 常以字符串返回价格；统一成有限数字或 null。 */
export function parseMarketNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const numeric = typeof value === 'number' ? value : Number(String(value).trim())
  return Number.isFinite(numeric) ? numeric : null
}

export function normalizeDeskQuote(raw: Record<string, unknown>): DeskQuote {
  // 后端合同以比例传输涨跌幅（-0.0161 = -1.61%）；展示层统一收口为百分数。
  const changePercentRatio = parseMarketNumber(raw.change_percent)
  return {
    symbol: String(raw.symbol ?? ''),
    name: String(raw.name ?? raw.symbol ?? ''),
    trade_eligible: raw.trade_eligible === true,
    last: parseMarketNumber(raw.last),
    open: parseMarketNumber(raw.open),
    high: parseMarketNumber(raw.high),
    low: parseMarketNumber(raw.low),
    previous_close: parseMarketNumber(raw.previous_close),
    change: parseMarketNumber(raw.change),
    change_percent: changePercentRatio === null ? null : changePercentRatio * 100,
    volume: parseMarketNumber(raw.volume),
    amount: parseMarketNumber(raw.amount),
    provider: String(raw.provider ?? 'PandaData'),
    provider_time: String(raw.provider_time ?? ''),
    frequency: String(raw.frequency ?? ''),
    freshness: String(raw.freshness ?? 'unknown'),
    market_status: String(raw.market_status ?? 'unknown'),
    session_alignment: String(raw.session_alignment ?? ''),
  }
}

/**
 * 模拟草稿引用价门禁：与后端对齐——
 * 交易中或已发布收盘（released）且有有效最新价即可；
 * 允许 stale（收盘后缓存），拒绝无价或明确不可用。
 */
export function canUseQuoteAsDraftReference(
  quote: Pick<DeskQuote, 'last' | 'freshness' | 'market_status'> & { trade_eligible?: boolean },
): boolean {
  if (quote.trade_eligible === false) return false
  if (quote.last === null || quote.last <= 0) return false
  if (!['in_session', 'released'].includes(quote.market_status)) return false
  if (['error', 'unavailable', 'missing'].includes(quote.freshness)) return false
  return true
}

export function draftReferenceBlockedReason(
  quote: (Pick<DeskQuote, 'last' | 'freshness' | 'market_status'> & { trade_eligible?: boolean }) | null | undefined,
): string {
  if (!quote) return '该标的没有可用的真实行情，无法创建引用价格明确的订单草稿。'
  if (quote.trade_eligible === false) return '该标的是只读市场参考对象，不能用于创建模拟订单。'
  if (quote.last === null || quote.last <= 0) return '该标的没有可用的最新价，无法创建引用价格明确的订单草稿。'
  if (!['in_session', 'released'].includes(quote.market_status)) {
    return `该标的市场状态为 ${quote.market_status}，请等待交易中行情或已发布收盘价后再创建草稿。`
  }
  if (['error', 'unavailable', 'missing'].includes(quote.freshness)) {
    return `该标的行情新鲜度为 ${quote.freshness}，服务端未提供可用引用价。`
  }
  return `该标的行情状态为 ${quote.freshness}/${quote.market_status}，暂不可创建草稿。`
}

export interface DeskWorkflowRun {
  run_id: string
  status: 'queued' | 'running' | 'completed' | 'attention_required' | 'failed' | 'timed_out' | 'blocked'
    | 'cancel_requested' | 'cancelling' | 'cancelled' | 'expired'
  workflow_key: string
  workflow_version: string
  revision: number
  final_artifact?: VersionReference | null
  completed_node_artifacts?: VersionReference[]
  created_at?: string
  updated_at?: string
  errors?: readonly unknown[]
  request_intent?: string
  scope?: Record<string, string>
  requested_at?: string
  parent_run_id?: string | null
  retry_mode?: 'full' | 'resume_failed' | null
  resumed_from_node_id?: string | null
}

export interface DeskWorkflowProgress {
  run_id: string
  workflow_key: string
  workflow_version: string
  status: DeskWorkflowRun['status']
  revision: number
  updated_at: string
  total_node_count: number
  completed_node_artifact_count: number
  completed_node_artifacts: VersionReference[]
  nodes?: Array<{
    node_id: string
    title: string
    agent_ids: string[]
    service_id: string | null
    status: 'pending' | 'running' | 'completed' | 'failed' | 'timed_out' | 'reused'
    attempt: number | null
    updated_at: string | null
  }>
  errors: string[]
  is_terminal: boolean
}

export interface DeskAgentDecision {
  decision_id: string
  decision_source: 'agent_generated_policy_approved'
  mode: 'answer' | 'workflow'
  message: string
  workflow_key: string | null
  workflow_title: string | null
  routing_reason: string
  expected_stages: string[]
  can_start: boolean
  answer_text: string | null
  ui_actions: DeskProposedUiAction[]
}

export interface DeskAgentPreview {
  mode: 'answer' | 'workflow'
  workflow_key: string | null
  workflow_title: string | null
  expected_roles: string[]
  artifact_types: string[]
  can_start: boolean
}

export interface DeskProposedUiAction {
  action_id: string
  parameters: Record<string, string>
  context_version: string
}

export interface DeskDirectAnswer {
  run_id: string
  plan: {
    assignments: Array<{ agent_id: string; reason: string }>
  }
  results: Array<{
    agent_id: string
    summary: string
    claims: Array<{
      kind: string
      statement: string
      evidence_ids: string[]
      unknowns: string[]
      invalidation_conditions: string[]
    }>
    proposed_actions: string[]
  }>
}

export interface DeskEvidenceClaim {
  kind: string
  statement: string
  author_agent_id: string | null
  evidence_ids: string[]
  unknowns: string[]
  invalidation_conditions: string[]
}

export interface DeskEvidenceBundle {
  object_type: string
  object_id: string
  version: string
  subject: string
  conclusion: string | null
  provider: string
  generated_at: string
  facts: DeskEvidenceClaim[]
  inferences: DeskEvidenceClaim[]
  counterpoints: string[]
  unknowns: string[]
  invalidation_conditions: string[]
  sources: Array<{ identifier: string; source: string; excerpt: string | null }>
  agent_nodes: Array<{ agent_id: string; reason: string | null }>
  notices: Array<{
    agent_id: string
    reason: string
    missing_resources: string[]
    missing_authorizations: string[]
  }>
}

export type DeskSectionKey = 'information' | 'portfolio' | 'watchlist' | 'trading' | 'review'

export interface DeskUiActionDescriptor {
  id: string
  object: string
  mutation: string
  descriptor_version: string
}

export interface DeskProfileProjection {
  version: number | null
  archetype_code: string | null
  archetype_title: string | null
  risk_level: string | null
  loss_tolerance_percent: number | null
  confidence: number | null
  completeness: number | null
  education_only: boolean | null
  selected_direction: string | null
  recommended_directions: string[]
  projection_version: string
  available: boolean
  degraded: boolean
}

export interface DeskBootstrap {
  owner_id: string
  section: DeskSectionKey
  symbol: string
  context_version: string
  profile_projection: DeskProfileProjection
  ui_action_catalog: DeskUiActionDescriptor[]
  /** Live probe results only — missing/false means not proven available. */
  capabilities: Record<string, boolean>
  generated_at: string
}

export type QuickCommandStage = 'initial' | 'after_answer' | 'after_workflow'

export interface QuickCommandResponse {
  quick_commands: string[]
  quick_commands_error: string | null
  generated_at: string
}

/** Capability is usable only when the server explicitly reported True. */
export function isDeskCapabilityEnabled(
  capabilities: Record<string, boolean> | null | undefined,
  key: string,
): boolean {
  return capabilities?.[key] === true
}

export interface DeskNotification {
  notification_id: string
  severity: string
  title: string
  message: string
  created_at: string
  status: string
  required?: boolean
  details?: Record<string, string>
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

export interface DeskFactBatch {
  provider: string
  fact_kind: 'company_disclosure' | 'margin_balance'
  symbol: string
  requested_at: string
  generated_at?: string
  data_mode?: 'real' | 'mock'
  fallback_reason?: string | null
  trade_eligible?: false
  facts: DeskFact[]
}

export interface DeskMarketNewsItem {
  id: string
  title: string
  summary: string
  source: string
  url: string | null
  publish_time: string | null
  sector: string | null
  tags: string[]
}

export interface DeskMarketNewsBatch {
  provider: string
  data_mode: 'real'
  trade_eligible: false
  requested_at: string
  fetched_at: string
  freshness: {
    status: 'fresh' | 'stale'
    age_seconds: number
    ttl_seconds: number
    cached: boolean
  }
  items: DeskMarketNewsItem[]
  warnings: string[]
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
  simulation_time: string | null
}

export interface SimulationClock {
  account_id: string
  current_time: string
  speed: 1
  status: 'running' | 'paused_market_closed'
  session_close_at: string
  next_session_open_at: string
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
  episode_id?: string
  decision_snapshot_id?: string
  review_triggered?: boolean
}

export type TradeEpisodeStatus = 'open' | 'closed_pending_review' | 'review_completed' | 'review_failed'
export type TradeReviewStatus = 'pending' | 'completed' | 'failed'

export interface TradeEpisode {
  episode_id: string
  owner_id: string
  account_id: string
  instrument_id: string
  status: TradeEpisodeStatus
  review_status: TradeReviewStatus | null
  opened_at: string
  closed_at: string | null
  opening_quantity: string
  current_quantity: string
  revision: number
  created_at: string
  updated_at: string
}

export interface TradeDecisionField {
  status: 'available' | 'unavailable'
  value: string | null
  unavailable_reason: string | null
}

export interface TradeDecisionSnapshot {
  snapshot_id: string
  episode_id: string
  order_id: string
  fill_id: string
  instrument_id: string
  side: string
  quantity: string
  price: string
  fee: string
  occurred_at: string
  market_evidence: Record<string, string>
  profile_version: number | null
  thesis: TradeDecisionField
  expected_return: TradeDecisionField
  primary_risks: TradeDecisionField
  contrary_evidence: TradeDecisionField
  expected_holding_period: TradeDecisionField
  confidence: TradeDecisionField
}

export interface TradeReview {
  review_id: string
  episode_id: string
  status: TradeReviewStatus
  kind: 'interim' | 'final'
  expected_return_assessment: string
  actual_return_rmb: string
  actual_return_percent: string | null
  holding_period_seconds: number
  execution_assessment: string
  established_points: string[]
  failed_points: string[]
  unknown_points: string[]
  next_adjustments: string[]
  evidence_references: Array<Record<string, string>>
  profile_feedback_id: string | null
  error: string | null
  completed_at: string | null
}

export type AgentLearningStatus = 'healthy' | 'stale' | 'unavailable' | 'error'

export interface AgentLearningSummary {
  status: AgentLearningStatus
  message: string | null
  last_cycle: {
    cycle: number
    topic: string
    status: string
    started_at: string | null
    completed_at: string | null
    summary: string | null
  } | null
  snapshot: {
    version: number
    total_lessons: number
    topics: Record<string, number>
    updated_at: string
  } | null
  recent_verified_lessons: Array<{
    lesson_id: string
    statement: string
    topic: string
    validation_method: string | null
    cycle: number
    created_at: string
    tags: string[]
    invalidation_conditions: string[]
  }>
  freshness: {
    configured_interval_seconds: number
    age_seconds: number | null
    is_stale: boolean
  }
}

export interface ImmediateMarketOrderInput {
  account_id: string
  instrument_id: string
  side: 'buy' | 'sell'
  quantity: string
  market_mode: 'live' | 'historical'
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
  profile_version: number | null
  directions: string[]
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
      order_type?: 'market' | 'limit'
      quantity: string | null
      limit_price?: string | null
      rationale?: string
      included: boolean
    }>
  }
  source_type: string
  source_id: string
  capabilities: Array<{ action: string; enabled: boolean; reason?: string | null }>
  history: Array<{ revision: number }>
  [key: string]: unknown
}

export function apiError(error: unknown): DeskApiError {
  if (axios.isAxiosError(error)) {
    const responseError = error.response?.data?.error
    const message = responseError?.message || error.response?.data?.detail
    const code = responseError?.code
    const activeRunId = responseError?.active_run_id
    const text = typeof message === 'string'
      ? message
      : error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT'
        ? 'Agent 服务响应超时，请重新连接'
        : error.message
    return new DeskApiError(
      typeof code === 'string' ? `${code} · ${text}` : text,
      typeof code === 'string' ? code : undefined,
      typeof activeRunId === 'string' ? activeRunId : undefined,
    )
  }
  return new DeskApiError(error instanceof Error ? error.message : '请求失败')
}

async function request<T>(call: () => Promise<{ data: T }>): Promise<T> {
  try { return (await call()).data } catch (error) { throw apiError(error) }
}

async function envelopedRequest<T>(call: () => Promise<{ data: { success: boolean; data: T; error?: { message?: string } } }>): Promise<T> {
  const envelope = await request(call)
  if (!envelope.success) throw new DeskApiError(envelope.error?.message || '请求失败')
  return envelope.data
}

function idempotencyHeaders(idempotencyKey: IdempotencyKey): { 'Idempotency-Key': IdempotencyKey } {
  return { 'Idempotency-Key': idempotencyKey }
}

export async function fetchMarketOverview(symbols: readonly string[]): Promise<DeskMarketOverview> {
  const result = await request<{
    data?: { quotes?: Array<Record<string, unknown>> }
    quotes?: Array<Record<string, unknown>>
    warnings?: DeskMarketWarning[]
  }>(
    () => client.get('/market/overview', { params: { symbols: symbols.join(',') } }),
  )
  const raw = result.data?.quotes ?? result.quotes ?? []
  return {
    quotes: raw.map((item) => normalizeDeskQuote(item)),
    warnings: result.warnings ?? [],
  }
}

export async function fetchSimulationMarketOverview(symbols: readonly string[]): Promise<DeskMarketOverview> {
  const result = await request<{
    data?: { quotes?: Array<Record<string, unknown>> }
    warnings?: DeskMarketWarning[]
  }>(
    () => client.get('/simulation/market/overview', { params: { symbols: symbols.join(',') } }),
  )
  return {
    quotes: (result.data?.quotes ?? []).map((item) => normalizeDeskQuote(item)),
    warnings: result.warnings ?? [],
  }
}

export function completedFinancialQuarterRange(now = new Date()): {
  startQuarter: string
  endQuarter: string
} {
  const currentYear = now.getUTCFullYear()
  const currentQuarter = Math.floor(now.getUTCMonth() / 3) + 1
  const endQuarterNumber = currentQuarter === 1 ? 4 : currentQuarter - 1
  const endYear = currentQuarter === 1 ? currentYear - 1 : currentYear
  const startQuarterNumber = endQuarterNumber === 1 ? 4 : endQuarterNumber - 1
  const startYear = endQuarterNumber === 1 ? endYear - 1 : endYear
  return {
    startQuarter: `${startYear}q${startQuarterNumber}`,
    endQuarter: `${endYear}q${endQuarterNumber}`,
  }
}

export interface DeskBar {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount?: number
  freshness?: string
}

function finiteBarNumber(value: unknown, field: string): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) {
    throw new DeskApiError(`K线字段 ${field} 不是有效数字`)
  }
  return parsed
}

export function normalizeDeskBars(rawBars: readonly Record<string, unknown>[]): DeskBar[] {
  const byTime = new Map<number, DeskBar>()
  for (const raw of rawBars) {
    const time = String(raw.time ?? '').trim()
    const timestamp = Date.parse(time)
    if (!time || !Number.isFinite(timestamp)) {
      throw new DeskApiError('K线时间不是有效时间')
    }
    byTime.set(timestamp, {
      time: new Date(timestamp).toISOString(),
      open: finiteBarNumber(raw.open, 'open'),
      high: finiteBarNumber(raw.high, 'high'),
      low: finiteBarNumber(raw.low, 'low'),
      close: finiteBarNumber(raw.close, 'close'),
      volume: finiteBarNumber(raw.volume, 'volume'),
      ...(raw.amount == null ? {} : { amount: finiteBarNumber(raw.amount, 'amount') }),
      ...(typeof raw.freshness === 'string' ? { freshness: raw.freshness } : {}),
    })
  }
  return [...byTime.entries()]
    .sort(([left], [right]) => left - right)
    .map(([, bar]) => bar)
}

export function assertBarFrequency(requested: string | undefined, actual: unknown): void {
  if (!requested) return
  const normalizedActual = String(actual ?? '').trim().toLowerCase()
  const accepted = requested === 'daily'
    ? new Set(['daily', '1d', '日频'])
    : new Set(['1m', '1min', '1分钟'])
  if (!accepted.has(normalizedActual)) {
    throw new DeskApiError(`K线频率不匹配：请求 ${requested}，服务端返回 ${normalizedActual || '未知频率'}`)
  }
}

export async function fetchBars(symbol: string, frequency?: string): Promise<DeskBar[]> {
  const params: Record<string, string> = { symbol }
  if (frequency) params.frequency = frequency
  const result = await request<{ frequency?: string; bars?: Array<Record<string, unknown>> }>(() =>
    client.get('/market/bars', { params })
  )
  assertBarFrequency(frequency, result.frequency)
  return normalizeDeskBars(result.bars ?? [])
}

export async function fetchSimulationBars(symbol: string, frequency = '1m'): Promise<DeskBar[]> {
  const result = await request<{ frequency?: string; bars?: Array<Record<string, unknown>> }>(() =>
    client.get('/simulation/market/bars', { params: { symbol, frequency } })
  )
  assertBarFrequency(frequency, result.frequency)
  return normalizeDeskBars(result.bars ?? [])
}

export function fetchInformationFacts(symbol: string): Promise<DeskFactBatch> {
  const range = completedFinancialQuarterRange()
  return request(() => client.get('/market/information-facts', {
    params: {
      symbol,
      start_quarter: range.startQuarter,
      end_quarter: range.endQuarter,
      limit: 4,
    },
  }))
}

export function fetchMarketNews(limit = 8, forceRefresh = false): Promise<DeskMarketNewsBatch> {
  return request(() => client.get('/market/news', {
    params: { limit, refresh: forceRefresh ? 1 : 0 },
  }))
}

export function fetchSentimentFacts(symbol: string): Promise<DeskFactBatch> {
  const end = new Date()
  const start = new Date(end)
  start.setUTCDate(start.getUTCDate() - 30)
  const compactDate = (value: Date) => value.toISOString().slice(0, 10).replace(/-/g, '')
  return request(() => client.get('/market/sentiment-facts', {
    params: {
      symbol,
      start_date: compactDate(start),
      end_date: compactDate(end),
      limit: 8,
    },
  }))
}

export async function fetchProfile(): Promise<ProfileWithRecommendations> {
  try {
    return await profileApi.latest()
  } catch (error) {
    if (error instanceof Error && (error.message === 'PROFILE_NOT_FOUND' || /not found|404|Investment profile/i.test(error.message))) {
      throw new Error('PROFILE_NOT_FOUND')
    }
    throw error
  }
}

export async function fetchDeskBootstrap(input?: {
  section?: DeskSectionKey
  symbol?: string
}): Promise<DeskBootstrap> {
  return request(() => client.get('/desk/bootstrap', {
    params: {
      section: input?.section,
      symbol: input?.symbol,
    },
  }))
}

export async function fetchNotifications(): Promise<DeskNotification[]> {
  const result = await request<DeskNotification[] | { notifications?: DeskNotification[] }>(() => client.get('/workspace/notifications'))
  if (Array.isArray(result)) return result
  return result?.notifications ?? []
}

export async function fetchNotificationHistory(input?: {
  limit?: number
  includeRead?: boolean
  cursor?: string
}): Promise<DeskNotification[]> {
  const result = await request<DeskNotification[] | { notifications?: DeskNotification[] }>(() =>
    client.get('/workspace/notifications/history', {
      params: {
        limit: input?.limit ?? 50,
        include_read: input?.includeRead ?? true,
        cursor: input?.cursor,
      },
    }),
  )
  if (Array.isArray(result)) return result
  return result?.notifications ?? []
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  await request(() => client.post(`/workspace/notifications/${encodeURIComponent(notificationId)}/read`))
}

export interface DeskUiActionReceipt {
  receipt: 'applied' | 'rejected' | 'stale_context'
  action_id: string
  reason: string | null
  owner_id: string
  parameters: Record<string, string>
  applied_at: string
}

export interface DeskUiActionCommand {
  actionId: string
  contextVersion: string
  parameters?: Record<string, string>
}

export async function applyDeskUiAction(input: DeskUiActionCommand): Promise<DeskUiActionReceipt> {
  return request(() =>
    client.post('/desk/ui-actions', {
      action_id: input.actionId,
      context_version: input.contextVersion,
      parameters: input.parameters ?? {},
    }),
  )
}

export async function decideDeskAgent(input: {
  message: string
  section: DeskSectionKey
  symbol: string
  contextVersion: string
  activeWorkflow: boolean
  orderDraft?: {
    id: string
    version: string
  }
}): Promise<DeskAgentDecision> {
  return request(() => client.post('/agent/desk/decision', {
    message: input.message,
    section: input.section,
    symbol: input.symbol,
    context_version: input.contextVersion,
    active_workflow: input.activeWorkflow,
    ...(input.orderDraft
      ? {
          order_draft_id: input.orderDraft.id,
          order_draft_version: input.orderDraft.version,
        }
      : {}),
  }, { timeout: DESK_AGENT_REQUEST_TIMEOUT_MS }))
}

export async function previewDeskAgent(input: {
  message: string
  section: DeskSectionKey
  symbol: string
  contextVersion: string
  activeWorkflow: boolean
  orderDraft?: {
    id: string
    version: string
  }
}): Promise<DeskAgentPreview> {
  return request(() => client.post('/agent/desk/preview', {
    message: input.message,
    section: input.section,
    symbol: input.symbol,
    context_version: input.contextVersion,
    active_workflow: input.activeWorkflow,
    ...(input.orderDraft
      ? {
          order_draft_id: input.orderDraft.id,
          order_draft_version: input.orderDraft.version,
        }
      : {}),
  }, { timeout: DESK_AGENT_REQUEST_TIMEOUT_MS }))
}

export async function streamDeskAgentDecision(
  input: Parameters<typeof decideDeskAgent>[0],
  onDelta: (delta: string) => void,
): Promise<DeskAgentDecision> {
  const token = localStorage.getItem('finance-god-token')
  const baseUrl = financeApiBase()
  const controller = new AbortController()
  const timeout = window.setTimeout(
    () => controller.abort(),
    DESK_AGENT_REQUEST_TIMEOUT_MS,
  )
  let response: Response
  try {
    response = await fetch(`${baseUrl}/agent/desk/decision/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/x-ndjson, application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal: controller.signal,
      body: JSON.stringify({
        message: input.message,
        section: input.section,
        symbol: input.symbol,
        context_version: input.contextVersion,
        active_workflow: input.activeWorkflow,
        ...(input.orderDraft
          ? {
              order_draft_id: input.orderDraft.id,
              order_draft_version: input.orderDraft.version,
            }
          : {}),
      }),
    })
  } catch (error) {
    window.clearTimeout(timeout)
    if (controller.signal.aborted) {
      throw new DeskApiError('Agent 服务响应超时，请重新连接', 'AI_STREAM_TIMEOUT')
    }
    throw error
  }
  try {
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as { error?: { message?: string; code?: string } } | null
      if (response.status === 401) expireBrowserSession(USER_SESSION)
      throw new DeskApiError(
        payload?.error?.message ?? `Agent 流式请求失败（HTTP ${response.status}）`,
        payload?.error?.code,
      )
    }
    if (response.headers.get('content-type')?.includes('application/json')) {
      try {
        return await response.json() as DeskAgentDecision
      } catch (error) {
        if (error instanceof SyntaxError) {
          throw new DeskApiError('Agent 返回了无法解析的 JSON 响应', 'AI_STREAM_INVALID_FRAME')
        }
        throw error
      }
    }
    if (!response.body) {
      throw new DeskApiError('Agent 流式响应没有可读取的正文', 'AI_STREAM_EMPTY')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let decision: DeskAgentDecision | null = null
    let answerText = ''
    let doneSeen = false

    type StreamEvent = {
      type: 'start' | 'delta' | 'done' | 'error'
      decision?: DeskAgentDecision
      text?: string
      answer_text?: string
      message?: string
      code?: string
    }

    function consumeLine(line: string) {
      if (!line.trim()) return
      let event: StreamEvent
      try {
        event = JSON.parse(line) as StreamEvent
      } catch {
        throw new DeskApiError('Agent 流式响应包含无法解析的数据帧', 'AI_STREAM_INVALID_FRAME')
      }
      if (event.type === 'start' && event.decision) decision = event.decision
      if (event.type === 'delta' && event.text) {
        answerText += event.text
        onDelta(event.text)
      }
      if (event.type === 'done') {
        doneSeen = true
        answerText = event.answer_text ?? answerText
      }
      if (event.type === 'error') throw new DeskApiError(event.message ?? 'Agent 流式生成失败', event.code)
    }

    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      lines.forEach(consumeLine)
      if (done) break
    }
    consumeLine(buffer)
    if (!doneSeen || !decision || !answerText.trim()) {
      throw new DeskApiError('Agent 流式响应未正常结束', 'AI_STREAM_INCOMPLETE')
    }
    return { ...(decision as DeskAgentDecision), answer_text: answerText.trim() }
  } catch (error) {
    if (controller.signal.aborted) {
      throw new DeskApiError('Agent 服务响应超时，请重新连接', 'AI_STREAM_TIMEOUT')
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}

export function fetchDeskQuickCommands(input: {
  stage: QuickCommandStage
  section: DeskSectionKey
  symbol: string
  contextVersion: string
  decisionId?: string
  runId?: string
}): Promise<QuickCommandResponse> {
  return request(() => client.post('/desk/quick-commands', {
    stage: input.stage,
    section: input.section,
    symbol: input.symbol,
    context_version: input.contextVersion,
    ...(input.decisionId ? { decision_id: input.decisionId } : {}),
    ...(input.runId ? { run_id: input.runId } : {}),
  }, { timeout: DESK_AGENT_REQUEST_TIMEOUT_MS }))
}

export async function runDeskDirectAnswer(message: string): Promise<DeskDirectAnswer> {
  return request(() => client.post('/agent/research', {
    subject: message,
    task_type: 'research',
    asset_kind: 'equity',
    max_agents: 1,
  }, { timeout: DESK_AGENT_REQUEST_TIMEOUT_MS }))
}

export async function createWorkflow(input: {
  intent: string
  section: DeskSectionKey
  symbol: string
  contextVersion: string
  idempotencyKey: string
  orderDraft?: {
    id: string
    version: string
  }
}): Promise<DeskWorkflowRun> {
  return request(() => client.post('/workflows/desk', {
    request_intent: input.intent,
    section: input.section,
    symbol: input.symbol,
    context_version: input.contextVersion,
    ...(input.orderDraft
      ? {
          order_draft_id: input.orderDraft.id,
          order_draft_version: input.orderDraft.version,
        }
      : {}),
  }, { headers: { 'Idempotency-Key': input.idempotencyKey } }))
}

export async function fetchWorkflow(runId: string): Promise<DeskWorkflowRun> {
  return request(() => client.get(`/workflows/${encodeURIComponent(runId)}`))
}

export interface DeskWorkflowHistoryPage {
  items: DeskWorkflowRun[]
  next_cursor: string | null
}

export async function fetchWorkflowHistory(input?: {
  cursor?: string | null
  limit?: number
  status?: DeskWorkflowRun['status'] | ''
}): Promise<DeskWorkflowHistoryPage> {
  return request(() => client.get('/workflows', {
    params: {
      limit: input?.limit ?? 20,
      ...(input?.cursor ? { cursor: input.cursor } : {}),
      ...(input?.status ? { status: input.status } : {}),
    },
  }))
}

export async function cancelWorkflow(runId: string, idempotencyKey: string): Promise<DeskWorkflowRun> {
  return request(() => client.post(
    `/workflows/${encodeURIComponent(runId)}/cancel`,
    {},
    { headers: { 'Idempotency-Key': idempotencyKey } },
  ))
}

export async function retryWorkflow(
  runId: string,
  mode: 'full' | 'resume_failed',
  idempotencyKey: string,
): Promise<DeskWorkflowRun> {
  return request(() => client.post(
    `/workflows/${encodeURIComponent(runId)}/retry`,
    { mode },
    { headers: { 'Idempotency-Key': idempotencyKey } },
  ))
}

export async function fetchWorkflowProgress(
  runId: string,
  options?: { afterRevision?: number; waitSeconds?: number; signal?: AbortSignal },
): Promise<DeskWorkflowProgress> {
  return request(() => client.get(`/workflows/${encodeURIComponent(runId)}/progress`, {
    params: options?.afterRevision === undefined
      ? undefined
      : {
          after_revision: options.afterRevision,
          wait_seconds: options.waitSeconds ?? 20,
        },
    signal: options?.signal,
  }))
}

export async function fetchWorkflowEvidence(reference: VersionReference): Promise<DeskEvidenceBundle> {
  return request(() => client.get(
    `/evidence/${encodeURIComponent(reference.object_type)}/${encodeURIComponent(reference.object_id)}`,
    { params: { version: reference.version, tier: 'advanced' } },
  ))
}

export function fetchSimulationAccount(): Promise<SimulationAccount | null> {
  return request(() => client.get('/simulation/accounts/current'))
}

export function createSimulationAccount(initialCashRmb: string, simulationStartAt: string, idempotencyKey: IdempotencyKey): Promise<SimulationAccount> {
  return request(() => client.post('/simulation/accounts', {
    initial_cash_rmb: initialCashRmb,
    simulation_start_at: simulationStartAt,
  }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function resetSimulationAccount(accountId: string, initialCashRmb: string, simulationStartAt: string, idempotencyKey: IdempotencyKey): Promise<SimulationAccount> {
  return request(() => client.post(`/simulation/accounts/${encodeURIComponent(accountId)}/reset`, {
    initial_cash_rmb: initialCashRmb,
    simulation_start_at: simulationStartAt,
  }, { headers: idempotencyHeaders(idempotencyKey) }))
}

export function fetchSimulationClock(): Promise<SimulationClock> {
  return request(() => client.get('/simulation/clock'))
}

export function resumeSimulationClock(expectedRevision: number, idempotencyKey: IdempotencyKey): Promise<SimulationClock> {
  return request(() => client.post('/simulation/clock/resume-next-session', {
    expected_revision: expectedRevision,
  }, { headers: idempotencyHeaders(idempotencyKey) }))
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
  return request(() => client.post(
    `/simulation/drafts/${encodeURIComponent(draftId)}/submit`,
    {},
    { headers: idempotencyHeaders(idempotencyKey) },
  ))
}

export function submitSimulationMarketOrder(input: ImmediateMarketOrderInput, idempotencyKey: IdempotencyKey): Promise<SimulationOrder> {
  return request(() => client.post(
    '/simulation/market-orders',
    input,
    { headers: idempotencyHeaders(idempotencyKey) },
  ))
}

export function fetchTradeEpisodes(filters: {
  instrumentId?: string
  status?: TradeEpisodeStatus
  reviewStatus?: TradeReviewStatus
} = {}): Promise<TradeEpisode[]> {
  return envelopedRequest(() => client.get('/trade-episodes', {
    params: {
      ...(filters.instrumentId ? { instrument_id: filters.instrumentId } : {}),
      ...(filters.status ? { status: filters.status } : {}),
      ...(filters.reviewStatus ? { review_status: filters.reviewStatus } : {}),
    },
  }))
}

export function fetchTradeEpisodeDecisions(episodeId: string): Promise<TradeDecisionSnapshot[]> {
  return envelopedRequest(() => client.get(`/trade-episodes/${encodeURIComponent(episodeId)}/decisions`))
}

export function fetchTradeEpisodeReview(episodeId: string): Promise<TradeReview> {
  return envelopedRequest(() => client.get(`/trade-episodes/${encodeURIComponent(episodeId)}/review`))
}

export function retryTradeEpisodeReview(episodeId: string, idempotencyKey: IdempotencyKey): Promise<TradeReview> {
  return envelopedRequest(() => client.post(
    `/trade-episodes/${encodeURIComponent(episodeId)}/review/retry`,
    {},
    { headers: idempotencyHeaders(idempotencyKey) },
  ))
}

export function fetchAgentLearningSummary(): Promise<AgentLearningSummary> {
  return request(() => client.get('/agent-learning/summary'))
}

export function reconcileSimulationOrder(orderId: string, idempotencyKey: IdempotencyKey): Promise<SimulationOrder> {
  return request(() => client.post(
    `/simulation/orders/${encodeURIComponent(orderId)}/reconcile`,
    {},
    { headers: idempotencyHeaders(idempotencyKey) },
  ))
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
