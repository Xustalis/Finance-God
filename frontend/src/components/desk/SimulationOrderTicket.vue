<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  confirmOrderDraft,
  confirmSoftRisk,
  createOrderDraft,
  newIdempotencyKey,
  reviewOrderDraft,
  submitOrderDraft,
} from '@/api/desk'
import type {
  MarketQuote,
  OrderDraftCreate,
  OrderSide,
  OrderType,
  SimulationAccount,
  StoredDraft,
  StoredOrder,
  TimeInForce,
} from '@/types/desk'

const props = defineProps<{
  account: SimulationAccount | null
  accountLoading: boolean
  accountMissing: boolean
  accountError: string | null
  quote: MarketQuote | null
}>()

const emit = defineEmits<{
  submitted: [order: StoredOrder]
}>()

type TicketStage =
  | 'editing'
  | 'creating'
  | 'reviewing'
  | 'review_failed'
  | 'reviewed'
  | 'confirming_risk'
  | 'confirming'
  | 'confirmed'
  | 'submitting'
  | 'unknown'
  | 'submitted'

const side = ref<OrderSide>('buy')
const orderType = ref<OrderType>('market')
const quantity = ref<number | null>(null)
const limitPrice = ref<number | null>(null)
const timeInForce = ref<TimeInForce>('day')
const stage = ref<TicketStage>('editing')
const workflowError = ref<string | null>(null)
const currentDraft = ref<StoredDraft | null>(null)
const submittedOrder = ref<StoredOrder | null>(null)
const summaryAcknowledged = ref(false)
const creationKey = ref<string | null>(null)
const submissionKey = ref<string | null>(null)

const busy = computed(() => [
  'creating',
  'reviewing',
  'confirming_risk',
  'confirming',
  'submitting',
].includes(stage.value))

const validQuantity = computed(() => (
  quantity.value !== null
  && Number.isFinite(quantity.value)
  && quantity.value > 0
))

const validLimitPrice = computed(() => (
  orderType.value === 'market'
  || (
    limitPrice.value !== null
    && Number.isFinite(limitPrice.value)
    && limitPrice.value > 0
  )
))

const simulationInstrumentSupported = computed(() => (
  props.quote !== null
  && ['equity', 'etf'].includes(props.quote.asset_type)
))

const canCreate = computed(() => (
  props.account?.status === 'active'
  && simulationInstrumentSupported.value
  && props.quote?.freshness === 'current'
  && props.quote.market_status === 'released'
  && validQuantity.value
  && validLimitPrice.value
  && !busy.value
))

const risk = computed(() => currentDraft.value?.risk_result ?? null)
const softRiskPending = computed(() => (
  risk.value?.status === 'confirmation_required'
  && risk.value.soft_confirmation === null
))
const hardBlocked = computed(() => (
  risk.value?.status === 'blocked'
  || risk.value?.status === 'expired'
))
const canConfirmSummary = computed(() => (
  stage.value === 'reviewed'
  && !softRiskPending.value
  && !hardBlocked.value
  && Boolean(currentDraft.value?.immutable_summary_hash)
  && summaryAcknowledged.value
))
const orderId = computed(() => (
  submittedOrder.value?.exchange_order?.order_id
  ?? submittedOrder.value?.fund_order?.order_id
  ?? null
))
const submittedStatus = computed(() => (
  submittedOrder.value?.exchange_order?.status
  ?? submittedOrder.value?.fund_order?.status
  ?? 'unknown'
))

const costEstimate = computed(() => currentDraft.value?.cost_estimate ?? null)
const projectedCash = computed<number | null>(() => {
  const est = costEstimate.value
  const acct = props.account
  if (!est || !acct) return null
  return est.cash_flow === 'outflow'
    ? acct.cash_available_rmb - est.total
    : acct.cash_available_rmb + est.total
})

