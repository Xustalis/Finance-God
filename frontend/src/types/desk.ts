/* ═══════════════════════════════════════════════════
   交易台 — 行情 / 仿真 / 工作区 类型
   与后端 server.py + market_data/service.py 对齐
   ═══════════════════════════════════════════════════ */

// ─── 行情（PandaData） ────────────────────────────

export interface MarketQuote {
  symbol: string
  name: string
  asset_type: string
  market: string
  currency: string
  last: number
  open: number
  high: number
  low: number
  previous_close: number | null
  change: number | null
  change_percent: number | null
  volume: number
  amount: number | null
  provider: string
  provider_time: string
  retrieved_at: string
  frequency: string
  freshness: 'current' | 'stale' | 'not_released' | 'unknown'
  market_status: 'in_session' | 'closed_pending' | 'released' | 'unknown'
  source_endpoint: string
  capability_version: string
  instrument_master_identity: string
  instrument_master_version: string
  /** PandaData live-trading eligibility; simulation support is a separate UI rule. */
  trade_eligible: false
}

export interface QuoteBatch {
  provider: string
  requested_at: string
  cache_hit: boolean
  quotes: MarketQuote[]
  errors: Record<string, string>
  diagnostics: DataDiagnostic[]
  quality: Record<string, QualityDecision>
}

export interface MarketOverviewView {
  object: {
    type: 'market_overview'
    id: string
    symbols: string[]
  }
  data: {
    quotes: MarketQuote[]
    signal: {
      tendency: 'positive' | 'cautious' | 'neutral' | 'unavailable'
      tendency_label: string
      consistency_percent: number | null
      definition: string
    }
    forces: Array<{
      code: 'leader' | 'laggard' | 'average_change' | 'volume_leader'
      label: string
    }>
    indicators: Array<{
      code: 'advance_ratio' | 'change_dispersion' | 'average_change' | 'fresh_coverage'
      name: string
      value: number | null
      unit: 'percent' | 'percentage_points'
      definition: string
    }>
  }
  version: string
  algorithm_version: string
  generated_at: string
  data_status: {
    provider: string
    provider_time: string | null
    frequency: string | null
    freshness: 'fresh' | 'delayed' | 'stale' | 'unknown'
    last_success_at: string
  }
  warnings: Array<{
    code: string
    severity: 'info' | 'warning' | 'blocking'
    message: string
    affected_fields: string[]
  }>
}

export interface DataDiagnostic {
  scope: string
  code: string
  message: string
  endpoint?: string | null
}

export interface QualityDecision {
  decision: 'pass' | 'warn' | 'fail'
  reasons: string[]
}

export interface MarketBar {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number | null
  freshness: 'current' | 'stale' | 'not_released' | 'unknown'
  provider_time: string
  source_endpoint: string
  capability_version: string
  instrument_master_identity: string
  instrument_master_version: string
  trade_eligible: false
}

export interface BarsResponse {
  provider: string
  symbol: string
  frequency: string
  bars: MarketBar[]
  quality: QualityDecision
}

export interface CatalogDataset {
  name: string
  description?: string
  frequency?: string
  market?: string
  [key: string]: unknown
}

export interface CatalogResponse {
  provider: string
  summary: Record<string, unknown>
  datasets: CatalogDataset[]
}

// ─── 标的搜索（标的主数据） ─────────────────

export interface InstrumentSummary {
  symbol: string
  provider_symbol: string
  market: string
  asset_class: string
  currency: string
  aliases: string[]
  frequency: string
  simulation_supported: boolean
}

export interface InstrumentSearchResponse {
  provider: string
  query: string
  instrument_master_identity: string
  instrument_master_version: string
  instruments: InstrumentSummary[]
}

// ─── 健康检查 ─────────────────────────────────────

export interface HealthResponse {
  liveness: string
  readiness: 'ready' | 'not_ready'
  readiness_reason: string
  market_data: string
  account_mode: string
}

// ─── 仿真交易 ─────────────────────────────────────

export interface SimulationAccount {
  account_id: string
  owner_id: string
  status: string
  cash_total_rmb: number
  cash_available_rmb: number
  cash_frozen_rmb: number
  margin_rmb: number
  revision: number
}

export interface VersionReference {
  object_type: string
  object_id: string
  version: string
}

// ─── 交易计划（T04）──────────────────────────────

export type TradePlanStatus =
  | 'draft'
  | 'pending_review'
  | 'confirmed'
  | 'executing'
  | 'partially_completed'
  | 'completed'
  | 'expired'
  | 'rejected'
  | 'cancelled'

