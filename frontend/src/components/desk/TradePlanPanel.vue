<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { TradePlan, TradePlanActionRevision } from '@/services/tradingDesk'

const props = defineProps<{
  plan: TradePlan | null
  loading: boolean
  error: string | null
  onRevise: (actions: TradePlanActionRevision[]) => void | Promise<void>
  onConfirm: () => void | Promise<void>
  onDismiss: () => void
}>()

const editing = ref(false)

interface EditableAction {
  action_id: string
  instrument_id: string
  side: string
  order_type: string
  quantity: string
  rationale: string
  included: boolean
}

const editableActions = ref<EditableAction[]>([])

const planActions = computed(() =>
  props.plan?.object.actions.map((a) => ({
    action_id: a.action_id,
    instrument_id: a.instrument_id,
    side: a.side,
    order_type: a.order_type ?? 'market',
    quantity: a.quantity ?? '',
    rationale: a.rationale ?? '',
    included: a.included,
  })) ?? [],
)

watch(() => props.plan, () => { editing.value = false }, { deep: true })

function startEdit() {
  editableActions.value = planActions.value.map((a) => ({ ...a }))
  editing.value = true
}

function cancelEdit() {
  editing.value = false
}

async function submitRevision() {
  const actions: TradePlanActionRevision[] = editableActions.value.map((a) => ({
    action_id: a.action_id,
    quantity: a.quantity || null,
    included: a.included,
  }))
  await props.onRevise(actions)
  editing.value = false
}

function sideLabel(side: string): string {
  const map: Record<string, string> = { buy: '买入', sell: '卖出', short: '做空', cover: '平空' }
  return map[side] ?? side
}

function typeLabel(type: string): string {
  return type === 'market' ? '市价' : type === 'limit' ? '限价' : type
}

const statusLabel = computed(() => {
  const s = props.plan?.object.status
  if (s === 'pending_review') return '待审核'
  if (s === 'confirmed') return '已确认'
  if (s === 'cancelled') return '已取消'
  return s ?? '未知'
})

const canConfirm = computed(() =>
  props.plan?.object.status === 'pending_review'
  && !props.loading
  && planActions.value.some((a) => a.included),
)
</script>

<template>
  <section v-if="plan" class="overview-section trade-plan-section" aria-labelledby="trade-plan-title">
    <header>
      <h2 id="trade-plan-title">交易计划</h2>
      <small>{{ statusLabel }} · 修订 {{ plan.object.revision }} · 来源 {{ plan.source_type }}</small>
    </header>

    <!-- Actions table: read mode -->
    <div v-if="!editing" class="market-table-wrap">
      <table class="market-table">
        <thead>
          <tr>
            <th scope="col">纳入</th>
            <th scope="col">标的</th>
            <th scope="col">方向</th>
            <th scope="col">类型</th>
            <th scope="col" class="numeric">数量</th>
            <th scope="col">理由</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="action in planActions" :key="action.action_id" :class="{ excluded: !action.included }">
            <td>{{ action.included ? '✓' : '—' }}</td>
            <th scope="row">{{ action.instrument_id }}</th>
            <td>{{ sideLabel(action.side) }}</td>
            <td>{{ typeLabel(action.order_type) }}</td>
            <td class="numeric">{{ action.quantity || '待定' }}</td>
            <td class="rationale-cell">{{ action.rationale || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Actions table: edit mode -->
    <div v-else class="market-table-wrap">
      <table class="market-table">
        <thead>
          <tr>
            <th scope="col">纳入</th>
            <th scope="col">标的</th>
            <th scope="col">方向</th>
            <th scope="col">类型</th>
            <th scope="col" class="numeric">数量</th>
            <th scope="col">理由</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="action in editableActions" :key="action.action_id">
            <td><input type="checkbox" v-model="action.included"></td>
            <th scope="row">{{ action.instrument_id }}</th>
            <td>{{ sideLabel(action.side) }}</td>
            <td>{{ typeLabel(action.order_type) }}</td>
            <td class="numeric"><input type="number" v-model="action.quantity" min="1" step="1" class="qty-input"></td>
            <td class="rationale-cell">{{ action.rationale || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="data-error" role="alert">{{ error }}</p>

    <!-- Button group -->
    <div class="plan-actions">
      <template v-if="plan.object.status === 'pending_review'">
        <template v-if="!editing">
          <button class="ink-button" type="button" :disabled="!canConfirm" @click="onConfirm">
            {{ loading ? '正在确认' : '确认并生成草稿' }}
          </button>
          <button class="text-action" type="button" :disabled="loading" @click="startEdit">修订计划</button>
          <button class="text-action dismiss" type="button" :disabled="loading" @click="onDismiss">取消</button>
        </template>
        <template v-else>
          <button class="ink-button" type="button" :disabled="loading" @click="submitRevision">
            {{ loading ? '正在保存' : '保存修订' }}
          </button>
          <button class="text-action" type="button" @click="cancelEdit">放弃修改</button>
        </template>
      </template>
      <template v-else-if="plan.object.status === 'confirmed'">
        <p class="plan-confirmed-notice">计划已确认，草稿已生成。请在交易表单中核对并提交。</p>
        <button class="text-action" type="button" @click="onDismiss">关闭</button>
      </template>
      <template v-else>
        <button class="text-action" type="button" @click="onDismiss">关闭</button>
      </template>
    </div>
  </section>
</template>

<style scoped>
.trade-plan-section { margin-top: 1rem; }
.excluded { opacity: 0.5; }
.rationale-cell { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.82rem; color: var(--muted-ink); }
.qty-input { width: 80px; padding: 0.2rem 0.4rem; border: 1px solid var(--rule); background: var(--paper-light); font-variant-numeric: tabular-nums; font-family: inherit; font-size: 0.85rem; }
.plan-actions { display: flex; align-items: center; gap: 1rem; margin-top: 0.75rem; flex-wrap: wrap; }
.text-action { background: transparent; border: none; color: var(--muted-ink); cursor: pointer; font-family: inherit; font-size: 0.85rem; text-decoration: underline; padding: 0.3rem 0; }
.text-action:hover { color: var(--ink); }
.text-action.dismiss { color: var(--risk); }
.text-action.dismiss:hover { opacity: 0.8; }
.plan-confirmed-notice { font-size: 0.85rem; color: var(--positive); margin: 0; }
</style>
