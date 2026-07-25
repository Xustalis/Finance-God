<script setup lang="ts">
import { computed, ref } from 'vue'

export interface SimulationAccount {
  account_id: string
  cash_total_rmb: string | number
  cash_available_rmb: string | number
  cash_frozen_rmb: string | number
  revision: number
  simulation_time: string | null
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
  onOpenPosition?: (position: PortfolioPosition) => void
  onSellPosition?: (position: PortfolioPosition) => void
  onCreateAccount: (input: { initialCash: string; simulationStartAt: string }) => void | Promise<void>
}>()

const quoteBySymbol = computed(() => new Map(props.quotes.map((quote) => [quote.symbol, quote])))
const initialCash = ref('100000')
const simulationStartAt = ref(defaultHistoricalStart())
const hasUnavailableMarketValue = computed(() => (
  props.portfolio?.positions.some((position) => marketValue(position) === null) ?? false
))

/* ─── 组合级汇总 ─── */
const totalMarketValue = computed(() => {
  if (!props.portfolio) return null
  if (!props.portfolio.positions.length) return 0
  let sum = 0
  for (const p of props.portfolio.positions) {
    const v = marketValue(p)
    if (v === null) return null
    sum += v
  }
  return sum
})
const totalUnrealized = computed(() => {
  if (!props.portfolio) return null
  if (!props.portfolio.positions.length) return 0
  let sum = 0
  for (const p of props.portfolio.positions) {
    const v = unrealized(p)
    if (v === null) return null
    sum += v
  }
  return sum
})
const totalAssets = computed(() => {
  const cash = decimal(props.account?.cash_total_rmb ?? null)
  const market = totalMarketValue.value
  if (cash === null || market === null) return null
  return cash + market
})

