<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  DeskQuote,
  SimulationAccount as TradingDeskAccount,
  SimulationDraft,
  SimulationOrder,
  TradePlan,
} from '@/services/tradingDesk'
import { canUseQuoteAsDraftReference, draftReferenceBlockedReason } from '@/services/tradingDesk'

export type SimulationAccount = Pick<TradingDeskAccount, 'account_id' | 'cash_available_rmb'>
export interface DraftSnapshot {
  record_revision: SimulationDraft['record_revision']
  draft: Pick<SimulationDraft['draft'], 'draft_id' | 'status' | 'instrument_id' | 'side' | 'order_type' | 'quantity' | 'limit_price'>
    & Partial<Pick<SimulationDraft['draft'], 'valid_until' | 'input_versions'>>
  reference_price?: SimulationDraft['reference_price']
  risk_result: SimulationDraft['risk_result']
  immutable_summary_hash: SimulationDraft['immutable_summary_hash']
  confirmed_at: SimulationDraft['confirmed_at']
}
export type OrderReceipt = Pick<SimulationOrder, 'order_id' | 'status' | 'instrument_id' | 'side' | 'quantity' | 'average_fill_price' | 'execution_error'>

const props = defineProps<{
  account: SimulationAccount | null
  accountState: 'unknown' | 'absent' | 'available' | 'error'
  selectedSymbol: string
  quotes: readonly DeskQuote[]
  draft: DraftSnapshot | null
  receipt: OrderReceipt | null
  tradePlan?: TradePlan | null
  prefill?: { side: 'buy' | 'sell'; quantity: string; priceType: 'market' | 'limit'; limitPrice: string | null } | null
  loading: boolean
  error: string | null
  onLoad: () => void | Promise<void>
  onOpenPortfolio?: () => void
  onEnsureQuoteSymbol?: (symbol: string) => void | Promise<void>
  onCreateDraft: (input: { instrumentId: string; side: 'buy' | 'sell'; orderType: 'market' | 'limit'; quantity: string; limitPrice: string | null }) => void | Promise<void>
  onReviewDraft: (draftId: string) => void | Promise<void>
  onConfirmSoftRisk: (input: { draftId: string; reasonHash: string }) => void | Promise<void>
  onConfirmDraft: (input: { draftId: string; expectedRevision: number; summaryHash: string }) => void | Promise<void>
  onSubmitDraft: (draftId: string) => void | Promise<void>
  onReconcileOrder?: (orderId: string) => void | Promise<void>
}>()

const instrumentId = ref(props.selectedSymbol)
const side = ref<'buy' | 'sell'>('buy')
const orderType = ref<'market' | 'limit'>('market')
const quantity = ref('')
const limitPrice = ref('')
const referenceQuote = computed(() => props.quotes.find((quote) => quote.symbol === instrumentId.value.trim()) ?? null)
const quoteBlockedReason = computed(() => {
  if (!referenceQuote.value) return draftReferenceBlockedReason(null)
  if (!canUseQuoteAsDraftReference(referenceQuote.value)) return draftReferenceBlockedReason(referenceQuote.value)
  return null
})
const canCreate = computed(() => Boolean(
  props.account
  && props.accountState === 'available'
  && referenceQuote.value
  && canUseQuoteAsDraftReference(referenceQuote.value)
  && Number(quantity.value) > 0
  && (orderType.value === 'market' || Number(limitPrice.value) > 0),
))
const requiresSoftConfirmation = computed(() => props.draft?.risk_result?.status === 'confirmation_required' && !props.draft.risk_result.soft_confirmation && Boolean(props.draft.risk_result.reason_hash))
const canConfirmSummary = computed(() => {
  const risk = props.draft?.risk_result
  return Boolean(props.draft?.immutable_summary_hash && (risk?.status === 'passed' || (risk?.status === 'confirmation_required' && risk.soft_confirmation)))
})

watch(() => props.selectedSymbol, (next) => { instrumentId.value = next })
watch(() => props.prefill, (next) => {
  if (!next) return
  side.value = next.side
  quantity.value = next.quantity
  orderType.value = next.priceType
  limitPrice.value = next.limitPrice ?? ''
}, { immediate: true })
watch(instrumentId, (next) => {
  const symbol = next.trim()
  if (symbol) void props.onEnsureQuoteSymbol?.(symbol)
}, { immediate: true })

