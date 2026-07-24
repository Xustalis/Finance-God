<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Masthead from '@/components/desk/Masthead.vue'
import {
  confirmTradePlanAndGenerateDrafts,
  fetchTradePlan,
  newIdempotencyKey,
  saveTradePlanVersion,
} from '@/api/desk'
import { useAiContextStore } from '@/stores/aiContext'
import type {
  TradePlanActionRevision,
  TradePlanCapability,
  TradePlanPageView,
  TradePlanStatus,
} from '@/types/desk'

const route = useRoute()
const router = useRouter()
const ai = useAiContextStore()
const view = ref<TradePlanPageView | null>(null)
const loading = ref(true)
const submitting = ref(false)
const error = ref<string | null>(null)
const resultMessage = ref<string | null>(null)
const actionDrafts = ref<Record<string, { quantity: string; included: boolean }>>({})
let confirmationKey: string | null = null

const planId = computed(() => String(route.params.planId || ''))
const plan = computed(() => view.value?.object ?? null)
const sourceRoute = computed(() =>
  view.value?.source_type === 'candidate' ? '/watchlist' : '/portfolio',
)
const sourceLabel = computed(() =>
  view.value?.source_type === 'candidate' ? '系统候选' : '组合集中度偏离',
)
const confirmationCapability = computed(() =>
  capability('confirm_and_generate'),
)
const saveCapability = computed(() => capability('save_version'))

const STATUS_LABEL: Record<TradePlanStatus, string> = {
  draft: '草稿',
  pending_review: '待审阅',
  confirmed: '已确认',
  executing: '执行中',
  partially_completed: '部分完成',
  completed: '已完成',
  expired: '已失效',
  rejected: '已拒绝',
  cancelled: '已取消',
}

function capability(action: TradePlanCapability['action']) {
  return view.value?.capabilities.find((item) => item.action === action) ?? null
}

function syncActionDrafts(next: TradePlanPageView) {
  actionDrafts.value = Object.fromEntries(
    next.object.actions.map((action) => [
      action.action_id,
      {
        quantity: action.quantity === null ? '' : String(action.quantity),
        included: action.included,
      },
    ]),
  )
}

function applyView(next: TradePlanPageView) {
  view.value = next
  syncActionDrafts(next)
  ai.setContext({
    scope: 'portfolio',
    subject: `交易计划 ${next.object.plan_id} 版本 ${next.object.revision}`,
    label: `交易计划 · v${next.object.revision}`,
  })
}

async function loadPlan() {
  loading.value = true
  error.value = null
  try {
    applyView(await fetchTradePlan(planId.value))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    loading.value = false
  }
}

function revisionPayload(): TradePlanActionRevision[] {
  if (!plan.value) return []
  return plan.value.actions.map((action) => {
    const draft = actionDrafts.value[action.action_id]
    const rawQuantity = String(draft?.quantity ?? '').trim()
    const quantity = rawQuantity ? Number(rawQuantity) : null
    if (quantity !== null && (!Number.isFinite(quantity) || quantity <= 0)) {
      throw new Error(`${action.instrument_id} 的数量必须大于 0`)
    }
    return {
      action_id: action.action_id,
      quantity,
      included: draft?.included ?? action.included,
    }
  })
}

async function saveVersion() {
  if (!plan.value || submitting.value) return
  submitting.value = true
  error.value = null
  resultMessage.value = null
  try {
    const next = await saveTradePlanVersion(
      plan.value.plan_id,
      plan.value.revision,
      revisionPayload(),
    )
    applyView(next)
    resultMessage.value = `已保存计划版本 v${next.object.revision}`
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    submitting.value = false
  }
}

async function confirmAndGenerate() {
  if (!plan.value || submitting.value || !confirmationCapability.value?.enabled) return
  submitting.value = true
  error.value = null
  resultMessage.value = null
  try {
    confirmationKey ??= newIdempotencyKey('trade-plan-confirm')
    const next = await confirmTradePlanAndGenerateDrafts(
      plan.value.plan_id,
      plan.value.revision,
      confirmationKey,
    )
    applyView(next)
    resultMessage.value = `计划已确认，已生成 ${next.draft_links.length} 个订单草稿`
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    submitting.value = false
  }
}