function decimal(value: string | number | null): number | null {
  if (value === null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}
function money(value: string | number | null): string { const parsed = decimal(value); return parsed === null ? '—' : `¥${parsed.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` }
function quantity(value: string | number): string { return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }
function canSell(position: PortfolioPosition): boolean {
  const available = Number(position.available_quantity)
  return Number.isFinite(available) && available > 0
}
function quoteFor(position: PortfolioPosition): QuoteSnapshot | null { return quoteBySymbol.value.get(position.instrument_id) ?? null }
function marketValue(position: PortfolioPosition): number | null { const quote = quoteFor(position); const amount = decimal(position.quantity); return !quote || quote.last === null || amount === null ? null : quote.last * amount }
function unrealized(position: PortfolioPosition): number | null { const value = marketValue(position); const cost = decimal(position.cost_basis_rmb); return value === null || cost === null ? null : value - cost }
function unrealizedPercent(position: PortfolioPosition): string {
  const pnl = unrealized(position)
  const cost = decimal(position.cost_basis_rmb)
  if (pnl === null || cost === null || cost === 0) return ''
  return `${pnl >= 0 ? '+' : ''}${((pnl / cost) * 100).toFixed(2)}%`
}
function lastPrice(position: PortfolioPosition): string {
  const quote = quoteFor(position)
  if (!quote || quote.last === null) return '—'
  return `¥${quote.last.toFixed(2)}`
}
function averageCost(position: PortfolioPosition): string {
  const cost = decimal(position.average_cost_rmb)
  if (cost === null) return '—'
  return `¥${cost.toFixed(2)}`
}
function quoteMeta(position: PortfolioPosition): string {
  const quote = quoteFor(position)
  if (!quote) return '无行情快照'
  return [quote.provider_time, quote.freshness, quote.market_status].filter(Boolean).join(' · ')
}
function holdPercent(position: PortfolioPosition): string {
  const mv = marketValue(position)
  const total = totalAssets.value
  if (mv === null || total === null || total === 0) return ''
  return `${((mv / total) * 100).toFixed(1)}%`
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
function defaultHistoricalStart(): string {
  const value = new Date(Date.now() + 8 * 60 * 60_000)
  value.setUTCDate(value.getUTCDate() - 1)
  while (value.getUTCDay() === 0 || value.getUTCDay() === 6) {
    value.setUTCDate(value.getUTCDate() - 1)
  }
  value.setUTCHours(9, 30, 0, 0)
  return value.toISOString().slice(0, 16)
}
function asShanghaiIso(value: string): string {
  return new Date(`${value}:00+08:00`).toISOString()
}
</script>

<template>
  <section class="information-workspace portfolio-workspace" aria-labelledby="portfolio-title">
    <header class="overview-heading"><h1 id="portfolio-title">持仓</h1><button class="refresh-button" type="button" :disabled="loading" @click="onLoad">{{ loading ? '正在刷新' : '刷新' }}</button></header>

    <section v-if="accountState === 'unknown' && !account" class="not-connected-workspace" aria-live="polite">
      <h2>正在确认模拟账户</h2>
      <p>账户状态确认前不会开放建立账户操作。</p>
    </section>

    <section v-else-if="accountState === 'absent'" class="not-connected-workspace" aria-labelledby="account-title">
      <h2 id="account-title">建立模拟账户</h2>
      <p>尚未建立模拟账户。初始资金只在你确认后提交到服务端。</p>
      <form class="form-workspace" @submit.prevent="onCreateAccount({ initialCash, simulationStartAt: asShanghaiIso(simulationStartAt) })">
        <label>初始资金（人民币）<input v-model="initialCash" type="number" min="1" step="0.01" required></label>
        <label>历史起点（上海时间）<input v-model="simulationStartAt" type="datetime-local" step="60" required></label>
        <button class="ink-button" type="submit" :disabled="loading">建立模拟账户</button>
      </form>
    </section>

    <template v-else-if="account">
      <!-- 组合总览摘要 -->
      <section class="portfolio-summary" aria-labelledby="account-summary-title">
        <header>
          <h2 id="account-summary-title">模拟账户</h2>
          <small>实时行情估值 · 修订 {{ account.revision }}</small>
        </header>
        <div class="portfolio-summary-grid">
          <div class="portfolio-summary-primary">
            <dt>总资产</dt>
            <dd>{{ totalAssets !== null ? money(totalAssets) : '估值不完整' }}</dd>
          </div>
          <div class="portfolio-summary-metrics">
            <dl class="portfolio-metrics-row">
              <div>
                <dt>现金</dt>
                <dd>{{ money(account.cash_total_rmb) }}</dd>
              </div>
              <div>
                <dt>可用</dt>
                <dd>{{ money(account.cash_available_rmb) }}</dd>
              </div>
              <div>
                <dt>冻结</dt>
                <dd>{{ money(account.cash_frozen_rmb) }}</dd>
              </div>
              <div v-if="totalMarketValue !== null">
                <dt>持仓市值</dt>
                <dd>{{ money(totalMarketValue) }}</dd>
              </div>
              <div v-if="totalUnrealized !== null">
                <dt>浮动盈亏</dt>
                <dd :class="totalUnrealized >= 0 ? 'up' : 'down'">{{ money(totalUnrealized) }}</dd>
              </div>
            </dl>
          </div>
        </div>
      </section>

      <!-- 持仓明细 -->
      <section class="overview-section portfolio-positions" aria-labelledby="position-title">
        <header><h2 id="position-title">持仓明细</h2><small v-if="portfolio">{{ portfolio.positions.length }} 只标的 · {{ portfolio.rule_version }}</small></header>
        <div v-if="portfolio?.positions.length" class="market-table-wrap">
          <table class="market-table portfolio-table">
            <thead>
              <tr>
                <th scope="col">标的</th>
                <th scope="col" class="numeric">数量</th>
                <th scope="col" class="numeric col-available">可用</th>
                <th scope="col" class="numeric">现价</th>
                <th scope="col" class="numeric">均价</th>
                <th scope="col" class="numeric">成本</th>
                <th scope="col" class="numeric">市值</th>
                <th scope="col" class="numeric">浮盈</th>
                <th scope="col" class="numeric col-realized">已实现</th>
                <th scope="col" class="col-action">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="position in portfolio.positions"
                :key="position.instrument_id"
                class="position-row"
                tabindex="0"
                :aria-label="`点击查看 ${position.instrument_id} 的交易页面`"
                @click="onOpenPosition?.(position)"
                @keydown.enter="onOpenPosition?.(position)"
              >
                <th scope="row">
                  <span class="position-symbol-link">{{ position.instrument_id }}</span>
                  <small class="position-hold-pct" v-if="holdPercent(position)">{{ holdPercent(position) }}</small>
                </th>
                <td class="numeric">{{ quantity(position.quantity) }}</td>
                <td class="numeric col-available">{{ quantity(position.available_quantity) }}</td>
                <td class="numeric position-price">
                  <span>{{ lastPrice(position) }}</span>
                  <small>{{ quoteMeta(position) }}</small>
                </td>
                <td class="numeric position-average-cost">{{ averageCost(position) }}</td>
                <td class="numeric position-cost">{{ money(position.cost_basis_rmb) }}</td>
                <td class="numeric" :class="{ 'data-error': marketValue(position) === null }">{{ marketValueLabel(position) }}</td>
                <td
                  class="numeric pnl-cell"
                  :class="unrealized(position) === null ? 'data-error' : ((unrealized(position) ?? 0) >= 0 ? 'up' : 'down')"
                >
                  <span>{{ unrealizedLabel(position) }}</span>
                  <small v-if="unrealizedPercent(position)">{{ unrealizedPercent(position) }}</small>
                </td>
                <td class="numeric col-realized" :class="(decimal(position.realized_pnl_rmb) ?? 0) >= 0 ? 'up' : 'down'">{{ money(position.realized_pnl_rmb) }}</td>
                <td class="col-action">
                  <button
                    class="position-sell-button"
                    type="button"
                    :disabled="!canSell(position)"
                    :aria-label="`卖出 ${position.instrument_id}`"
                    @click.stop="onSellPosition?.(position)"
                  >卖出</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="workspace-empty-ledger" role="status">
          <header><strong>当前模拟账户没有持仓</strong><span>模拟账户已建立，尚无买入成交</span></header>
          <dl>
            <div><dt>进入方式</dt><dd>在"交易"工作区选择 A 股标的并提交模拟市价单。</dd></div>
            <div><dt>成交后显示</dt><dd>数量、可用数量、成本、市值、浮盈与已实现盈亏。</dd></div>
            <div><dt>行情边界</dt><dd>市值与浮盈只使用 PandaData 可用最新价；行情失败时明确标记不可用。</dd></div>
          </dl>
        </div>
        <p v-if="hasUnavailableMarketValue" class="data-footnote" role="status">
          部分持仓缺少可用最新价，市值与浮盈标记为不可用；成本与已实现盈亏仍来自模拟账本。可点「刷新」重新拉取真实行情，不会用本地估算填充。
        </p>
      </section>
    </template>
    <section v-else class="not-connected-workspace" aria-live="polite">
      <h2>模拟账户状态不可用</h2>
      <p>服务端未能确认账户是否存在，已暂停建立账户操作。请刷新后重试。</p>
    </section>
    <p v-if="error" class="data-error" role="alert">持仓读取失败：{{ error }}</p>
  </section>
</template>
