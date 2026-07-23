// 统一 API 响应格式
export interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: { code: string; message: string; details?: Record<string, unknown> } | null;
  meta: Record<string, unknown>;
}

// 分页响应（data 部分用于列表型接口）
export interface PageResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ---------- 用户画像 ----------
export interface Goal {
  name: string;
  target_amount: number;
  target_date: string;
  priority: 'high' | 'medium' | 'low';
}

export interface FinancialConstraints {
  investable_amount?: number;
  emergency_fund?: number;
  near_term_cash_needs?: number;
  major_liabilities?: number;
  base_currency?: string;
  region?: string;
}

export interface StatedRisk {
  loss_tolerance?: number;
  volatility_tolerance?: number;
  experience_years?: number;
  preference?: string;
  source?: string;
  collected_at?: string;
}

export interface RevealedRisk {
  inferred_tolerance?: number;
  source?: string;
}

export interface BehavioralPrefs {
  review_frequency?: string;
  drawdown_reaction?: string;
  autonomy_preference?: string;
}

export interface Restrictions {
  regions?: string[];
  product_exclusions?: string[];
  concentration_limits?: Record<string, number>;
}

export interface UserProfile {
  id: string;
  version: number;
  goals: Goal[];
  financial_constraints: FinancialConstraints;
  stated_risk: StatedRisk;
  revealed_risk: RevealedRisk;
  behavioral_prefs: BehavioralPrefs;
  restrictions: Restrictions;
  completeness: number;
  confidence: number;
  status: 'draft' | 'confirmed' | 'superseded';
  confirmed_at: string | null;
  created_at: string | null;
}

// ---------- 用户心智状态快照 ----------
export interface MentalState {
  anxiety_level: number;
  greed_level: number;
  impulsivity: number;
  overall_state: string;
}

export interface CognitiveBias {
  name: string;
  detected: boolean;
  score: number;
  evidence?: string | null;
}

export interface UserStateSnapshot {
  id: string;
  version: number;
  mental_state: MentalState;
  cognitive_biases: CognitiveBias[];
  signal_sources: unknown[];
  consent_scope: string;
  confidence: number;
  expires_at: string;
  user_confirmation: 'pending' | 'confirmed' | 'corrected' | 'rejected';
  user_feedback?: string | null;
  created_at: string;
}

// ---------- 投资授权书 ----------
export interface RiskBudget {
  max_drawdown?: number;
  max_volatility?: number;
  var_limit?: number;
}

export interface CashBoundary {
  min_cash_ratio?: number;
  max_cash_ratio?: number;
}

export interface AssetScope {
  allowed_markets?: string[];
  allowed_asset_types?: string[];
}

export interface ConcentrationLimits {
  max_single_asset?: number;
  max_single_sector?: number;
  max_single_market?: number;
}

export interface InvestmentMandate {
  id: string;
  version: number;
  profile_version: number;
  goal_priorities: string[];
  risk_budget: RiskBudget;
  cash_boundary: CashBoundary;
  asset_scope: AssetScope;
  concentration_limits: ConcentrationLimits;
  rebalance_frequency: string;
  rebalance_threshold: number;
  autonomy_level: 'L0' | 'L1' | 'L2' | 'L3';
  max_single_order_amount?: number | null;
  valid_from: string;
  valid_until: string | null;
  status: 'draft' | 'active' | 'paused' | 'revoked' | 'expired' | 'superseded';
  revoked_at?: string | null;
  revoke_reason?: string | null;
  created_at: string;
}

// ---------- 持仓快照 ----------
export interface HoldingPosition {
  instrument_id?: string;
  symbol?: string;
  name?: string;
  quantity?: number;
  avg_cost?: number;
  market_value?: number;
  weight?: number;
  cost_basis?: number;
  unrealized_pnl?: number;
}

export interface HoldingSnapshot {
  id: string;
  version: number;
  source_type: 'manual' | 'csv_import' | 'broker_sync';
  positions: HoldingPosition[];
  unresolved_positions: unknown[];
  unresolved_weight: number;
  total_market_value: number;
  total_cost_basis: number;
  cash_balance: number;
  valuation_as_of: string;
  created_at: string;
}