async function createDraft() { if (!canCreate.value) return; await props.onCreateDraft({ instrumentId: instrumentId.value.trim(), side: side.value, orderType: orderType.value, quantity: quantity.value, limitPrice: orderType.value === 'limit' ? limitPrice.value : null }) }
async function refreshQuote() {
  const symbol = instrumentId.value.trim()
  if (symbol) await props.onEnsureQuoteSymbol?.(symbol)
  await props.onLoad()
}
</script>

<template>
  <section class="information-workspace" aria-labelledby="trading-title">
    <header class="overview-heading"><h1 id="trading-title">交易</h1><button class="refresh-button" type="button" :disabled="loading" @click="refreshQuote">{{ loading ? '正在刷新' : '刷新' }}</button></header>
    <p class="chapter">仿真交易。Agent 只能协助准备和复核；最终提交必须由你本人确认。交易计划不是自动下单。</p>
    <section v-if="tradePlan" class="overview-section" aria-labelledby="plan-title">
      <header>
        <h2 id="plan-title">服务端交易计划</h2>
        <small>{{ tradePlan.object.plan_id }} · 修订 {{ tradePlan.object.revision }}</small>
      </header>
      <dl class="market-sheet">
        <div><dt>状态</dt><dd>{{ tradePlan.object.status }}</dd></div>
        <div><dt>来源</dt><dd>{{ tradePlan.source_type }} · {{ tradePlan.source_id }}</dd></div>
        <div><dt>动作数</dt><dd>{{ tradePlan.object.actions.length }}</dd></div>
      </dl>
      <div v-if="tradePlan.object.actions.length" class="market-table-wrap"><table class="market-table">
          <thead><tr><th scope="col">标的</th><th scope="col">方向</th><th scope="col" class="numeric">数量</th><th scope="col">纳入</th></tr></thead>
          <tbody>
            <tr v-for="action in tradePlan.object.actions" :key="action.action_id">
              <th scope="row">{{ action.instrument_id }}</th>
              <td>{{ action.side }}</td>
              <td class="numeric">{{ action.quantity ?? '—' }}</td>
              <td>{{ action.included ? '是' : '否' }}</td>
            </tr>
          </tbody>
        </table></div>
      <p class="data-footnote">计划仅作研究与准备；创建下方草稿并完成确认后才会生成仿真订单。</p>
    </section>
    <section v-if="accountState === 'unknown' && !account" class="not-connected-workspace"><h2>正在确认仿真账户</h2><p>账户状态确认前不会开放订单草稿。</p></section>
    <section v-else-if="accountState === 'absent'" class="not-connected-workspace">
      <h2>尚未建立仿真账户</h2>
      <p>没有仿真账户时不能创建订单草稿。请先在「持仓」建立仿真账户；账户、订单与执行始终为仿真数据。</p>
      <button v-if="onOpenPortfolio" class="ink-button" type="button" @click="onOpenPortfolio">前往持仓建立账户</button>
    </section>
    <section v-else-if="accountState === 'error' && !account" class="not-connected-workspace">
      <h2>仿真账户状态不可用</h2>
      <p>服务端未能确认账户状态，已暂停创建订单草稿。请刷新后重试。</p>
      <button class="refresh-button" type="button" :disabled="loading" @click="onLoad">{{ loading ? '正在刷新' : '刷新账户状态' }}</button>
    </section>
    <template v-else-if="account">
      <section class="quote-reference" aria-live="polite">
        <div>
          <span>真实引用行情</span>
          <strong>{{ referenceQuote?.name || instrumentId }} · {{ referenceQuote?.symbol || '未匹配' }}</strong>
        </div>
        <template v-if="referenceQuote">
          <dl>
            <div><dt>最新价</dt><dd>{{ referenceQuote.last ?? '不可用' }}</dd></div>
            <div><dt>上游时间</dt><dd>{{ referenceQuote.provider_time || '—' }}</dd></div>
            <div><dt>频率 / 新鲜度</dt><dd>{{ referenceQuote.frequency || '—' }} · {{ referenceQuote.freshness }}</dd></div>
            <div><dt>市场状态</dt><dd>{{ referenceQuote.market_status }}</dd></div>
          </dl>
          <p v-if="quoteBlockedReason" class="data-error" role="status">{{ quoteBlockedReason }}</p>
        </template>
        <template v-else>
          <p class="data-error" role="status">{{ quoteBlockedReason }}</p>
          <p class="data-footnote">不会用示例价或本地推算价创建草稿。可先确认标的代码，再刷新真实行情。</p>
        </template>
        <button v-if="quoteBlockedReason" class="refresh-button" type="button" :disabled="loading" @click="refreshQuote">{{ loading ? '正在刷新' : '刷新真实行情' }}</button>
      </section>
      <form class="form-workspace" aria-label="创建仿真订单草稿" @submit.prevent="createDraft">
        <label>标的<input v-model="instrumentId" required></label>
        <label>方向<select v-model="side"><option value="buy">买入</option><option value="sell">卖出</option></select></label>
        <label>订单类型<select v-model="orderType"><option value="market">市价</option><option value="limit">限价</option></select></label>
        <label>数量<input v-model="quantity" type="number" min="1" step="1" required></label>
        <label v-if="orderType === 'limit'">限价<input v-model="limitPrice" type="number" min="0.01" step="0.01" required></label>
        <button class="ink-button" type="submit" :disabled="!canCreate || loading">创建订单草稿</button>
        <p v-if="!canCreate && accountState === 'available' && Number(quantity) > 0 && quoteBlockedReason" class="data-footnote">{{ quoteBlockedReason }}</p>
      </form>

      <section v-if="draft" class="overview-section" aria-labelledby="draft-title">
        <header><h2 id="draft-title">订单草稿</h2><small>{{ draft.draft.draft_id }} · 修订 {{ draft.record_revision }}</small></header>
        <dl class="market-sheet"><div><dt>标的</dt><dd>{{ draft.draft.instrument_id }}</dd></div><div><dt>方向</dt><dd>{{ draft.draft.side }}</dd></div><div><dt>状态</dt><dd>{{ draft.draft.status }}</dd></div><div><dt>数量</dt><dd>{{ draft.draft.quantity ?? '—' }}</dd></div><div><dt>限价</dt><dd>{{ draft.draft.limit_price ?? '市价' }}</dd></div><div><dt>真实引用价</dt><dd>{{ draft.reference_price ?? '—' }}</dd></div><div><dt>有效期至</dt><dd>{{ draft.draft.valid_until ?? '—' }}</dd></div><div><dt>行情版本</dt><dd>{{ draft.draft.input_versions?.[0]?.version ?? '—' }}</dd></div><div><dt>风险复核</dt><dd>{{ draft.risk_result?.status ?? '尚未复核' }}</dd></div></dl>
        <ul v-if="draft.risk_result?.reasons?.length" class="risk-reason-list"><li v-for="reason in draft.risk_result.reasons" :key="reason.code" :class="reason.severity === 'hard' ? 'data-error' : ''">{{ reason.message }}（{{ reason.code }}）</li></ul>
        <div class="form-actions"><button v-if="!draft.risk_result" class="refresh-button" type="button" @click="onReviewDraft(draft.draft.draft_id)">进行风险复核</button><button v-if="requiresSoftConfirmation" class="refresh-button" type="button" @click="onConfirmSoftRisk({ draftId: draft.draft.draft_id, reasonHash: draft.risk_result!.reason_hash! })">确认已知风险</button><button v-if="canConfirmSummary && draft.draft.status !== 'confirmed'" class="ink-button" type="button" @click="onConfirmDraft({ draftId: draft.draft.draft_id, expectedRevision: draft.record_revision, summaryHash: draft.immutable_summary_hash! })">确认订单摘要</button><button v-if="draft.draft.status === 'confirmed'" class="ink-button" type="button" @click="onSubmitDraft(draft.draft.draft_id)">最终提交仿真订单</button></div>
      </section>
      <section v-if="receipt" class="overview-section" aria-labelledby="receipt-title">
        <header><h2 id="receipt-title">订单 / 成交回执</h2><small>{{ receipt.order_id }}</small></header>
        <dl class="market-sheet"><div><dt>状态</dt><dd>{{ receipt.status }}</dd></div><div><dt>标的</dt><dd>{{ receipt.instrument_id }}</dd></div><div><dt>成交均价</dt><dd>{{ receipt.average_fill_price ?? '等待成交' }}</dd></div></dl>
        <p v-if="receipt.execution_error" class="data-error">{{ receipt.execution_error }}</p>
        <button
          v-if="onReconcileOrder && ['accepted', 'partially_filled'].includes(receipt.status)"
          class="refresh-button"
          type="button"
          :disabled="loading"
          @click="onReconcileOrder(receipt.order_id)"
        >{{ loading ? '正在读取行情' : '按真实行情尝试撮合' }}</button>
        <p v-if="receipt.status === 'accepted'" class="data-footnote">仅使用提交后的 PandaData 行情；尚无后续行情时订单保持等待成交。</p>
      </section>
    </template>
    <p v-if="error" class="data-error" role="alert">仿真交易失败：{{ error }}</p>
  </section>
</template>
