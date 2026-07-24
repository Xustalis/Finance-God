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

export interface QuoteSnapshot { symbol: string; last: number | null; provider_time: string; freshness: string }

const props = defineProps<{
  account: SimulationAccount | null
  portfolio: PortfolioView | null
  quotes: readonly QuoteSnapshot[]
  loading: boolean
  error: string | null
  onLoad: () => void | Promise<void>
  onCreateAccount: (initialCash: string) => void | Promise<void>
}>()

const quoteBySymbol = computed(() => new Map(props.quotes.map((quote) => [quote.symbol, quote])))
const initialCash = ref('100000')

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
</script>

<template>
  <section class="information-workspace" aria-labelledby="portfolio-title">
    <header class="overview-heading"><h1 id="portfolio-title">持仓</h1><button class="refresh-button" type="button" :disabled="loading" @click="onLoad">{{ loading ? '正在刷新' : '刷新' }}</button></header>
    <p class="chapter">仿真账户与仿真持仓；行情采用 PandaData 上游快照。</p>

    <section v-if="!account" class="not-connected-workspace" aria-labelledby="account-title">
      <h2 id="account-title">建立仿真账户</h2>
      <p>尚未建立仿真账户。初始资金只在你确认后提交到服务端。</p>
      <form class="form-workspace" @submit.prevent="onCreateAccount(initialCash)">
        <label>初始资金（人民币）<input v-model="initialCash" type="number" min="1" step="0.01" required></label>
        <button class="ink-button" type="submit">建立仿真账户</button>
      </form>
    </section>

    <template v-else>
      <section class="overview-section" aria-labelledby="account-summary-title">
        <header><h2 id="account-summary-title">仿真账户</h2><small>修订 {{ account.revision }}</small></header>
        <dl class="market-sheet"><div><dt>现金总额</dt><dd>{{ money(account.cash_total_rmb) }}</dd></div><div><dt>可用现金</dt><dd>{{ money(account.cash_available_rmb) }}</dd></div><div><dt>冻结资金</dt><dd>{{ money(account.cash_frozen_rmb) }}</dd></div></dl>
      </section>
      <section class="overview-section" aria-labelledby="position-title">
        <header><h2 id="position-title">仿真持仓</h2><small v-if="portfolio">{{ portfolio.as_of }} · {{ portfolio.rule_version }}</small></header>
        <table v-if="portfolio?.positions.length" class="market-table">
          <thead><tr><th scope="col">标的</th><th scope="col" class="numeric">数量</th><th scope="col" class="numeric">可用</th><th scope="col" class="numeric">成本</th><th scope="col" class="numeric">市值</th><th scope="col" class="numeric">浮盈</th><th scope="col" class="numeric">已实现</th></tr></thead>
          <tbody><tr v-for="position in portfolio.positions" :key="position.instrument_id"><th scope="row">{{ position.instrument_id }}<small v-if="quoteFor(position)">{{ quoteFor(position)?.provider_time }} · {{ quoteFor(position)?.freshness }}</small></th><td class="numeric">{{ quantity(position.quantity) }}</td><td class="numeric">{{ quantity(position.available_quantity) }}</td><td class="numeric">{{ money(position.cost_basis_rmb) }}</td><td class="numeric">{{ marketValue(position) === null ? '行情不可用' : money(marketValue(position)) }}</td><td class="numeric" :class="(unrealized(position) ?? 0) >= 0 ? 'up' : 'down'">{{ unrealized(position) === null ? '行情不可用' : money(unrealized(position)) }}</td><td class="numeric" :class="decimal(position.realized_pnl_rmb)! >= 0 ? 'up' : 'down'">{{ money(position.realized_pnl_rmb) }}</td></tr></tbody>
        </table>
        <p v-else class="empty-data">当前仿真账户没有持仓。</p>
      </section>
    </template>
    <p v-if="error" class="data-error" role="alert">持仓读取失败：{{ error }}</p>
  </section>
</template>