function money(value: number): string {
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function resetWorkflow() {
  if (stage.value === 'editing' || busy.value || stage.value === 'submitted' || stage.value === 'unknown') {
    return
  }
  stage.value = 'editing'
  workflowError.value = null
  currentDraft.value = null
  summaryAcknowledged.value = false
  creationKey.value = null
  submissionKey.value = null
}

watch([side, orderType, quantity, limitPrice, timeInForce], resetWorkflow)
watch(() => props.quote?.symbol, resetWorkflow)

function draftRequest(): OrderDraftCreate {
  const quote = props.quote
  const account = props.account
  if (!quote || !account || !validQuantity.value) {
    throw new Error('账户、标的或数量尚未满足草稿条件')
  }
  return {
    mode: 'manual',
    account_id: account.account_id,
    instrument_id: quote.symbol,
    side: side.value,
    order_type: orderType.value,
    quantity: quantity.value as number,
    amount: null,
    limit_price: orderType.value === 'limit' ? limitPrice.value : null,
    reference_price: quote.last,
    time_in_force: timeInForce.value,
    fund_rule_version: null,
    valid_until: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
    input_versions: [{
      object_type: 'market_quote',
      object_id: quote.symbol,
      version: quote.provider_time,
    }],
    plan_reference: null,
  }
}

async function createAndReview() {
  if (!canCreate.value) return
  workflowError.value = null
  summaryAcknowledged.value = false
  try {
    creationKey.value ??= newIdempotencyKey('draft')
    stage.value = 'creating'
    const created = await createOrderDraft(draftRequest(), creationKey.value)
    currentDraft.value = created
    stage.value = 'reviewing'
    currentDraft.value = await reviewOrderDraft(
      created.draft.draft_id,
      created.record_revision,
    )
    stage.value = 'reviewed'
  } catch (error) {
    workflowError.value = error instanceof Error ? error.message : String(error)
    stage.value = currentDraft.value ? 'review_failed' : 'editing'
  }
}

async function retryReview() {
  const draft = currentDraft.value
  if (!draft || busy.value) return
  workflowError.value = null
  stage.value = 'reviewing'
  try {
    currentDraft.value = await reviewOrderDraft(
      draft.draft.draft_id,
      draft.record_revision,
    )
    stage.value = 'reviewed'
  } catch (error) {
    workflowError.value = error instanceof Error ? error.message : String(error)
    stage.value = 'review_failed'
  }
}

async function acknowledgeSoftRisk() {
  const draft = currentDraft.value
  if (!draft?.risk_result || !softRiskPending.value || busy.value) return
  workflowError.value = null
  stage.value = 'confirming_risk'
  try {
    currentDraft.value = await confirmSoftRisk(
      draft.draft.draft_id,
      draft.risk_result.reason_hash,
    )
    stage.value = 'reviewed'
  } catch (error) {
    workflowError.value = error instanceof Error ? error.message : String(error)
    stage.value = 'reviewed'
  }
}

async function confirmSummary() {
  const draft = currentDraft.value
  const summaryHash = draft?.immutable_summary_hash
  if (!draft || !summaryHash || !canConfirmSummary.value) return
  workflowError.value = null
  stage.value = 'confirming'
  try {
    currentDraft.value = await confirmOrderDraft(
      draft.draft.draft_id,
      draft.record_revision,
      summaryHash,
    )
    stage.value = 'confirmed'
  } catch (error) {
    workflowError.value = error instanceof Error ? error.message : String(error)
    stage.value = 'reviewed'
  }
}

async function submitConfirmedDraft() {
  const draft = currentDraft.value
  if (!draft || stage.value !== 'confirmed') return
  workflowError.value = null
  submissionKey.value ??= newIdempotencyKey('submit')
  stage.value = 'submitting'
  try {
    submittedOrder.value = await submitOrderDraft(
      draft.draft.draft_id,
      submissionKey.value,
    )
    stage.value = 'submitted'
    emit('submitted', submittedOrder.value)
  } catch (error) {
    workflowError.value = error instanceof Error ? error.message : String(error)
    stage.value = 'unknown'
  }
}
</script>

<template>
  <section class="ticket" aria-labelledby="simulation-ticket-title">
    <h2 id="simulation-ticket-title" class="section-title">
      <span>仿真订单草稿</span>
      <small>ORDER DRAFT</small>
    </h2>

    <div v-if="accountLoading" class="ticket-state" role="status">正在加载仿真账户…</div>
    <div v-else-if="accountMissing" class="ticket-state">
      <strong>尚未初始化仿真账户</strong>
      <span>在设置页创建账户后，才能创建可提交草稿。</span>
      <router-link to="/settings" class="secondary-action">前往账户设置</router-link>
    </div>
    <div v-else-if="accountError" class="ticket-state error-state" role="alert">
      <strong>账户状态加载失败</strong>
      <span>{{ accountError }}</span>
    </div>
    <form
      v-else-if="account"
      data-test="order-ticket-form"
      class="ticket-form"
      @submit.prevent="createAndReview"
    >
      <div class="account-line">
        <span>仿真账户</span>
        <strong>{{ account.account_id }}</strong>
        <span>可用 ¥{{ account.cash_available_rmb.toFixed(2) }}</span>
      </div>

      <label>
        <span>方向</span>
        <select v-model="side" :disabled="busy">
          <option value="buy">买入</option>
          <option value="sell">卖出</option>
        </select>
      </label>
      <label>
        <span>订单类型</span>
        <select v-model="orderType" :disabled="busy">
          <option value="market">市价单</option>
          <option value="limit">限价单</option>
        </select>
      </label>
      <label>
        <span>数量</span>
        <input
          v-model.number="quantity"
          data-test="order-quantity"
          type="number"
          min="1"
          step="1"
          inputmode="decimal"
          :disabled="busy"
        />
      </label>
      <label v-if="orderType === 'limit'">
        <span>限价</span>
        <input
          v-model.number="limitPrice"
          type="number"
          min="0.01"
          step="0.01"
          inputmode="decimal"
          :disabled="busy"
        />
      </label>
      <label>
        <span>有效期</span>
        <select v-model="timeInForce" :disabled="busy">
          <option value="day">当日有效</option>
          <option value="good_til_cancelled">撤销前有效</option>
          <option value="immediate_or_cancel">立即成交或取消</option>
        </select>
      </label>

      <p v-if="!quote" class="condition-note">等待 PandaData 当前标的行情。</p>
      <p v-else-if="!simulationInstrumentSupported" class="condition-note error-state">
        当前资产类型 {{ quote.asset_type }} 尚未接入仿真撮合。
      </p>
      <p v-else-if="quote.freshness !== 'current'" class="condition-note error-state">
        行情状态为 {{ quote.freshness }}，刷新成功前不能创建草稿。
      </p>
      <p v-else-if="quote.market_status !== 'released'" class="condition-note error-state">
        行情发布状态为 {{ quote.market_status }}，当前版本不能用于仿真草稿。
      </p>
      <p v-else class="condition-note">
        当前标的支持仿真撮合；PandaData 实盘交易资格为
        {{ quote.trade_eligible ? '可用' : '未开放' }}，不影响仿真账户。
      </p>

      <button
        v-if="stage === 'editing'"
        data-test="create-review-draft"
        class="primary-action"
        type="submit"
        :disabled="!canCreate"
      >
        创建并复核草稿
      </button>
      <button
        v-else-if="stage === 'review_failed'"
        class="primary-action"
        type="button"
        @click="retryReview"
      >
        重新请求风险复核
      </button>
      <p v-else-if="stage === 'creating'" class="operation-state" role="status">
        正在创建草稿…
      </p>
      <p v-else-if="stage === 'reviewing'" class="operation-state" role="status">
        草稿已创建，正在执行风险复核…
      </p>

      <div v-if="stage === 'reviewed' && currentDraft" class="review-summary">
        <div class="review-heading">
          <strong v-if="risk?.status === 'passed'">风险复核通过</strong>
          <strong v-else-if="softRiskPending">存在需确认的软风险</strong>
          <strong v-else-if="hardBlocked" class="error-state">风险复核阻断</strong>
          <span>规则 {{ risk?.rule_version.version || '—' }}</span>
        </div>
        <dl>
          <div><dt>标的</dt><dd>{{ currentDraft.draft.instrument_id }}</dd></div>
          <div><dt>方向</dt><dd>{{ currentDraft.draft.side }}</dd></div>
          <div><dt>数量</dt><dd>{{ currentDraft.draft.quantity }}</dd></div>
          <div><dt>价格</dt><dd>{{ currentDraft.draft.limit_price ?? '市价' }}</dd></div>
          <div><dt>风险有效至</dt><dd>{{ risk ? new Date(risk.expires_at).toLocaleString('zh-CN') : '—' }}</dd></div>
        </dl>
        <dl v-if="costEstimate" data-test="cost-estimate" class="cost-estimate">
          <div>
            <dt>参考价</dt>
            <dd>
              ¥{{ money(costEstimate.reference_price) }}
              <em>{{ costEstimate.price_source === 'limit_price' ? '限价' : '市价含滑点' }}</em>
            </dd>
          </div>
          <div><dt>交易金额</dt><dd>¥{{ money(costEstimate.notional) }}</dd></div>
          <div>
            <dt>预估手续费</dt>
            <dd>¥{{ money(costEstimate.fee) }} <em>{{ costEstimate.fee_bps }} bps</em></dd>
          </div>
          <div class="cost-total">
            <dt>{{ costEstimate.cash_flow === 'outflow' ? '预估总支出' : '预估到账' }}</dt>
            <dd>¥{{ money(costEstimate.total) }}</dd>
          </div>
          <div v-if="projectedCash !== null">
            <dt>成交后可用</dt>
            <dd :class="{ 'error-state': projectedCash < 0 }">¥{{ money(projectedCash) }}</dd>
          </div>
        </dl>
        <p v-else class="condition-note">
          当前草稿无法预估金额（缺少参考价）。手续费与滑点由后端仿真规则计算。
        </p>
        <ul v-if="risk?.reasons.length" class="risk-reasons">
          <li v-for="reason in risk.reasons" :key="reason.code">
            <strong>{{ reason.severity === 'hard' ? '硬阻断' : '需确认' }}</strong>
            {{ reason.message }}
          </li>
        </ul>
        <button
          v-if="softRiskPending"
          class="primary-action"
          type="button"
          @click="acknowledgeSoftRisk"
        >
          确认已阅读软风险
        </button>
        <template v-else-if="!hardBlocked">
          <label class="acknowledgement">
            <input
              v-model="summaryAcknowledged"
              data-test="summary-acknowledgement"
              type="checkbox"
            />
            我已核对账户、标的、方向、数量、价格与风险时点
          </label>
          <button
            data-test="confirm-draft"
            class="primary-action"
            type="button"
            :disabled="!canConfirmSummary"
            @click="confirmSummary"
          >
            确认订单摘要
          </button>
        </template>
      </div>

      <p v-if="stage === 'confirming_risk'" class="operation-state" role="status">
        正在记录软风险确认…
      </p>
      <p v-if="stage === 'confirming'" class="operation-state" role="status">
        正在确认不可变订单摘要…
      </p>
      <div v-if="stage === 'confirmed'" class="confirmed-state">
        <strong>草稿已确认</strong>
        <span>提交后将创建仿真订单，订单状态需在执行中心继续跟踪。</span>
        <button
          data-test="submit-draft"
          class="primary-action"
          type="button"
          @click="submitConfirmedDraft"
        >
          提交仿真订单
        </button>
      </div>
      <p v-if="stage === 'submitting'" class="operation-state" role="status">
        请求已发送，正在等待仿真执行方响应；请勿重复提交。
      </p>
      <div v-if="stage === 'unknown'" class="ticket-state error-state" role="alert">
        <strong>提交结果未知</strong>
        <span>{{ workflowError }}</span>
        <router-link to="/orders" class="secondary-action">前往执行中心查询</router-link>
      </div>
      <div v-if="stage === 'submitted'" class="ticket-state success-state" role="status">
        <strong>仿真订单请求已创建</strong>
        <span>
          订单 {{ orderId || '—' }}，服务端状态 {{ submittedStatus }}；
          请求已发送不等于执行方已受理或已成交。
        </span>
        <router-link to="/orders" class="secondary-action">查看订单状态</router-link>
      </div>
      <p
        v-if="workflowError && stage !== 'unknown'"
        class="form-error"
        role="alert"
      >
        {{ workflowError }}
      </p>
    </form>
  </section>
</template>

<style scoped>
.ticket { border-top: 1px solid var(--rule); }
.section-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin: 0;
  padding: 18px 18px 7px;
  border-bottom: 1px solid var(--rule);
  font-size: 15px;
  font-weight: 900;
}
.section-title small {
  color: var(--muted-ink);
  font-family: var(--font-numeric);
  font-size: 8px;
  letter-spacing: .1em;
}
.ticket-form { display: grid; gap: 10px; padding: 14px 18px 18px; }
.ticket-form label:not(.acknowledgement) { display: grid; gap: 4px; }
.ticket-form label > span { color: var(--muted-ink); font-size: 11px; }
.ticket-form input,
.ticket-form select { min-height: 34px; font-size: 13px; }
.account-line {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 3px 10px;
  padding-bottom: 9px;
  border-bottom: 1px solid var(--faint-rule);
  font-size: 12px;
}
.account-line strong { overflow: hidden; text-overflow: ellipsis; }
.account-line span:last-child { grid-column: 1 / -1; color: var(--muted-ink); }
.primary-action,
.secondary-action {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--ink);
  font: inherit;
  font-weight: 800;
  text-decoration: none;
  cursor: pointer;
}
.primary-action { width: 100%; background: var(--ink); color: var(--paper-light); }
.primary-action:disabled { cursor: not-allowed; opacity: .45; }
.secondary-action { margin-top: 8px; padding: 0 12px; background: transparent; color: var(--ink); }
.ticket-state {
  display: grid;
  gap: 5px;
  padding: 18px;
  color: var(--muted-ink);
  font-size: 13px;
}
.ticket-state strong { color: var(--ink); }
.condition-note,
.operation-state,
.form-error { margin: 0; padding: 8px 10px; border-left: 3px solid var(--rule); font-size: 12px; }
.form-error,
.error-state { color: var(--risk); }
.form-error { border-left-color: var(--risk); background: #f5ebe8; }
.review-summary {
  display: grid;
  gap: 10px;
  padding-top: 10px;
  border-top: 3px double var(--rule);
}
.review-heading { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; }
.review-heading span { color: var(--muted-ink); }
.review-summary dl { margin: 0; }
.review-summary dl > div { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--faint-rule); }
.review-summary dt { color: var(--muted-ink); font-size: 12px; }
.review-summary dd { margin: 0; font: 12px var(--font-numeric); }
.cost-estimate { padding-top: 4px; }
.cost-estimate dd { display: flex; align-items: baseline; gap: 6px; }
.cost-estimate dd em { color: var(--muted-ink); font-size: 10px; font-style: normal; }
.cost-estimate .cost-total dt,
.cost-estimate .cost-total dd { font-weight: 800; }
.cost-estimate .cost-total dt { color: var(--ink); }
.risk-reasons { margin: 0; padding: 0; list-style: none; }
.risk-reasons li { padding: 6px 0; border-bottom: 1px solid var(--faint-rule); font-size: 12px; }
.acknowledgement { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; }
.acknowledgement input { min-height: auto; margin-top: 2px; }
.confirmed-state { display: grid; gap: 6px; font-size: 12px; }
.confirmed-state span { color: var(--muted-ink); }
.success-state { border-left: 3px solid var(--positive); }
@media (prefers-reduced-motion: reduce) {
  .primary-action,
  .secondary-action { transition: none; }
}
</style>
