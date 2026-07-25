<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import MarketChart, { type ChartQuote, type ChartPeriod } from './MarketChart.vue'
import TradePlanPanel from './TradePlanPanel.vue'
import DraftReviewPanel from './DraftReviewPanel.vue'
import type {
  DeskBar,
  DeskQuote,
  SimulationAccount,
  SimulationDraft,
  SimulationFill,
  SimulationOrder,
  SimulationPortfolio,
  TradePlan,
  TradePlanActionRevision,
} from '@/services/tradingDesk'
import { canUseQuoteAsDraftReference, draftReferenceBlockedReason } from '@/services/tradingDesk'

const props = withDefaults(defineProps<{
  account: Pick<SimulationAccount, 'account_id' | 'cash_available_rmb'> | null
  accountState: 'unknown' | 'absent' | 'available' | 'error'
  portfolio: SimulationPortfolio | null
  selectedSymbol: string
  quotes: readonly DeskQuote[]
  bars?: readonly DeskBar[]
  barsError?: string | null
  minutePeriodsAvailable?: boolean
  receipt: SimulationOrder | null
  fills: readonly SimulationFill[]
  prefill?: {
    side: 'buy' | 'sell'
    quantity: string
    source?: 'agent_strategy'
    planId?: string
  } | null
  activeDraft?: SimulationDraft | null
  activeTradePlan?: TradePlan | null
  tradePlanError?: string | null
  draftLoading?: boolean
  indexSwitchNotice?: string | null
  loading: boolean
  error: string | null
  onLoad: () => void | Promise<void>
  onOpenPortfolio?: () => void
  onEnsureQuoteSymbol?: (symbol: string) => void | Promise<void>
  onSelectSymbol?: (symbol: string) => void
  onPeriodChange?: (period: ChartPeriod) => void
  onSubmit: (input: {
    instrumentId: string
    side: 'buy' | 'sell'
    quantity: string
  }) => void | Promise<void>
  onReviewDraft?: () => void | Promise<void>
  onAcknowledgeSoftRisk?: (hash: string) => void | Promise<void>
  onConfirmDraft?: (hash: string) => void | Promise<void>
  onSubmitDraft?: () => void | Promise<void>
  onDismissDraft?: () => void
  onRevisePlan?: (actions: TradePlanActionRevision[]) => void | Promise<void>
  onConfirmPlan?: () => void | Promise<void>
  onDismissPlan?: () => void
}>(), {
  minutePeriodsAvailable: true,
})

const instrumentId = ref(props.selectedSymbol)
const side = ref<'buy' | 'sell'>('buy')
const quantity = ref('')
const referenceQuote = computed(() => props.quotes.find((quote) => quote.symbol === instrumentId.value.trim().toUpperCase()) ?? null)
const chartQuote = computed<ChartQuote | null>(() => {
  const quote = props.quotes.find((item) => item.symbol === props.selectedSymbol)
  return quote ? { ...quote } as ChartQuote : null
})
const chartError = computed(() => props.barsError ?? null)
const position = computed(() => props.portfolio?.positions.find((item) => item.instrument_id === instrumentId.value.trim().toUpperCase()) ?? null)
const numericQuantity = computed(() => Number(quantity.value))
const numericPrice = computed(() => referenceQuote.value?.last ?? null)
const estimatedAmount = computed(() => numericPrice.value === null || numericQuantity.value <= 0 ? null : numericPrice.value * numericQuantity.value)
const availableCash = computed(() => Number(props.account?.cash_available_rmb ?? 0))
const availableQuantity = computed(() => Number(position.value?.available_quantity ?? 0))
const quoteBlockedReason = computed(() => referenceQuote.value && canUseQuoteAsDraftReference(referenceQuote.value)
  ? null
  : draftReferenceBlockedReason(referenceQuote.value ?? null))
