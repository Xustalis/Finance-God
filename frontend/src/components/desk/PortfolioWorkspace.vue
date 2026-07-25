<script setup lang="ts">
import { computed, ref } from 'vue'

export interface SimulationAccount {
  account_id: string
  cash_total_rmb: string | number
  cash_available_rmb: string | number
  cash_frozen_rmb: string | number
  revision: number
}

export interface PortfolioPosition {
  instrument_id: string
  quantity: string | number
  available_quantity: string | number
  average_cost_rmb: string | number | null
  cost_basis_rmb: string | number
  realized_pnl_rmb: string | number
}

export interface PortfolioView {
  as_of: string
  rule_version: string
  realized_pnl_rmb: string | number
  positions: readonly PortfolioPosition[]
}

export interface QuoteSnapshot {
  symbol: string
  last: number | null
  provider_time: string
  freshness: string
  market_status?: string
}

const props = defineProps<{
  account: SimulationAccount | null
  accountState: 'unknown' | 'absent' | 'available' | 'error'
  portfolio: PortfolioView | null
  quotes: readonly QuoteSnapshot[]
  loading: boolean
  error: string | null
  onLoad: () => void | Promise<void>
  onCreateAccount: (initialCash: string) => void | Promise<void>
}>()

const quoteBySymbol = computed(() => new Map(props.quotes.map((quote) => [quote.symbol, quote])))
const initialCash = ref('100000')
const hasUnavailableMarketValue = computed(() => (
  props.portfolio?.positions.some((position) => marketValue(position) === null) ?? false
))

function decimal(value: string | number | null): number | null {
  if (value === null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}
function money(value: string | number | null): string { const parsed = decimal(value); return parsed === null ? '—' : `¥${parsed.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}` }
function quantity(value: string | number): string { return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }
function quoteFor(position: PortfolioPosition): QuoteSnapshot | null { return quoteBySymbol.value.get(position.instrument_id) ?? null }
function marketValue(position: PortfolioPosition): number | null { const quote = quoteFor(position); const amount = decimal(position.quantity); return !quote || quote.last === null || amount === null ? null : quote.last * amount }
function unrealized(position: PortfolioPosition): number | null { const value = marketValue(position); const cost = decimal(position.cost_basis_rmb); return value === null || cost === null ? null : value - cost }
function quoteMeta(position: PortfolioPosition): string {
  const quote = quoteFor(position)
  if (!quote) return '无行情快照'
  const parts = [quote.provider_time || null, quote.freshness || null, quote.market_status || null].filter(Boolean)
  return parts.length ? parts.join(' · ') : '行情元数据缺失'
}
function marketValueLabel(position: PortfolioPosition): string {
  const value = marketValue(position)
  if (value !== null) return money(value)
  const quote = quoteFor(position)
  if (!quote) return '行情不可用'
  if (quote.last === null) return '无最新价'
  return '行情不可用'
}
function unrealizedLabel(position: PortfolioPosition): string {
  const value = unrealized(position)
  if (value !== null) return money(value)
  return marketValue(position) === null ? marketValueLabel(position) : '—'
}
</script>

<template>
  <section class="information-workspace" aria-labelledby="portfolio-title">
    <header class="overview-heading"><h1 id="portfolio-title">持仓</h1><button class="refresh-button" type="button" :disabled="loading" @click="onLoad">{{ loading ? '正在刷新' : '刷新' }}</button></header>
    <p class="chapter">仿真账户与仿真持仓；市值/浮盈仅在有真实行情最新价时计算，缺失时显示不可用，不编造数字。</p>

    <section v-if="accountState === 'unknown' && !account" class="not-connected-workspace" aria-live="polite">
      <h2>正在确认仿真账户</h2>
      <p>账户状态确认前不会开放建立账户操作。</p>
    </section>

    <section v-else-if="accountState === 'absent'" class="not-connected-workspace" aria-labelledby="account-title">
      <h2 id="account-title">建立仿真账户</h2>
      <p>尚未建立仿真账户。初始资金只在你确认后提交到服务端。</p>
      <form class="form-workspace" @submit.prevent="onCreateAccount(initialCash)">
        <label>初始资金（人民币）<input v-model="initialCash" type="number" min="1" step="0.01" required></label>
        <button class="ink-button" type="submit" :disabled="loading">建立仿真账户</button>
      </form>
    </section>

    <template v-else-if="account">
      <section class="overview-section" aria-labelledby="account-summary-title">
        <header><h2 id="account-summary-title">仿真账户</h2><small>修订 {{ account.revision }}</small></header>
        <dl class="market-sheet"><div><dt>现金总额</dt><dd>{{ money(account.cash_total_rmb) }}</dd></div><div><dt>可用现金</dt><dd>{{ money(account.cash_available_rmb) }}</dd></div><div><dt>冻结资金</dt><dd>{{ money(account.cash_frozen_rmb) }}</dd></div></dl>
      </section>
      <section class="overview-section" aria-labelledby="position-title">
        <header><h2 id="position-title">仿真持仓</h2><small v-if="portfolio">{{ portfolio.as_of }} · {{ portfolio.rule_version }}</small></header>
        <div v-if="portfolio?.positions.length" class="market-table-wrap">
          <table class="market-table">
            <thead><tr><th scope="col">标的</th><th scope="col" class="numeric">数量</th><th scope="col" class="numeric">可用</th><th scope="col" class="numeric">成本</th><th scope="col" class="numeric">市值</th><th scope="col" class="numeric">浮盈</th><th scope="col" class="numeric">已实现</th></tr></thead>
            <tbody>
              <tr v-for="position in portfolio.positions" :key="position.instrument_id">
                <th scope="row">
                  {{ position.instrument_id }}
                  <small>{{ quoteMeta(position) }}</small>
                </th>
                <td class="numeric">{{ quantity(position.quantity) }}</td>
                <td class="numeric">{{ quantity(position.available_quantity) }}</td>
                <td class="numeric">{{ money(position.cost_basis_rmb) }}</td>
                <td class="numeric" :class="{ 'data-error': marketValue(position) === null }">{{ marketValueLabel(position) }}</td>
                <td
                  class="numeric"
                  :class="unrealized(position) === null ? 'data-error' : ((unrealized(position) ?? 0) >= 0 ? 'up' : 'down')"
                >{{ unrealizedLabel(position) }}</td>
                <td class="numeric" :class="(decimal(position.realized_pnl_rmb) ?? 0) >= 0 ? 'up' : 'down'">{{ money(position.realized_pnl_rmb) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="empty-data">当前仿真账户没有持仓。</p>
        <p v-if="hasUnavailableMarketValue" class="data-footnote" role="status">
          部分持仓缺少可用最新价，市值与浮盈标记为不可用；成本与已实现盈亏仍来自仿真账本。可点「刷新」重新拉取真实行情，不会用本地估算填充。
        </p>
      </section>
    </template>
    <section v-else class="not-connected-workspace" aria-live="polite">
      <h2>仿真账户状态不可用</h2>
      <p>服务端未能确认账户是否存在，已暂停建立账户操作。请刷新后重试。</p>
    </section>
    <p v-if="error" class="data-error" role="alert">持仓读取失败：{{ error }}</p>
  </section>
</template>