export interface TradePlanAction {
  action_id: string
  instrument_id: string
  side: 'buy' | 'sell'
  order_type: 'market' | 'limit'
  quantity: number | null
  limit_price: number | null
  reference_price: number | null
  time_in_force: TimeInForce
  included: boolean
  rationale: string
}

export interface TradePlan {
  plan_id: string
  account_id: string
  revision: number
  status: TradePlanStatus
  purpose: string
  actions: TradePlanAction[]
  estimated_fee_rmb: number
  portfolio_impact: string
  disagreements: string[]
  workflow_dependencies: unknown[]
  expires_at: string
  input_versions: VersionReference[]
  invalidated_by_versions: VersionReference[]
  audit_reference: AuditReference
}

export interface TradePlanCapability {
  action: 'save_version' | 'confirm_and_generate'
  enabled: boolean
  reason_code: string | null
  reason: string | null
}

export interface TradePlanPageView {
  object: TradePlan
  source_type: 'candidate' | 'portfolio_deviation'
  source_id: string
  version: string
  generated_at: string
  data_status: {
    provider: string
    provider_time: string | null
    frequency: string | null
    freshness: 'fresh' | 'delayed' | 'stale' | 'unknown'
    last_success_at: string | null
  }
  capabilities: TradePlanCapability[]
  warnings: Array<{
    code: string
    severity: 'info' | 'warning' | 'blocking'
    message: string
    affected_fields: string[]
  }>
  draft_links: Array<{
    action_id: string
    draft_id: string
    draft_revision: number
  }>
  history: Array<{
    revision: number
    status: TradePlanStatus
    recorded_at: string
    actor_id: string
  }>
}

export interface TradePlanActionRevision {
  action_id: string
  quantity: number | null
  included: boolean
}

export interface AuditReference {
  audit_id: string
  actor_id: string
  recorded_at: string
}

export type OrderSide = 'buy' | 'sell'
export type OrderType = 'market' | 'limit'
export type TimeInForce = 'day' | 'good_til_cancelled' | 'immediate_or_cancel'
export type RiskStatus = 'checking' | 'passed' | 'confirmation_required' | 'blocked' | 'expired'

export interface OrderDraftCreate {
  mode: 'manual'
  account_id: string
  instrument_id: string
  side: OrderSide
  order_type: OrderType
  quantity: number
  amount: null
  limit_price: number | null
  reference_price: number | null
  time_in_force: TimeInForce
  fund_rule_version: null
  valid_until: string
  input_versions: VersionReference[]
  plan_reference: null
}

export interface RiskReason {
  code: string
  severity: 'soft' | 'hard'
  message: string
}

export interface RiskCheckResult {
  risk_check_id: string
  revision: number
  status: RiskStatus
  reasons: RiskReason[]
  reason_hash: string
  checked_at: string
  expires_at: string
  soft_confirmation: Record<string, unknown> | null
  order_version: VersionReference
  rule_version: VersionReference
  input_versions: VersionReference[]
  audit_reference: Record<string, unknown>
}

/** 后端计算的下单前成本估算（金额/手续费/总支出）。前端仅展示，不自行计算。 */
export interface CostEstimate {
  reference_price: number
  price_source: 'limit_price' | 'market_reference'
  quantity: number
  notional: number
  fee: number
  total: number
  cash_flow: 'outflow' | 'inflow'
  fee_bps: number
  slippage_bps: number
  currency: string
  rule_version: string
}

export interface StoredDraft {
  record_revision: number
  owner_id: string
  mode: 'manual' | 'planned'
  draft: {
    draft_id: string
    revision: number
    status: 'draft' | 'pending_review' | 'confirmed' | 'expired' | 'cancelled'
    account_id: string
    instrument_id: string
    side: string
    order_type: string
    quantity: number | null
    amount: number | null
    limit_price: number | null
    time_in_force: string | null
    fund_rule_version: VersionReference | null
    valid_until: string
    input_versions: VersionReference[]
    audit_reference: Record<string, unknown>
  }
  plan_reference: VersionReference | null
  reference_price: number | null
  review: {
    succeeded: boolean
    summary: string | null
    error: string | null
  } | null
  risk_result: RiskCheckResult | null
  cost_estimate: CostEstimate | null
  immutable_summary_hash: string | null
  confirmed_at: string | null
}

export interface StoredOrder {
  owner_id: string
  draft_reference: VersionReference
  exchange_order: ExchangeOrder | null
  fund_order: FundOrder | null
  execution_error: string | null
}