const balanceBlockedReason = computed(() => {
  if (numericQuantity.value <= 0) return null
  if (side.value === 'buy' && estimatedAmount.value !== null && estimatedAmount.value > availableCash.value) return '可用现金不足'
  if (side.value === 'sell' && numericQuantity.value > availableQuantity.value) return '可卖数量不足'
  return null
})
const canSubmit = computed(() => Boolean(
  props.account
  && props.accountState === 'available'
  && !props.loading
  && numericQuantity.value > 0
  && !balanceBlockedReason.value
))
const latestFill = computed(() => props.receipt?.fills[props.receipt.fills.length - 1] ?? null)
const recentFills = computed(() => [...props.fills].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)).slice(0, 20))

// --- Position analysis & P/L ---
const positionQuantity = computed(() => Number(position.value?.quantity ?? 0))
const positionAvailable = computed(() => Number(position.value?.available_quantity ?? 0))
const costBasis = computed(() => Number(position.value?.cost_basis_rmb ?? 0))
const averageCost = computed(() => {
  const avg = position.value?.average_cost_rmb
  return avg !== null && avg !== undefined ? Number(avg) : null
})
const marketValue = computed(() => {
  if (numericPrice.value === null || positionQuantity.value <= 0) return null
  return numericPrice.value * positionQuantity.value
})
const unrealizedPnl = computed(() => {
  if (marketValue.value === null || costBasis.value <= 0) return null
  return marketValue.value - costBasis.value
})
const unrealizedPnlPercent = computed(() => {
  if (unrealizedPnl.value === null || costBasis.value <= 0) return null
  return (unrealizedPnl.value / costBasis.value) * 100
})
const sellPnlEstimate = computed(() => {
  if (side.value !== 'sell' || numericPrice.value === null || numericQuantity.value <= 0 || averageCost.value === null) return null
  return (numericPrice.value - averageCost.value) * numericQuantity.value
})
const hasPosition = computed(() => positionQuantity.value > 0)

watch(() => props.selectedSymbol, (next) => { instrumentId.value = next })
watch(() => props.prefill, (next) => {
  if (!next) return
  side.value = next.side
  quantity.value = next.quantity
}, { immediate: true })
watch(instrumentId, (next) => {
  const symbol = next.trim().toUpperCase()
  if (symbol) void props.onEnsureQuoteSymbol?.(symbol)
}, { immediate: true })

function selectTradingSymbol() {
  const symbol = instrumentId.value.trim().toUpperCase()
  if (!symbol) return
  instrumentId.value = symbol
  if (symbol !== props.selectedSymbol) props.onSelectSymbol?.(symbol)
}

