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
  freshness: string
  market_status: string
  source_endpoint: string
  capability_version: string
  instrument_master_identity: string
  instrument_master_version: string
  trade_eligible: boolean
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
  freshness: string
  provider_time: string
  source_endpoint: string
  capability_version: string
  instrument_master_identity: string
  instrument_master_version: string
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

// ─── 错误 ─────────────────────────────────────────

export interface BackendError {
  error: {
    code: string
    message: string
    trace_id?: string
  }
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

/** 默认行情标的列表 */
export const DEFAULT_SYMBOLS = [
  '000001.SZ', '000002.SZ', '600519.SH', '601318.SH',
  '399001.SZ', '399006.SZ', '000300.SH', '000016.SH',
]