export interface ExchangeOrder {
  order_id: string
  revision: number
  status:
    | 'submitting'
    | 'unknown'
    | 'accepted'
    | 'partially_filled'
    | 'filled'
    | 'cancelling'
    | 'cancelled'
    | 'rejected'
    | 'expired'
  idempotency_key: string
  draft_reference: VersionReference
  quantity: number
  cumulative_filled: number
  audit_reference: AuditReference
}

export interface FundOrder {
  order_id: string
  revision: number
  status:
    | 'draft'
    | 'pending_review'
    | 'submitted'
    | 'accepted'
    | 'pending_nav'
    | 'confirming'
    | 'confirmed'
    | 'partially_confirmed'
    | 'cancelled'
    | 'rejected'
  idempotency_key: string
  draft_reference: VersionReference
  requested_amount: number | null
  requested_units: number | null
  audit_reference: AuditReference
}

export interface SimulationFill {
  fill_id: string
  order_id: string
  account_id: string
  instrument_id: string
  /** originating draft side; older fills persisted before this field may be null. */
  side: OrderSide | null
  quantity: number
  price: number
  fee: number
  slippage_bps: number
  market_evidence: VersionReference
  model_version: string
  rule_version: string
  occurred_at: string
  ledger_fill_id: string
}

/** 持仓 projection（后端只出数量与成本，市值/浮盈由前端用实时行情计算）。 */
export interface SimulationPosition {
  account_id: string
  instrument_id: string
  currency: string
  long_quantity: number
  settled_quantity: number
  frozen_quantity: number
  cost_rmb: number
  revision: number
}

// ─── 权威持仓与估值（GET /simulation/portfolio） ───
// 后端只给出数量、成本、已实现盈亏等“事实”；市值与浮动盈亏由前端
// 用已轮询的实时行情（market store）乘以数量计算，不与仿真事实混存。

export interface PortfolioPosition {
  instrument_id: string
  currency: string
  quantity: number
  settled_quantity: number
  frozen_quantity: number
  available_quantity: number
  cost_basis_rmb: number
  average_cost_rmb: number | null
  realized_pnl_rmb: number
  revision: number
}

export interface PortfolioView {
  account_id: string
  owner_id: string
  as_of: string
  rule_version: string
  positions: PortfolioPosition[]
  realized_pnl_rmb: number
}

// ─── 订单执行视图（GET /simulation/orders 及 /orders/{id}） ───
// 完整订单字段 + 状态时间线，供执行中心对账与异常查询。

export type ExchangeOrderStatus =
  | 'submitting'
  | 'unknown'
  | 'accepted'
  | 'partially_filled'
  | 'filled'
  | 'cancelling'
  | 'cancelled'
  | 'rejected'
  | 'expired'

export interface OrderTimelineEntry {
  status: string
  occurred_at: string
  actor_id: string
  detail: string | null
}

export interface StoredOrderView {
  order_id: string
  owner_id: string
  order_kind: 'exchange' | 'fund'
  status: ExchangeOrderStatus
  instrument_id: string
  side: string
  order_type: string
  time_in_force: string | null
  limit_price: number | null
  quantity: number
  cumulative_filled: number
  remaining_quantity: number
  average_fill_price: number | null
  total_fee_rmb: number
  filled_notional_rmb: number
  revision: number
  confirmed_at: string | null
  updated_at: string
  draft_reference: VersionReference
  execution_error: string | null
  fills: SimulationFill[]
  timeline: OrderTimelineEntry[]
}

// ─── 决策收件箱（GET /simulation/decision-inbox） ───
// 聚合订单异常与未读通知，按 P0-P3 优先级排序；不创造待办。

export type DecisionPriority = 'P0' | 'P1' | 'P2' | 'P3'

export interface DecisionInboxItem {
  item_id: string
  priority: DecisionPriority
  kind: 'order' | 'notification'
  category: string
  title: string
  detail: string
  source_object_type: string
  source_object_id: string
  occurred_at: string
  required: boolean
  action_route: string | null
}

export interface DecisionInboxCounts {
  p0: number
  p1: number
  p2: number
  p3: number
  total: number
}

export interface DecisionInboxView {
  owner_id: string
  as_of: string
  counts: DecisionInboxCounts
  items: DecisionInboxItem[]
}

// ─── 工作区 ───────────────────────────────────────

export interface WatchlistGroup {
  group_id: string
  owner_user_id: string
  name: string
  description: string | null
  revision: number
  created_at: string
  updated_at: string
  instruments?: WatchlistInstrument[]
}