// ---------- 资产主数据 ----------
export interface Instrument {
  id: string;
  symbol: string;
  name: string;
  asset_type: string;
  market: string;
  currency: string;
  exchange?: string | null;
  min_trade_unit: number;
  expense_ratio?: number | null;
  sector?: string | null;
  benchmark?: string | null;
  trading_attributes: Record<string, unknown>;
  available_regions: string[];
  status: 'active' | 'suspended' | 'delisted';
  data_as_of: string;
  created_at: string;
}

// ---------- 策略方案 ----------
export interface GlobalAllocation {
  cash_ratio: number;
  equity_ratio: number;
  bond_ratio: number;
}

export interface RiskScenario {
  scenario_name: string;
  expected_return: number;
  expected_volatility: number;
  max_drawdown: number;
  probability: number;
}

export interface StrategyProposal {
  id: string;
  version: number;
  status: 'candidate' | 'accepted' | 'rejected' | 'superseded' | 'invalid';
  global_allocation: GlobalAllocation;
  market_allocation: Record<string, { weight: number }>;
  risk_scenarios: RiskScenario[];
  assumptions: string[];
  mental_adaptations: Record<string, unknown>;
  explanation?: string | null;
  mandate_version: number;
  created_at: string;
}

// ---------- 目标组合 ----------
export interface TargetWeight {
  instrument_id: string;
  symbol: string;
  name: string;
  weight: number;
  target_value: number;
  current_weight: number;
  delta: number;
}

export interface ConstraintReport {
  passed: { rule: string; value: number; limit: number; note?: string }[];
  failed: {
    rule: string;
    value: number;
    limit: number;
    severity?: string;
    explanation?: string;
  }[];
  warnings: { rule: string; value: number; limit: number; note?: string }[];
  passed_all?: boolean;
}

export interface RiskMetrics {
  expected_return: number;
  expected_volatility: number;
  sharpe_ratio: number;
  max_drawdown: number;
  var_95: number;
}

export interface RebalancePlanItem {
  instrument_id: string;
  symbol: string;
  action: 'buy' | 'sell';
  quantity: number;
  estimated_value: number;
  priority: number;
  reason: string;
}

export interface TargetPortfolio {
  id: string;
  version: number;
  constructible: boolean;
  constructible_reason?: string | null;
  target_weights: TargetWeight[];
  constraint_report: ConstraintReport;
  risk_metrics: RiskMetrics;
  rebalance_plan: RebalancePlanItem[];
  total_expected_cost: number;
  total_expected_slippage: number;
  data_coverage: number;
  status: 'draft' | 'confirmed' | 'executing' | 'executed' | 'invalid';
  created_at: string;
}

// ---------- 订单意图 ----------
export interface RiskCheck {
  passed: boolean;
  checks?: { rule: string; passed: boolean }[];
}

export interface OrderIntent {
  id: string;
  idempotency_key: string;
  account_type: 'simulation' | 'live';
  instrument_id?: string;
  symbol: string;
  direction: 'buy' | 'sell';
  quantity: number;
  price_limit?: number | null;
  price_protection?: Record<string, unknown>;
  mandate_version: number;
  portfolio_version?: number | null;
  strategy_version?: number | null;
  risk_check_1: RiskCheck;
  risk_check_2: RiskCheck;
  risk_check_3?: RiskCheck;
  status:
    | 'pending'
    | 'approved'
    | 'queued'
    | 'submitted'
    | 'partial_fill'
    | 'filled'
    | 'blocked'
    | 'rejected'
    | 'cancelled';
  expires_at: string;
  cancel_reason?: string | null;
  blocked_by?: { rule_id: string; rule_name: string; explanation: string } | null;
  created_at: string;
  updated_at?: string | null;
}

// ---------- 执行记录 ----------
export interface Fill {
  fill_price: number;
  fill_quantity: number;
  fill_time: string;
  fee: number;
  slippage: number;
  market_price_at_fill: number;
}

