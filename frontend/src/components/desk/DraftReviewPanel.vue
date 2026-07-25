<script setup lang="ts">
import { computed } from 'vue'
import type { SimulationDraft } from '@/services/tradingDesk'

const props = defineProps<{
  draft: SimulationDraft | null
  loading: boolean
  error: string | null
  onReview: () => void | Promise<void>
  onAcknowledgeSoftRisk: (hash: string) => void | Promise<void>
  onConfirm: (hash: string) => void | Promise<void>
  onSubmit: () => void | Promise<void>
  onDismiss: () => void
}>()

const status = computed(() => props.draft?.draft.status ?? '')

const stage = computed<'pending_review' | 'soft_risk' | 'ready_confirm' | 'confirmed' | 'other'>(() => {
  const s = status.value
  if (s === 'pending_review') return 'pending_review'
  if (s === 'reviewed' && props.draft?.risk_result?.status === 'soft_block') return 'soft_risk'
  if (s === 'reviewed' || s === 'soft_risk_confirmed') return 'ready_confirm'
  if (s === 'confirmed') return 'confirmed'
  return 'other'
})

const softRiskReasons = computed(() => props.draft?.risk_result?.reasons ?? [])
const reasonHash = computed(() => props.draft?.risk_result?.reason_hash ?? '')
const summaryHash = computed(() => props.draft?.immutable_summary_hash ?? props.draft?.risk_result?.summary_hash ?? '')
const costEstimate = computed(() => props.draft?.cost_estimate ?? null)

function sideLabel(side: string): string {
  const map: Record<string, string> = { buy: '买入', sell: '卖出', short: '做空', cover: '平空' }
  return map[side] ?? side
}

function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return `¥${num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const stageLabel = computed(() => {
  switch (stage.value) {
    case 'pending_review': return '等待风控复核'
    case 'soft_risk': return '需确认软风险'
    case 'ready_confirm': return '风控通过，等待确认'
    case 'confirmed': return '已确认，等待提交'
    default: return status.value
  }
})
</script>

<template>
  <section v-if="draft" class="overview-section draft-review-section" aria-labelledby="draft-review-title">
    <header>
      <h2 id="draft-review-title">订单草稿审核</h2>
      <small>{{ stageLabel }}</small>
    </header>

    <!-- Draft summary -->
    <dl class="market-sheet draft-summary">
      <div><dt>标的</dt><dd>{{ draft.draft.instrument_id }}</dd></div>
      <div><dt>方向</dt><dd>{{ sideLabel(draft.draft.side) }}</dd></div>
      <div><dt>数量</dt><dd>{{ draft.draft.quantity ?? '—' }}</dd></div>
      <div><dt>参考价</dt><dd>{{ money(draft.reference_price) }}</dd></div>
      <div><dt>模式</dt><dd>{{ draft.mode === 'planned' ? '交易计划' : '手动' }}</dd></div>
    </dl>

    <!-- Stage: pending_review -->
    <div v-if="stage === 'pending_review'" class="draft-stage">
      <p class="stage-description">草稿已创建，需要风控系统复核后才能继续。</p>
      <button class="ink-button" type="button" :disabled="loading" @click="onReview">
        {{ loading ? '正在复核' : '风控复核' }}
      </button>
    </div>

    <!-- Stage: soft_risk -->
    <div v-else-if="stage === 'soft_risk'" class="draft-stage">
      <p class="stage-description">风控发现以下软风险，确认后可继续：</p>
      <ul class="risk-reasons">
        <li v-for="(reason, idx) in softRiskReasons" :key="idx" :class="reason.severity">
          <span class="severity-tag">{{ reason.severity === 'hard' ? '硬限制' : '提示' }}</span>
          {{ reason.message }}
        </li>
      </ul>
      <button class="ink-button" type="button" :disabled="loading || !reasonHash" @click="onAcknowledgeSoftRisk(reasonHash)">
        {{ loading ? '正在确认' : '我已知晓风险，继续' }}
      </button>
    </div>

    <!-- Stage: ready_confirm -->
    <div v-else-if="stage === 'ready_confirm'" class="draft-stage">
      <p class="stage-description">风控通过。请确认以下费用预估：</p>
      <dl v-if="costEstimate" class="market-sheet cost-estimate">
        <div><dt>参考价</dt><dd>{{ money(costEstimate.reference_price) }}</dd></div>
        <div><dt>数量</dt><dd>{{ costEstimate.quantity }}</dd></div>
        <div><dt>名义金额</dt><dd>{{ money(costEstimate.notional) }}</dd></div>
        <div><dt>费用</dt><dd>{{ money(costEstimate.fee) }}</dd></div>
        <div><dt>总计</dt><dd><strong>{{ money(costEstimate.total) }}</strong></dd></div>
        <div><dt>现金变动</dt><dd>{{ money(costEstimate.cash_flow) }}</dd></div>
      </dl>
      <button class="ink-button" type="button" :disabled="loading || !summaryHash" @click="onConfirm(summaryHash)">
        {{ loading ? '正在确认' : '确认订单' }}
      </button>
    </div>

    <!-- Stage: confirmed -->
    <div v-else-if="stage === 'confirmed'" class="draft-stage">
      <p class="stage-description">订单已确认，摘要已锁定。提交后将进入撮合。</p>
      <dl class="market-sheet">
        <div><dt>确认时间</dt><dd>{{ draft.confirmed_at ?? '—' }}</dd></div>
      </dl>
      <button class="ink-button" type="button" :disabled="loading" @click="onSubmit">
        {{ loading ? '正在提交' : '提交订单' }}
      </button>
    </div>

    <p v-if="error" class="data-error" role="alert">{{ error }}</p>

    <div class="draft-dismiss">
      <button class="text-action" type="button" :disabled="loading" @click="onDismiss">放弃草稿</button>
    </div>
  </section>
</template>

<style scoped>
.draft-review-section { margin-top: 1rem; }
.draft-summary { margin-bottom: 0.75rem; }
.draft-stage { margin-top: 0.5rem; }
.stage-description { font-size: 0.85rem; color: var(--muted-ink); margin: 0 0 0.5rem; }
.risk-reasons { list-style: none; padding: 0; margin: 0 0 0.75rem; }
.risk-reasons li { padding: 0.4rem 0; border-bottom: 1px solid var(--faint-rule); font-size: 0.85rem; display: flex; align-items: baseline; gap: 0.5rem; }
.risk-reasons li.soft { color: var(--muted-ink); }
.risk-reasons li.hard { color: var(--risk); }
.severity-tag { font-size: 0.72rem; padding: 0.1rem 0.4rem; border: 1px solid currentColor; white-space: nowrap; }
.cost-estimate { margin-bottom: 0.75rem; }
.cost-estimate strong { color: var(--ink); }
.draft-dismiss { margin-top: 0.75rem; }
.text-action { background: transparent; border: none; color: var(--muted-ink); cursor: pointer; font-family: inherit; font-size: 0.85rem; text-decoration: underline; padding: 0.3rem 0; }
.text-action:hover { color: var(--risk); }
</style>