export interface WatchlistInstrument {
  instrument_id: string
  added_by: string
  added_at: string
}

export interface NotificationPreference {
  owner_user_id: string
  category_preferences: Record<string, boolean>
  updated_at: string
}

// ─── 错误 ─────────────────────────────────────────

export interface BackendError {
  error: {
    code: string
    message: string
    trace_id?: string
  }
}

// ─── AI 研究运行（Multi-Agent 运行时） ────────────
// 与后端 research_runtime.contracts.AgentRun 对齐；所有结论均来自真实
// Agent 运行，不在前端派生或伪造。

export interface AgentEvidence {
  identifier: string
  source: string
  excerpt: string
}

export interface AgentClaim {
  claim_id: string
  author_agent_id: string
  kind: 'fact' | 'inference'
  statement: string
  evidence_ids: string[]
  unknowns: string[]
  invalidation_conditions: string[]
}

export interface AgentResult {
  agent_id: string
  summary: string
  claims: AgentClaim[]
  evidence: AgentEvidence[]
  proposed_actions: string[]
  metadata: Record<string, unknown>
}

export interface AgentAssignment {
  agent_id: string
  reason: string
}

export interface AgentRoutingNotice {
  agent_id: string
  reason: string
  missing_resources: string[]
  missing_authorizations: string[]
}

export interface AgentRun {
  run_id: string
  plan: {
    run_id: string
    assignments: AgentAssignment[]
    notices: AgentRoutingNotice[]
  }
  results: AgentResult[]
}

export interface AgentResearchRequest {
  subject: string
  task_type?: string
  asset_kind?: 'equity' | 'fund' | 'portfolio' | 'market' | 'software' | 'other'
  scope?: string
  evidence?: AgentEvidence[]
  max_agents?: number
}

// ─── 过程与证据（T10 只读抽屉 / 高级页） ──────────
// 与后端 finance_god.application.evidence_service 对齐；证据仅镜像运行时
// 已产出的结论内容，按 (object_type, object_id, version) 不可变存储。

export type EvidenceTier = 'normal' | 'advanced' | 'internal'

export interface EvidenceClaim {
  kind: 'fact' | 'inference'
  statement: string
  author_agent_id: string | null
  evidence_ids: string[]
  unknowns: string[]
  invalidation_conditions: string[]
}

export interface EvidenceSource {
  identifier: string
  source: string
  excerpt: string | null
}

export interface EvidenceNode {
  agent_id: string
  reason: string | null
}

export interface EvidenceNotice {
  agent_id: string
  reason: string
  missing_resources: string[]
  missing_authorizations: string[]
}

export interface EvidenceView {
  object_type: string
  object_id: string
  version: string
  subject: string
  conclusion: string | null
  provider: string
  generated_at: string
  tier: EvidenceTier
  facts: EvidenceClaim[]
  inferences: EvidenceClaim[]
  counterpoints: string[]
  unknowns: string[]
  invalidation_conditions: string[]
  sources: EvidenceSource[]
  agent_nodes: EvidenceNode[]
  notices: EvidenceNotice[]
  error_trace: string | null
}

export interface EvidenceLineageInput {
  object_type: string
  object_id: string
  version: string
}

export interface EvidenceLineageView {
  object_type: string
  object_id: string
  version: string
  provider: string
  generated_at: string
  inputs: EvidenceLineageInput[]
  sources: EvidenceSource[]
}

export interface EvidenceVersionSummary {
  version: string
  subject: string
  conclusion: string | null
  provider: string
  generated_at: string
}

export interface EvidenceFieldDiff {
  field: string
  added: string[]
  removed: string[]
}

export interface EvidenceCompareView {
  object_type: string
  object_id: string
  base: EvidenceVersionSummary
  other: EvidenceVersionSummary
  diffs: EvidenceFieldDiff[]
}

export interface EvidenceExportView {
  object_type: string
  object_id: string
  exported_at: string
  tier: EvidenceTier
  versions: EvidenceVersionSummary[]
  bundle: EvidenceView
}

// ─── 工作区：自选与候选（T02） ─────────────────────

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
  instrument_id: string
  group_id: string
  revision: number
  added_at: string
  added_by: string
}

/** 五维评分的独立维度键（无综合分）。 */
export type CandidateDimensionKey =
  | 'portfolio_fit'
  | 'risk'
  | 'cost'
  | 'liquidity'
  | 'evidence'