function formatMoney(value: number | null): string {
  if (value === null) return '—'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
  }).format(value)
}

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

onMounted(loadPlan)
</script>

<template>
  <div class="plan-page">
    <Masthead />

    <main class="plan-canvas" :aria-busy="loading">
      <div v-if="loading" class="page-state" role="status">正在加载交易计划…</div>
      <div v-else-if="error && !view" class="page-state error-state" role="alert">
        <strong>交易计划加载失败</strong>
        <span>{{ error }}</span>
        <button type="button" class="secondary-action" @click="loadPlan">重新加载计划</button>
      </div>

      <template v-else-if="view && plan">
        <header class="plan-header">
          <div>
            <p class="kicker">组合 · 交易计划 T04</p>
            <h1 tabindex="-1">交易计划 {{ plan.plan_id }}</h1>
            <p class="identity-line">
              <strong>{{ STATUS_LABEL[plan.status] }}</strong>
              <span>版本 v{{ plan.revision }}</span>
              <span>仿真账户 {{ plan.account_id }}</span>
              <span>来源：{{ sourceLabel }}</span>
            </p>
          </div>
          <div class="data-stamp">
            <span>{{ view.data_status.provider }}</span>
            <strong>{{ formatTime(view.data_status.provider_time) }}</strong>
            <span>{{ view.data_status.frequency || '频率未知' }} · {{ view.data_status.freshness }}</span>
          </div>
        </header>

        <section class="reason-strip" aria-labelledby="plan-purpose">
          <div>
            <h2 id="plan-purpose">调整目的</h2>
            <p>{{ plan.purpose }}</p>
          </div>
          <div>
            <h2>适用与失效</h2>
            <p>本版本有效至 {{ formatTime(plan.expires_at) }}；输入版本变化后旧版本不能生成草稿。</p>
          </div>
          <div>
            <h2>不行动后果</h2>
            <p>{{ view.source_type === 'portfolio_deviation' ? '组合继续超过单一资产集中度阈值。' : '候选保持研究状态，不创建计划订单。' }}</p>
          </div>
        </section>

        <div v-if="view.warnings.length" class="warning-list" role="alert">
          <p v-for="warning in view.warnings" :key="warning.code">
            <strong>{{ warning.severity === 'blocking' ? '阻断' : '提示' }}</strong>
            {{ warning.message }}
          </p>
        </div>
        <p v-if="error" class="command-error" role="alert">{{ error }}</p>
        <p v-if="resultMessage" class="command-result" role="status">{{ resultMessage }}</p>

        <div class="workspace">
          <section class="actions-region" aria-labelledby="actions-heading">
            <div class="region-heading">
              <div>
                <h2 id="actions-heading">候选动作与执行依赖</h2>
                <p>数量是本页唯一业务输入；保存后由后端按最新 PandaData 参考价生成新版本。</p>
              </div>
              <span>{{ plan.actions.length }} 个动作</span>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">纳入</th>
                    <th scope="col">标的 / 依据</th>
                    <th scope="col">方向</th>
                    <th scope="col" class="num">参考价</th>
                    <th scope="col" class="num">数量</th>
                    <th scope="col">草稿</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="action in plan.actions" :key="action.action_id">
                    <td>
                      <input
                        v-model="actionDrafts[action.action_id].included"
                        type="checkbox"
                        :disabled="!saveCapability?.enabled || submitting"
                        :aria-label="`${action.instrument_id} 纳入计划`"
                      />
                    </td>
                    <td>
                      <strong class="mono">{{ action.instrument_id }}</strong>
                      <small>{{ action.rationale }}</small>
                    </td>
                    <td :class="action.side === 'buy' ? 'positive' : 'risk'">
                      {{ action.side === 'buy' ? '买入' : '卖出' }}
                    </td>
                    <td class="num">{{ formatMoney(action.reference_price) }}</td>
                    <td class="num">
                      <input
                        v-model="actionDrafts[action.action_id].quantity"
                        class="quantity-input"
                        type="number"
                        min="0.00000001"
                        step="1"
                        inputmode="decimal"
                        :disabled="!actionDrafts[action.action_id].included || !saveCapability?.enabled || submitting"
                        :aria-label="`${action.instrument_id} 计划数量`"
                      />
                    </td>
                    <td>
                      <router-link
                        v-if="view.draft_links.find((link) => link.action_id === action.action_id)"
                        :to="`/desk?draft=${view.draft_links.find((link) => link.action_id === action.action_id)?.draft_id}`"
                        class="inline-link"
                      >
                        进入交易台
                      </router-link>
                      <span v-else>尚未生成</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <aside class="impact-region" aria-labelledby="impact-heading">
            <div class="region-heading">
              <div>
                <h2 id="impact-heading">组合影响与校验</h2>
                <p>以下结果均绑定当前计划版本。</p>
              </div>
            </div>
            <dl class="impact-list">
              <div>
                <dt>费用估算</dt>
                <dd>{{ formatMoney(plan.estimated_fee_rmb) }}</dd>
              </div>
              <div>
                <dt>计划影响</dt>
                <dd>{{ plan.portfolio_impact }}</dd>
              </div>
              <div>
                <dt>输入版本</dt>
                <dd>{{ plan.input_versions.length }} 个快照</dd>
              </div>
              <div>
                <dt>分歧与排除</dt>
                <dd>{{ plan.disagreements.length ? plan.disagreements.join('；') : '无已记录分歧' }}</dd>
              </div>
            </dl>

            <section class="history">
              <h3>版本历史</h3>
              <ol>
                <li v-for="item in view.history" :key="item.revision">
                  <strong>v{{ item.revision }} · {{ STATUS_LABEL[item.status] }}</strong>
                  <span>{{ formatTime(item.recorded_at) }}</span>
                </li>
              </ol>
            </section>
          </aside>
        </div>

        <footer class="action-bar">
          <button type="button" class="text-action" @click="router.push(sourceRoute)">
            返回{{ sourceLabel }}
          </button>
          <div>
            <button
              type="button"
              data-test="save-plan-version"
              class="secondary-action"
              :disabled="submitting || !saveCapability?.enabled"
              @click="saveVersion"
            >
              {{ submitting ? '处理中…' : '保存新版本' }}
            </button>
            <button
              type="button"
              data-test="confirm-plan"
              class="primary-action"
              :disabled="submitting || !confirmationCapability?.enabled"
              :title="confirmationCapability?.reason || '确认当前计划并生成仿真订单草稿'"
              @click="confirmAndGenerate"
            >
              {{ submitting ? '处理中…' : '确认计划并生成草稿' }}
            </button>
          </div>
          <p v-if="!confirmationCapability?.enabled" class="disabled-reason">
            {{ confirmationCapability?.reason }}
          </p>
        </footer>
      </template>
    </main>
  </div>
