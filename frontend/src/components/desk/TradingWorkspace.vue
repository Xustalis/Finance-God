<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  SimulationAccount as TradingDeskAccount,
  SimulationDraft,
  SimulationOrder,
} from '@/services/tradingDesk'

export type SimulationAccount = Pick<TradingDeskAccount, 'account_id' | 'cash_available_rmb'>
export interface DraftSnapshot {
  record_revision: SimulationDraft['record_revision']
  draft: Pick<SimulationDraft['draft'], 'draft_id' | 'status' | 'instrument_id' | 'side' | 'order_type' | 'quantity' | 'limit_price'>
  risk_result: SimulationDraft['risk_result']
  immutable_summary_hash: SimulationDraft['immutable_summary_hash']
  confirmed_at: SimulationDraft['confirmed_at']
}
export type OrderReceipt = Pick<SimulationOrder, 'order_id' | 'status' | 'instrument_id' | 'side' | 'quantity' | 'average_fill_price' | 'execution_error'>

const props = defineProps<{
  account: SimulationAccount | null
  selectedSymbol: string
  draft: DraftSnapshot | null
  receipt: OrderReceipt | null
  loading: boolean
  error: string | null
  onLoad: () => void | Promise<void>
  onCreateDraft: (input: { instrumentId: string; side: 'buy' | 'sell'; orderType: 'market' | 'limit'; quantity: string; limitPrice: string | null }) => void | Promise<void>
  onReviewDraft: (draftId: string) => void | Promise<void>
  onConfirmSoftRisk: (input: { draftId: string; reasonHash: string }) => void | Promise<void>
  onConfirmDraft: (input: { draftId: string; expectedRevision: number; summaryHash: string }) => void | Promise<void>
  onSubmitDraft: (draftId: string) => void | Promise<void>
}>()

const instrumentId = ref(props.selectedSymbol)
const side = ref<'buy' | 'sell'>('buy')
const orderType = ref<'market' | 'limit'>('market')
const quantity = ref('')
const limitPrice = ref('')
const canCreate = computed(() => Boolean(props.account && instrumentId.value.trim() && Number(quantity.value) > 0 && (orderType.value === 'market' || Number(limitPrice.value) > 0)))
const requiresSoftConfirmation = computed(() => props.draft?.risk_result?.status === 'confirmation_required' && !props.draft.risk_result.soft_confirmation && Boolean(props.draft.risk_result.reason_hash))
const canConfirmSummary = computed(() => {
  const risk = props.draft?.risk_result
  return Boolean(props.draft?.immutable_summary_hash && (risk?.status === 'passed' || (risk?.status === 'confirmation_required' && risk.soft_confirmation)))
})

watch(() => props.selectedSymbol, (next) => { instrumentId.value = next })

async function createDraft() { if (!canCreate.value) return; await props.onCreateDraft({ instrumentId: instrumentId.value.trim(), side: side.value, orderType: orderType.value, quantity: quantity.value, limitPrice: orderType.value === 'limit' ? limitPrice.value : null }) }
</script>

<template>
  <section class="information-workspace" aria-labelledby="trading-title">
    <header class="overview-heading"><h1 id="trading-title">交易</h1><button class="refresh-button" type="button" :disabled="loading" @click="onLoad">{{ loading ? '正在刷新' : '刷新' }}</button></header>
    <p class="chapter">仿真交易。Agent 只能协助准备和复核；最终提交必须由你本人确认。</p>
    <section v-if="!account" class="not-connected-workspace"><h2>尚未建立仿真账户</h2><p>请先在“持仓”中建立仿真账户，再创建订单草稿。</p></section>
    <template v-else>
      <form class="form-workspace" aria-label="创建仿真订单草稿" @submit.prevent="createDraft">
        <label>标的<input v-model="instrumentId" required></label>
        <label>方向<select v-model="side"><option value="buy">买入</option><option value="sell">卖出</option></select></label>
        <label>订单类型<select v-model="orderType"><option value="market">市价</option><option value="limit">限价</option></select></label>
        <label>数量<input v-model="quantity" type="number" min="1" step="1" required></label>
        <label v-if="orderType === 'limit'">限价<input v-model="limitPrice" type="number" min="0.01" step="0.01" required></label>
        <button class="ink-button" type="submit" :disabled="!canCreate || loading">创建订单草稿</button>
      </form>

      <section v-if="draft" class="overview-section" aria-labelledby="draft-title">
        <header><h2 id="draft-title">订单草稿</h2><small>{{ draft.draft.draft_id }} · 修订 {{ draft.record_revision }}</small></header>
        <dl class="market-sheet"><div><dt>标的</dt><dd>{{ draft.draft.instrument_id }}</dd></div><div><dt>方向</dt><dd>{{ draft.draft.side }}</dd></div><div><dt>状态</dt><dd>{{ draft.draft.status }}</dd></div><div><dt>数量</dt><dd>{{ draft.draft.quantity ?? '—' }}</dd></div><div><dt>限价</dt><dd>{{ draft.draft.limit_price ?? '市价' }}</dd></div><div><dt>风险复核</dt><dd>{{ draft.risk_result?.status ?? '尚未复核' }}</dd></div></dl>
        <ul v-if="draft.risk_result?.reasons?.length" class="risk-reason-list"><li v-for="reason in draft.risk_result.reasons" :key="reason.code" :class="reason.severity === 'hard' ? 'data-error' : ''">{{ reason.message }}（{{ reason.code }}）</li></ul>
        <div class="form-actions"><button v-if="!draft.risk_result" class="refresh-button" type="button" @click="onReviewDraft(draft.draft.draft_id)">进行风险复核</button><button v-if="requiresSoftConfirmation" class="refresh-button" type="button" @click="onConfirmSoftRisk({ draftId: draft.draft.draft_id, reasonHash: draft.risk_result!.reason_hash! })">确认已知风险</button><button v-if="canConfirmSummary && draft.draft.status !== 'confirmed'" class="ink-button" type="button" @click="onConfirmDraft({ draftId: draft.draft.draft_id, expectedRevision: draft.record_revision, summaryHash: draft.immutable_summary_hash! })">确认订单摘要</button><button v-if="draft.draft.status === 'confirmed'" class="ink-button" type="button" @click="onSubmitDraft(draft.draft.draft_id)">最终提交仿真订单</button></div>
      </section>
      <section v-if="receipt" class="overview-section" aria-labelledby="receipt-title"><header><h2 id="receipt-title">订单 / 成交回执</h2><small>{{ receipt.order_id }}</small></header><dl class="market-sheet"><div><dt>状态</dt><dd>{{ receipt.status }}</dd></div><div><dt>标的</dt><dd>{{ receipt.instrument_id }}</dd></div><div><dt>成交均价</dt><dd>{{ receipt.average_fill_price ?? '等待成交' }}</dd></div></dl><p v-if="receipt.execution_error" class="data-error">{{ receipt.execution_error }}</p></section>
    </template>
    <p v-if="error" class="data-error" role="alert">仿真交易失败：{{ error }}</p>
  </section>
</template>