/** 维度评级；missing 表示数据不足，必须显式呈现而非猜测。 */
export type CandidateRating = 'strong' | 'adequate' | 'weak' | 'missing'

export interface CandidateDimension {
  dimension: CandidateDimensionKey
  label: string
  rating: CandidateRating
  detail: string
  metrics: Record<string, string>
  missing_fields: string[]
}

export interface CandidateExclusion {
  reason_code: string
  detail: string
}

export interface Candidate {
  instrument_id: string
  symbol: string
  name: string | null
  asset_type: string | null
  market: string | null
  currency: string | null
  direction: string
  direction_label: string
  purpose: string
  dimensions: CandidateDimension[]
  exclusions: CandidateExclusion[]
  tradable: boolean
  ignored: boolean
  ignore_reason: string | null
  as_of: string | null
  provider: string | null
}

export interface CandidateResponse {
  generated_at: string
  rule_version: string
  purpose_summary: string
  candidates: Candidate[]
  /** 非 null 时表示行情等上游不可用，需显式降级呈现。 */
  unavailable_reason: string | null
}

export type CandidateIgnoreReason =
  | 'not_now'
  | 'already_covered'
  | 'disagree'
  | 'data_error'

// ─── 交易授权 / 投资授权（T00，仿真业务数据） ─────
// 与后端 finance_god/trading/mandate.py + api/mandate_routes.py 对齐。
// 授权为仿真业务数据（非真实经纪商），金额/比率以字符串（Decimal）传输。

export type AutonomyLevel = 'L0' | 'L1' | 'L2'
export type MandateStatus = 'active' | 'paused' | 'revoked' | 'expired'

/** 授权限额（Decimal 以字符串传输，前端仅展示与回传，不自行改写精度）。 */
export interface MandateLimits {
  max_single_order_amount: string
  max_daily_turnover_amount: string
  max_single_asset_ratio: string
  max_broad_etf_ratio: string
  max_otc_fund_ratio: string
  max_industry_ratio: string
  max_gross_ratio: string
  max_short_gross_ratio: string
  max_single_short_ratio: string
  max_price_deviation_ratio: string
  max_all_in_cost_ratio: string
  max_slippage_bps: string
}

export interface InvestmentMandate {
  mandate_id: string
  owner_user_id: string
  version: number
  status: MandateStatus
  autonomy_level: AutonomyLevel
  allowed_markets: string[]
  allowed_assets: string[]
  allowed_sides: string[]
  allowed_order_types: string[]
  short_markets: string[]
  limits: MandateLimits
  valid_from: string
  valid_until: string
  created_at: string
  created_by: string
  note: string | null
}

/** 保存新版本授权的提交体（乐观并发用 expected_revision）。 */
export interface MandateSavePayload {
  expected_revision: number
  autonomy_level: AutonomyLevel
  allowed_markets: string[]
  allowed_assets: string[]
  allowed_sides: string[]
  allowed_order_types: string[]
  short_markets: string[]
  limits: MandateLimits
  valid_until: string
  note: string | null
}

export interface MandateImpactFinding {
  code: string
  message: string
}

export interface MandateImpactedOrder {
  reference: string
  instrument_id: string
  side: string
  order_type: string
  findings: MandateImpactFinding[]
}

export interface MandateImpact {
  evaluated: number
  affected: MandateImpactedOrder[]
}

// ─── 前端辅助 ─────────────────────────────────────

export type Direction = 'up' | 'down' | 'flat'

export function directionOf(quote: MarketQuote): Direction {
  if (quote.change === null || quote.change === 0) return 'flat'
  return quote.change > 0 ? 'up' : 'down'
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const pct = (value * 100).toFixed(2)
  return value > 0 ? `+${pct}%` : `${pct}%`
}

export function formatChange(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const v = value.toFixed(2)
  return value > 0 ? `+${v}` : v
}

export function formatNumber(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined) return '—'
  return value.toFixed(decimals)
}

export function formatVolume(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (value >= 1e4) return (value / 1e4).toFixed(1) + '万'
  return value.toFixed(0)
}

/** 默认行情标的列表：仅包含 instrument master 中已验证可取快照的 A 股标的。 */
export const DEFAULT_SYMBOLS = [
  '000001.SZ',
  '000002.SZ',
  '600519.SH',
  '601318.SH',
  '600036.SH',
  '000858.SZ',
  '002594.SZ',
  '300750.SZ',
]

/** 钱包重置后固定恢复的仿真现金（人民币）。 */
export const DEFAULT_SIMULATION_CASH_RMB = 1_000_000