</template>

<style scoped>
.plan-page {
  min-height: 100vh;
  border-top: 6px solid var(--ink);
  background: var(--paper);
  color: var(--ink);
  font-variant-numeric: tabular-nums lining-nums;
}
.plan-canvas { min-height: calc(100vh - 82px); padding: 12px 18px 88px; }
.page-state { display: grid; min-height: 60vh; place-content: center; gap: 10px; text-align: center; }
.error-state { color: var(--risk); }
.plan-header {
  display: flex; justify-content: space-between; gap: 24px; align-items: end;
  padding: 8px 0 12px; border-bottom: 3px double var(--rule);
}
.kicker { margin: 0 0 4px; color: var(--risk); font-size: 11px; font-weight: 900; letter-spacing: .12em; }
h1 { margin: 0; font-size: clamp(24px, 3vw, 36px); letter-spacing: -.02em; }
.identity-line { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 8px 0 0; color: var(--muted-ink); font-size: 12px; }
.identity-line strong { color: var(--ink); }
.data-stamp { display: grid; justify-items: end; gap: 2px; color: var(--muted-ink); font-size: 11px; }
.data-stamp strong { color: var(--ink); font-size: 13px; }
.reason-strip {
  display: grid; grid-template-columns: 1.15fr 1fr 1fr; border-bottom: 1px solid var(--rule);
}
.reason-strip > div { padding: 12px 16px; border-right: 1px solid var(--faint-rule); }
.reason-strip > div:last-child { border-right: 0; }
.reason-strip h2, .region-heading h2 { margin: 0; font-size: 13px; letter-spacing: .04em; }
.reason-strip p, .region-heading p { margin: 5px 0 0; color: var(--muted-ink); font-size: 12px; line-height: 1.5; }
.warning-list, .command-error, .command-result {
  margin: 10px 0 0; padding: 8px 12px; border: 1px solid var(--risk); font-size: 12px;
}
.warning-list p { margin: 0; }
.warning-list p + p { margin-top: 4px; }
.command-error { color: var(--risk); }
.command-result { border-color: var(--positive); color: var(--positive); }
.workspace { display: grid; grid-template-columns: minmax(0, 7fr) minmax(300px, 5fr); border-bottom: 1px solid var(--rule); }
.actions-region { min-width: 0; border-right: 1px solid var(--rule); }
.impact-region { min-width: 0; }
.region-heading {
  min-height: 58px; display: flex; justify-content: space-between; gap: 12px;
  padding: 12px 14px; border-bottom: 1px solid var(--rule);
}
.region-heading > span { color: var(--muted-ink); font-size: 12px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { padding: 9px 10px; border-bottom: 1px solid var(--faint-rule); text-align: left; vertical-align: top; }
th { color: var(--muted-ink); font-size: 11px; }
td small { display: block; max-width: 320px; margin-top: 3px; color: var(--muted-ink); line-height: 1.35; }
.num { text-align: right; }
.mono { font-family: var(--font-numeric); }
.positive { color: var(--positive); font-weight: 800; }
.risk { color: var(--risk); font-weight: 800; }
.quantity-input { width: 96px; min-height: 32px; padding: 4px 7px; text-align: right; border: 1px solid var(--rule); background: var(--paper-light); }
input[type="checkbox"] { accent-color: var(--ink); }
.inline-link { border-bottom: 1px solid var(--ink); font-weight: 800; }
.impact-list { margin: 0; padding: 4px 14px 10px; }
.impact-list > div { display: grid; grid-template-columns: 100px 1fr; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--faint-rule); }
.impact-list dt { color: var(--muted-ink); font-size: 12px; }
.impact-list dd { margin: 0; font-size: 12px; line-height: 1.5; }
.history { padding: 6px 14px 16px; }
.history h3 { margin: 8px 0; font-size: 13px; }
.history ol { list-style: none; margin: 0; padding: 0; }
.history li { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-bottom: 1px solid var(--faint-rule); font-size: 11px; }
.history li span { color: var(--muted-ink); }
.action-bar {
  position: sticky; bottom: 0; z-index: 20;
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  min-height: 66px; padding: 10px 18px; border-top: 3px double var(--rule); background: var(--paper-light);
}
.action-bar > div { display: flex; gap: 10px; margin-left: auto; }
.primary-action, .secondary-action, .text-action { min-height: 36px; padding: 7px 14px; font-weight: 800; }
.primary-action { border: 1px solid var(--ink); background: var(--ink); color: var(--paper-light); }
.secondary-action { border: 1px solid var(--rule); background: transparent; color: var(--ink); }
.text-action { border: 0; border-bottom: 1px solid var(--ink); background: transparent; color: var(--ink); }
button:disabled { cursor: not-allowed; opacity: .48; }
.disabled-reason { max-width: 300px; margin: 0; color: var(--risk); font-size: 11px; }
button:focus-visible, input:focus-visible, a:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

@media (max-width: 1279px) {
  .plan-canvas { padding-inline: 12px; }
  .workspace { grid-template-columns: minmax(0, 7fr) minmax(280px, 5fr); }
  .data-stamp { display: none; }
}
@media (prefers-reduced-motion: no-preference) {
  .plan-header, .reason-strip, .workspace { animation: plan-enter 180ms ease-out both; }
  .reason-strip { animation-delay: 30ms; }
  .workspace { animation-delay: 60ms; }
}
@keyframes plan-enter {
  from { opacity: 0; transform: translateY(3px); }
  to { opacity: 1; transform: none; }
}
</style>