function money(value: number | string | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function pnlClass(value: number | null): string {
  if (value === null || value === 0) return ''
  return value > 0 ? 'pnl-positive' : 'pnl-negative'
}

async function submit() {
  if (!canSubmit.value) return
  await props.onSubmit({
    instrumentId: instrumentId.value.trim().toUpperCase(),
    side: side.value,
    quantity: String(quantity.value),
  })
}
</script>

<template>
  <section class="information-workspace" aria-labelledby="trading-title">
    <header class="overview-heading">
      <h1 id="trading-title">模拟交易</h1>
      <button class="refresh-button" type="button" :disabled="loading" @click="onLoad">{{ loading ? '正在刷新' : '刷新' }}</button>
    </header>

    <!-- Index switch notice -->
    <p v-if="indexSwitchNotice" class="index-switch-notice" role="status">{{ indexSwitchNotice }}</p>

    <section class="overview-section trading-chart-section" aria-labelledby="trading-chart-title">
      <header>
        <h2 id="trading-chart-title">{{ chartQuote?.name || selectedSymbol }}</h2>
        <small>{{ selectedSymbol }} · 实时 K 线</small>
      </header>
      <MarketChart
        :quote="chartQuote"
        :bars="bars ?? []"
        :loading="loading"
        :error="chartError"
        :minute-periods-available="minutePeriodsAvailable"
        :on-period-change="onPeriodChange"
      />
    </section>

    <section v-if="accountState === 'unknown' && !account" class="not-connected-workspace">
      <h2>正在确认模拟账户</h2>
      <p>账户状态确认后才能交易。</p>
    </section>
    <section v-else-if="accountState === 'absent'" class="not-connected-workspace">
      <h2>尚未建立模拟账户</h2>
      <p>请先建立模拟账户。</p>
      <button v-if="onOpenPortfolio" class="ink-button" type="button" @click="onOpenPortfolio">前往持仓</button>
    </section>
    <section v-else-if="accountState === 'error' && !account" class="not-connected-workspace">
      <h2>模拟账户不可用</h2>
      <button class="refresh-button" type="button" :disabled="loading" @click="onLoad">重新读取</button>
    </section>

    <template v-else-if="account">
      <section class="quote-reference" aria-live="polite">
        <div>
          <span>真实行情</span>
          <strong>{{ referenceQuote?.name || instrumentId }} · {{ referenceQuote?.symbol || '未匹配' }}</strong>
        </div>
        <dl v-if="referenceQuote">
          <div><dt>最新价</dt><dd>{{ money(referenceQuote.last) }}</dd></div>
          <div><dt>上游时间</dt><dd>{{ referenceQuote.provider_time || '—' }}</dd></div>
          <div><dt>频率 / 新鲜度</dt><dd>{{ referenceQuote.frequency || '—' }} · {{ referenceQuote.freshness }}</dd></div>
        </dl>
        <p v-if="quoteBlockedReason" class="workflow-note" role="status">{{ quoteBlockedReason }} 后端将尝试使用可用的历史价格执行。</p>
      </section>

      <!-- Position Analysis & P/L -->
      <section v-if="hasPosition" class="overview-section position-analysis" aria-labelledby="position-analysis-title">
        <header>
          <h2 id="position-analysis-title">当前持仓</h2>
          <small>模拟 · {{ instrumentId }}</small>
        </header>
        <dl class="market-sheet">
          <div><dt>持有数量</dt><dd>{{ positionQuantity.toLocaleString('zh-CN') }}</dd></div>
          <div><dt>可卖数量</dt><dd>{{ positionAvailable.toLocaleString('zh-CN') }}</dd></div>
          <div><dt>成本金额</dt><dd>{{ money(costBasis) }}</dd></div>
          <div><dt>平均成本</dt><dd>{{ averageCost !== null ? money(averageCost) : '—' }}</dd></div>
          <div><dt>当前市值</dt><dd>{{ marketValue !== null ? money(marketValue) : '行情不可用' }}</dd></div>
          <div>
            <dt>浮动盈亏</dt>
            <dd :class="pnlClass(unrealizedPnl)">
              {{ unrealizedPnl !== null ? money(unrealizedPnl) : '—' }}
              <span v-if="unrealizedPnlPercent !== null" class="pnl-percent">
                ({{ unrealizedPnlPercent >= 0 ? '+' : '' }}{{ unrealizedPnlPercent.toFixed(2) }}%)
              </span>
            </dd>
          </div>
        </dl>
      </section>

      <!-- Quick Market Order Form -->
      <form class="form-workspace" aria-label="模拟市价交易" @submit.prevent="submit">
        <p v-if="prefill?.source === 'agent_strategy'" class="empty-data" role="status">
          AI 已根据交易计划填写模拟交易单{{ prefill.planId ? `（${prefill.planId}）` : '' }}。
          {{ prefill.quantity ? '请核对真实行情、方向和数量后手动提交。' : '计划未确定数量，请补充数量后手动提交。' }}
        </p>
        <label>标的<input v-model="instrumentId" required @change="selectTradingSymbol"></label>
        <label>方向<select v-model="side"><option value="buy">买入</option><option value="sell">卖出</option></select></label>
        <label>数量<input v-model="quantity" type="number" min="1" step="1" required></label>
        <dl class="market-sheet trade-check">
          <div><dt>预计金额</dt><dd>{{ money(estimatedAmount) }}</dd></div>
          <div v-if="side === 'buy'"><dt>可用现金</dt><dd>{{ money(account.cash_available_rmb) }}</dd></div>
          <div v-else><dt>可卖数量</dt><dd>{{ availableQuantity.toLocaleString('zh-CN') }}</dd></div>
        </dl>
        <!-- Sell P/L estimate -->
        <dl v-if="side === 'sell' && sellPnlEstimate !== null" class="market-sheet sell-pnl">
          <div>
            <dt>预估{{ sellPnlEstimate >= 0 ? '盈利' : '亏损' }}</dt>
            <dd :class="pnlClass(sellPnlEstimate)">{{ money(Math.abs(sellPnlEstimate)) }}</dd>
          </div>
        </dl>
        <p v-if="balanceBlockedReason" class="data-error" role="status">{{ balanceBlockedReason }}</p>
        <button class="ink-button" type="submit" :disabled="!canSubmit">
          {{ loading ? '正在执行' : side === 'buy' ? '立即买入' : '立即卖出' }}
        </button>
      </form>

      <!-- Trade Plan Panel -->
      <TradePlanPanel
        v-if="activeTradePlan"
        :plan="activeTradePlan"
        :loading="loading"
        :error="tradePlanError ?? null"
        :on-revise="onRevisePlan ?? (async () => {})"
        :on-confirm="onConfirmPlan ?? (async () => {})"
        :on-dismiss="onDismissPlan ?? (() => {})"
      />

      <!-- Draft Review Panel -->
      <DraftReviewPanel
        v-if="activeDraft"
        :draft="activeDraft"
        :loading="draftLoading ?? false"
        :error="error"
        :on-review="onReviewDraft ?? (async () => {})"
        :on-acknowledge-soft-risk="onAcknowledgeSoftRisk ?? (async () => {})"
        :on-confirm="onConfirmDraft ?? (async () => {})"
        :on-submit="onSubmitDraft ?? (async () => {})"
        :on-dismiss="onDismissDraft ?? (() => {})"
      />

      <section v-if="receipt" class="overview-section" aria-labelledby="receipt-title">
        <header><h2 id="receipt-title">成交回执</h2><small>{{ receipt.order_id }}</small></header>
        <dl class="market-sheet">
          <div><dt>方向</dt><dd>{{ receipt.side === 'buy' ? '买入' : '卖出' }}</dd></div>
          <div><dt>标的</dt><dd>{{ receipt.instrument_id }}</dd></div>
          <div><dt>数量</dt><dd>{{ receipt.cumulative_filled }}</dd></div>
          <div><dt>成交价</dt><dd>{{ money(receipt.average_fill_price) }}</dd></div>
          <div><dt>成交金额</dt><dd>{{ money(receipt.filled_notional_rmb) }}</dd></div>
          <div><dt>费用</dt><dd>{{ money(receipt.total_fee_rmb) }}</dd></div>
          <div><dt>成交时间</dt><dd>{{ latestFill?.occurred_at ?? receipt.updated_at }}</dd></div>
        </dl>
      </section>

      <section class="overview-section" aria-labelledby="recent-fills-title">
        <header><h2 id="recent-fills-title">最近成交</h2><small>模拟 · 最近 20 条</small></header>
        <p v-if="!recentFills.length" class="empty-data">暂无成交。</p>
        <div v-else class="market-table-wrap">
          <table class="market-table">
            <thead><tr><th scope="col">时间</th><th scope="col">标的</th><th scope="col">方向</th><th scope="col" class="numeric">数量</th><th scope="col" class="numeric">成交价</th><th scope="col" class="numeric">金额</th></tr></thead>
            <tbody>
              <tr v-for="fill in recentFills" :key="fill.fill_id">
                <td>{{ fill.occurred_at }}</td>
                <th scope="row">{{ fill.instrument_id }}</th>
                <td>{{ fill.side === 'buy' ? '买入' : '卖出' }}</td>
                <td class="numeric">{{ fill.quantity }}</td>
                <td class="numeric">{{ money(fill.price) }}</td>
                <td class="numeric">{{ money(Number(fill.price) * Number(fill.quantity)) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
    <p v-if="error" class="data-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.index-switch-notice { background: var(--paper-light); border: 1px solid var(--rule); padding: 0.5rem 0.75rem; font-size: 0.82rem; color: var(--muted-ink); margin-bottom: 0.75rem; }
.position-analysis { margin-top: 0.5rem; }
.pnl-positive { color: var(--positive); font-weight: 600; }
.pnl-negative { color: var(--risk); font-weight: 600; }
.pnl-percent { font-size: 0.82rem; font-weight: 400; }
.sell-pnl { margin-top: 0.25rem; padding-top: 0.25rem; border-top: 1px dashed var(--faint-rule); }
</style>