export interface StatusHistoryItem {
  from_status: string;
  to_status: string;
  at: string;
  reason: string;
  actor: string;
}

export interface ExecutionRecord {
  id: string;
  order_intent_id: string;
  user_id: string;
  account_type: string;
  fills: Fill[];
  total_filled_quantity: number;
  total_fee: number;
  total_slippage: number;
  avg_fill_price: number;
  status_history: StatusHistoryItem[];
  rejection_reason?: string | null;
  cancel_reason?: string | null;
  data_as_of: string;
  fee_model: string;
  slippage_model: string;
  status: string;
  created_at: string;
  updated_at?: string | null;
}

// ---------- 风险事件 ----------
export interface RiskEvent {
  id: string;
  rule_id: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  category: string;
  description: string;
  input_snapshot: Record<string, unknown>;
  affected_objects: unknown[];
  disposition: 'open' | 'acknowledged' | 'resolved' | 'escalated';
  resolution?: string | null;
  resolved_at?: string | null;
  resolved_by?: string | null;
  recovery_conditions?: Record<string, unknown> | null;
  created_at: string;
}

// ---------- 审计事件 ----------
export interface AuditEvent {
  id: string;
  event_type: string;
  user_id: string;
  subject_type: string;
  subject_id: string;
  before_version?: number | null;
  after_version?: number | null;
  request_correlation_id?: string | null;
  payload: Record<string, unknown>;
  actor: string;
  ip_address?: string | null;
  created_at: string;
}

// ---------- 仿真账户 ----------
export interface SimPosition {
  instrument_id?: string;
  symbol?: string;
  quantity: number;
  avg_cost: number;
  market_value: number;
  unrealized_pnl?: number;
}

export interface SimulatedAccount {
  id: string;
  user_id: string;
  cash_balance: number;
  total_market_value: number;
  total_value: number;
  positions: SimPosition[];
  total_fee_paid: number;
  total_slippage: number;
  status: 'active' | 'paused' | 'closed';
  created_at: string;
}

// ---------- Agent 状态 ----------
export interface AgentHealth {
  status: string;
}

export interface AgentStatus {
  name: string;
  capabilities: string[];
  health: AgentHealth;
}

// ---------- 仪表盘聚合数据 ----------
export interface DashboardMentalState {
  anxiety_level: number;
  greed_level: number;
  impulsivity: number;
  overall_state: string;
}

export interface DashboardPortfolioState {
  deviation: number;
  max_drawdown: number;
  sharpe_ratio: number;
}

export interface DashboardMarketSentiment {
  a_shares: number;
  us_stocks: number;
  hk_stocks: number;
}

export interface DashboardRiskAlert {
  total: number;
  critical: number;
  unresolved: number;
}

export interface DashboardData {
  mental_state?: DashboardMentalState;
  portfolio_state?: DashboardPortfolioState;
  market_sentiment?: DashboardMarketSentiment;
  risk_alert?: DashboardRiskAlert;
  pending_items?: { title: string; description?: string; type?: string }[];
  recent_activities?: { time: string; description: string; actor?: string }[];
}

// ---------- 复盘 ----------
export interface ReviewResult {
  id: string;
  type: string;
  period: string;
  profile_changes: {
    version_from: number | null;
    version_to: number;
    changes: { field: string; from: unknown; to: unknown }[];
  };
  portfolio_deviation: {
    current_vs_target_deviation: number;
    largest_deviations: { symbol: string; deviation: number }[];
  };
  strategy_performance: {
    return_actual: number;
    return_expected: number;
    tracking_error: number;
  };
  execution_quality: {
    total_orders: number;
    avg_slippage_bps: number;
    fill_rate: number;
  };
  risk_events_summary: {
    total: number;
    critical: number;
    resolved: number;
  };
  mental_state_trend: {
    anxiety_trend: string;
    confidence_trend: string;
  };
  recommendations: string[];
  actions_required: string[];
}
