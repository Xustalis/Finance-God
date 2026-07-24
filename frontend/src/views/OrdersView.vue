<script setup lang="ts">
/**
 * OrdersView — 订单执行中心
 * 左栏筛选 + 主栏订单列表 + 右栏订单详情（完整字段 + 状态时间线 + 对账）。
 * 数据来自仿真交易后端 StoredOrderView：完整委托字段、累计成交、均价、费用、
 * 执行错误与状态时间线。异常订单可发起对账（reconcile）向上游同步真实状态。
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import { useMarketStore } from '@/stores/market'
import { fetchOrders, cancelOrder, reconcileOrder } from '@/api/desk'
import type { StoredOrderView } from '@/types/desk'

const market = useMarketStore()

const orders = ref<StoredOrderView[]>([])
const loading = ref(true)
const ordersError = ref<string | null>(null)
const filter = ref<'all' | 'active' | 'filled' | 'closed' | 'exception'>('all')
const selectedOrderId = ref<string | null>(null)
const cancelling = ref<string | null>(null)
const reconciling = ref<string | null>(null)
const actionError = ref<string | null>(null)

/** 非终态：仍可能变化，可对账。终态订单不再向上游查询。 */
const TERMINAL = ['filled', 'cancelled', 'rejected', 'expired']

const STATUS_LABELS: Record<string, string> = {
  submitting: '提交中',
  unknown: '状态未知',
  accepted: '已受理',
  partially_filled: '部分成交',
  filled: '全部成交',
  cancelling: '撤销中',
  cancelled: '已撤销',
  rejected: '已拒绝',
  expired: '已过期',
  confirmed: '已确认',
  FILLED: '全部成交',
  PARTIALLY_FILLED: '部分成交',
}
function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

const SIDE_LABELS: Record<string, string> = { buy: '买入', sell: '卖出', short: '卖空' }
function sideLabel(side: string | null): string {
  return side ? (SIDE_LABELS[side] ?? side) : '—'
}

const ORDER_TYPE_LABELS: Record<string, string> = { market: '市价', limit: '限价' }
function orderTypeLabel(type: string): string {
  return ORDER_TYPE_LABELS[type] ?? type
}

const TIF_LABELS: Record<string, string> = {
  day: '当日有效',
  good_til_cancelled: '撤销前有效',
  immediate_or_cancel: '立即成交否则撤销',
}
function tifLabel(tif: string | null): string {
  return tif ? (TIF_LABELS[tif] ?? tif) : '—'
}

function formatRmb(value: number): string {
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}
function formatQty(value: number): string {
  return Number.isInteger(value)
    ? value.toString()
    : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value)
}
function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

function isException(order: StoredOrderView): boolean {
  return order.execution_error !== null
    || order.status === 'unknown'
    || order.status === 'rejected'
}

const filteredOrders = computed(() => {
  switch (filter.value) {
    case 'active':
      return orders.value.filter((o) =>
        ['submitting', 'unknown', 'accepted', 'partially_filled', 'cancelling'].includes(o.status),
      )
    case 'filled':
      return orders.value.filter((o) => o.status === 'filled')
    case 'closed':
      return orders.value.filter((o) => ['cancelled', 'rejected', 'expired'].includes(o.status))
    case 'exception':
      return orders.value.filter(isException)
    default:
      return orders.value
  }
})

const selectedOrder = computed(() => {
  if (!selectedOrderId.value) return null
  return orders.value.find((o) => o.order_id === selectedOrderId.value) ?? null
})

const statusCounts = computed(() => ({
  all: orders.value.length,
  active: orders.value.filter((o) =>
    ['submitting', 'unknown', 'accepted', 'partially_filled', 'cancelling'].includes(o.status),
  ).length,
  filled: orders.value.filter((o) => o.status === 'filled').length,
  closed: orders.value.filter((o) => ['cancelled', 'rejected', 'expired'].includes(o.status)).length,
  exception: orders.value.filter(isException).length,
}))

const FILTER_LABELS: Record<typeof filter.value, string> = {
  all: '全部',
  active: '在途',
  filled: '已成交',
  closed: '已了结',
  exception: '异常',
}

function canCancel(order: StoredOrderView): boolean {
  return order.order_kind === 'exchange'
    && ['submitting', 'accepted', 'partially_filled'].includes(order.status)
}
/** 非终态或存在执行错误时允许对账：向上游查询真实状态并回填。 */
function canReconcile(order: StoredOrderView): boolean {
  return order.order_kind === 'exchange'
    && (!TERMINAL.includes(order.status) || order.execution_error !== null)
}

function toggleOrderSelection(orderId: string) {
  selectedOrderId.value = selectedOrderId.value === orderId ? null : orderId
}

function failureMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback
}

async function handleCancel(orderId: string) {
  cancelling.value = orderId
  actionError.value = null
  try {
    await cancelOrder(orderId)
    await loadData()
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e)
  } finally {
    cancelling.value = null
  }
}

async function handleReconcile(orderId: string) {
  reconciling.value = orderId
  actionError.value = null
  try {
    await reconcileOrder(orderId)
    await loadData()
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e)
  } finally {
    reconciling.value = null
  }
}

async function loadData() {
  loading.value = true
  ordersError.value = null
  try {
    orders.value = await fetchOrders()
  } catch (e) {
    ordersError.value = failureMessage(e, '订单数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  market.startPolling()
  market.checkHealth()
  loadData()
})
onUnmounted(() => market.stopPolling())
</script>

<template>
  <DeskLayout>
    <template #left>
      <section class="rail-section">
        <h2 class="section-title">
          <span>筛选</span>
          <small>FILTER</small>
        </h2>
        <div class="filter-group">
          <button
            v-for="key in (['all','active','filled','closed','exception'] as const)"
            :key="key"
            class="filter-button"
            :class="{ active: filter === key, alert: key === 'exception' && statusCounts.exception > 0 }"
            @click="filter = key"
          >
            {{ FILTER_LABELS[key] }}
            <span class="filter-count">
              {{ ordersError && orders.length === 0 ? '不可用' : statusCounts[key] }}
            </span>
          </button>
        </div>
        <div class="rail-action">
          <button class="secondary-button" :disabled="loading" @click="loadData">刷新</button>
        </div>
      </section>
    </template>

    <template #main>
      <div class="lead-header">
        <div class="lead-kicker">
          <span>订单</span>
          <span>ORDERS</span>
        </div>
        <h1 class="lead-title">
          执行中心
          <small>{{ ordersError && orders.length === 0 ? '结果不可用' : `${filteredOrders.length} 条记录` }}</small>
        </h1>
      </div>

      <div v-if="ordersError" class="data-warning" role="alert">
        <p><strong>订单数据加载失败：</strong>{{ ordersError }}。当前结果不能判断为空。</p>
      </div>

      <div v-if="loading" class="table-state">加载订单数据...</div>
      <div v-else-if="ordersError && orders.length === 0" class="table-state">
        <strong class="down">订单结果不可用</strong>
        <span>无法确认当前是否存在订单，请重试。</span>
        <button class="secondary-button" style="margin-top:10px" @click="loadData">重试加载</button>
      </div>
      <div v-else-if="filteredOrders.length === 0" class="table-state">
        <span>暂无{{ filter === 'all' ? '' : FILTER_LABELS[filter] }}订单。</span>
        <router-link to="/desk" class="secondary-button" style="margin-top: 12px; display: inline-flex;">前往交易台</router-link>
      </div>
      <div v-else class="orders-table">
        <div class="otable-header">
          <span class="col-sym">标的</span>
          <span class="col-dir">方向</span>
          <span class="col-num">委托量</span>
          <span class="col-num">已成交</span>
          <span class="col-num">均价</span>
          <span class="col-status">状态</span>
          <span class="col-action">操作</span>
        </div>
        <div
          v-for="order in filteredOrders"
          :key="order.order_id"
          class="otable-row"
          :class="{ active: selectedOrderId === order.order_id, exception: isException(order) }"
        >
          <button
            class="order-select"
            :aria-pressed="selectedOrderId === order.order_id"
            @click="toggleOrderSelection(order.order_id)"
          >
            <strong class="col-sym">{{ order.instrument_id }}</strong>
            <span class="col-dir" :class="order.side === 'buy' ? 'up' : order.side === 'sell' ? 'down' : ''">{{ sideLabel(order.side) }}</span>
            <span class="col-num">{{ formatQty(order.quantity) }}</span>
            <span class="col-num">{{ formatQty(order.cumulative_filled) }}</span>
            <span class="col-num">{{ order.average_fill_price === null ? '—' : `¥${formatRmb(order.average_fill_price)}` }}</span>
            <span class="col-status">{{ statusLabel(order.status) }}</span>
          </button>
          <span class="col-action">
            <button
              v-if="canCancel(order)"
              class="cancel-btn"
              :disabled="cancelling === order.order_id"
              @click.stop="handleCancel(order.order_id)"
            >
              {{ cancelling === order.order_id ? '取消中...' : '撤单' }}
            </button>
          </span>
        </div>
      </div>

      <p v-if="actionError" class="form-error" style="margin: 12px 20px;" role="alert">
        {{ actionError }}
        <button class="text-button" @click="actionError = null">关闭</button>
      </p>
    </template>

    <template #right>
      <section class="rail-section">
        <h2 class="section-title">
          <span>订单详情</span>
          <small>DETAIL</small>
        </h2>
        <div v-if="selectedOrder" class="detail-body">
          <div class="summary-grid">
            <div class="summary-row">
              <span>订单 ID</span>
              <strong class="mono-id">{{ selectedOrder.order_id }}</strong>
            </div>
            <div class="summary-row">
              <span>标的</span>
              <strong>{{ selectedOrder.instrument_id }}</strong>
            </div>
            <div class="summary-row">
              <span>方向</span>
              <strong :class="selectedOrder.side === 'buy' ? 'up' : selectedOrder.side === 'sell' ? 'down' : ''">
                {{ sideLabel(selectedOrder.side) }}
              </strong>
            </div>
            <div class="summary-row">
              <span>类型</span>
              <strong>{{ orderTypeLabel(selectedOrder.order_type) }} · {{ selectedOrder.order_kind === 'exchange' ? '场内' : '基金' }}</strong>
            </div>
            <div class="summary-row">
              <span>委托价格</span>
              <strong>{{ selectedOrder.limit_price === null ? '市价' : `¥${formatRmb(selectedOrder.limit_price)}` }}</strong>
            </div>
            <div class="summary-row">
              <span>有效期</span>
              <strong>{{ tifLabel(selectedOrder.time_in_force) }}</strong>
            </div>
            <div class="summary-row">
              <span>委托数量</span>
              <strong>{{ formatQty(selectedOrder.quantity) }}</strong>
            </div>
            <div class="summary-row">
              <span>累计成交</span>
              <strong>{{ formatQty(selectedOrder.cumulative_filled) }}</strong>
            </div>
            <div class="summary-row">
              <span>剩余数量</span>
              <strong>{{ formatQty(selectedOrder.remaining_quantity) }}</strong>
            </div>
            <div class="summary-row">
              <span>成交均价</span>
              <strong>{{ selectedOrder.average_fill_price === null ? '—' : `¥${formatRmb(selectedOrder.average_fill_price)}` }}</strong>
            </div>
            <div class="summary-row">
              <span>成交金额</span>
              <strong>¥{{ formatRmb(selectedOrder.filled_notional_rmb) }}</strong>
            </div>
            <div class="summary-row">
              <span>累计费用</span>
              <strong>¥{{ formatRmb(selectedOrder.total_fee_rmb) }}</strong>
            </div>
            <div class="summary-row">
              <span>状态</span>
              <strong>{{ statusLabel(selectedOrder.status) }}</strong>
            </div>
            <div class="summary-row">
              <span>确认时间</span>
              <strong class="ts">{{ formatTime(selectedOrder.confirmed_at) }}</strong>
            </div>
            <div class="summary-row">
              <span>更新时间</span>
              <strong class="ts">{{ formatTime(selectedOrder.updated_at) }}</strong>
            </div>
          </div>

          <div v-if="selectedOrder.execution_error" class="exec-error" role="alert">
            <strong>执行错误</strong>
            <span>{{ selectedOrder.execution_error }}</span>
          </div>

          <!-- 状态时间线 -->
          <div class="timeline-block">
            <h3 class="detail-heading">状态时间线</h3>
            <ol v-if="selectedOrder.timeline.length > 0" class="timeline">
              <li v-for="(entry, idx) in selectedOrder.timeline" :key="idx" class="timeline-item">
                <span class="tl-status">{{ statusLabel(entry.status) }}</span>
                <span class="tl-time">{{ formatTime(entry.occurred_at) }}</span>
                <span v-if="entry.detail" class="tl-detail">{{ entry.detail }}</span>
              </li>
            </ol>
            <p v-else class="detail-empty">暂无时间线记录。</p>
          </div>

          <!-- 成交明细 -->
          <div class="fills-block">
            <h3 class="detail-heading">成交明细 <small>{{ selectedOrder.fills.length }} 笔</small></h3>
            <table v-if="selectedOrder.fills.length > 0" class="fills-table">
              <thead>
                <tr>
                  <th scope="col">时间</th>
                  <th scope="col" class="num">数量</th>
                  <th scope="col" class="num">成交价</th>
                  <th scope="col" class="num">费用</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="fill in selectedOrder.fills" :key="fill.fill_id">
                  <td class="ts">{{ formatTime(fill.occurred_at) }}</td>
                  <td class="num">{{ formatQty(fill.quantity) }}</td>
                  <td class="num">¥{{ formatRmb(fill.price) }}</td>
                  <td class="num">¥{{ formatRmb(fill.fee) }}</td>
                </tr>
              </tbody>
            </table>
            <p v-else class="detail-empty">暂无成交。</p>
          </div>

          <div v-if="canCancel(selectedOrder) || canReconcile(selectedOrder)" class="detail-actions">
            <button
              v-if="canReconcile(selectedOrder)"
              class="secondary-button"
              :disabled="reconciling === selectedOrder.order_id"
              @click="handleReconcile(selectedOrder.order_id)"
            >
              {{ reconciling === selectedOrder.order_id ? '对账中...' : '对账（向上游同步）' }}
            </button>
            <button
              v-if="canCancel(selectedOrder)"
              class="secondary-button"
              :disabled="cancelling === selectedOrder.order_id"
              @click="handleCancel(selectedOrder.order_id)"
            >
              {{ cancelling === selectedOrder.order_id ? '取消中...' : '撤销此单' }}
            </button>
          </div>
        </div>
        <div v-else class="summary-empty">
          <span>点击订单查看完整字段、状态时间线与成交明细</span>
        </div>
      </section>
    </template>
  </DeskLayout>
</template>

<style scoped>
.rail-section { padding: 0; }
.rail-section + .rail-section { border-top: 1px solid var(--rule); }

.section-title {
  display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
  padding: 18px 18px 7px; border-bottom: 1px solid var(--rule);
  font-size: 15px; font-weight: 900; letter-spacing: 0.04em; margin: 0;
}
.section-title small {
  color: var(--muted-ink); font-family: var(--font-numeric);
  font-size: 8px; font-weight: 700; letter-spacing: 0.1em; white-space: nowrap;
}

.filter-group { padding: 12px 18px; display: grid; gap: 4px; }
.filter-button {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; background: transparent; border: 1px solid var(--faint-rule);
  color: var(--ink); font-size: 13px; font-weight: 600; cursor: pointer;
  transition: all 0.15s;
}
.filter-button:hover { border-color: var(--rule); }
.filter-button.active { border-color: var(--risk); background: rgb(143 48 39 / 5%); font-weight: 900; }
.filter-button.alert .filter-count { color: var(--risk); font-weight: 900; }
.filter-count {
  font-family: var(--font-numeric); font-size: 12px; color: var(--muted-ink);
}

.rail-action { padding: 14px 18px; }

.lead-header { margin-bottom: 12px; }
.lead-kicker {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 5px; padding-bottom: 4px; border-bottom: 3px double var(--rule);
  color: var(--muted-ink); font-size: 9px; font-weight: 700; letter-spacing: 0.13em;
}
.lead-kicker span:first-child { color: var(--risk); font-size: 10px; font-weight: 900; }
.lead-title {
  font-size: clamp(1.8rem, 3vw, 2.8rem); font-weight: 700; line-height: 1.1;
  letter-spacing: -0.02em; margin: 0;
}
.lead-title small {
  display: block; font-size: 0.5em; font-family: var(--font-numeric);
  font-weight: 700; margin-top: 4px;
}

.table-state { padding: 40px 20px; color: var(--muted-ink); font-size: 14px; text-align: center; }
.table-state strong { display: block; margin-bottom: 4px; }
.data-warning {
  margin: 0 20px 12px; padding: 9px 12px; border: 1px solid var(--risk);
  color: var(--risk); font-size: 12px;
}
.data-warning p { margin: 0; }

.orders-table { border-top: 1px solid var(--rule); }
.otable-header {
  display: grid; grid-template-columns: minmax(0,1fr) 50px 70px 70px 80px 70px 60px; gap: 4px;
  padding: 8px 20px 6px; font-size: 11px; font-weight: 900;
  color: var(--muted-ink); letter-spacing: 0.04em; border-bottom: 1px solid var(--rule);
}
.otable-header .col-num, .otable-header .col-status, .otable-header .col-action { text-align: right; }

.otable-row {
  display: grid; grid-template-columns: minmax(0,1fr) 60px; gap: 4px;
  width: 100%; padding: 10px 20px; border: 0;
  border-bottom: 1px solid var(--faint-rule); background: transparent;
  font-size: 14px; text-align: left; transition: background 0.15s;
}
.otable-row:hover { background: var(--faint-rule); }
.otable-row.active { background: rgb(45 34 22 / 10%); border-left: 3px solid var(--risk); padding-left: 17px; }
.otable-row.exception { border-left: 3px solid var(--risk); padding-left: 17px; }
.order-select {
  display: grid; grid-template-columns: minmax(0,1fr) 50px 70px 70px 80px 70px; gap: 4px;
  padding: 0; border: 0; background: transparent; color: inherit;
  font: inherit; text-align: left; cursor: pointer;
}

.order-select .col-sym {
  font-family: var(--font-numeric); font-weight: 700;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.order-select .col-num, .order-select .col-status {
  text-align: right; font-family: var(--font-numeric); font-size: 13px;
}
.order-select .col-dir { font-size: 12px; font-weight: 700; }
.otable-row .col-action { text-align: right; }

.cancel-btn {
  padding: 2px 8px; font-size: 11px; font-weight: 700;
  background: transparent; border: 1px solid var(--risk); color: var(--risk);
  cursor: pointer; transition: all 0.15s;
}
.cancel-btn:hover:not(:disabled) { background: var(--risk); color: var(--paper-light); }

.detail-body { padding-bottom: 18px; }
.summary-grid { padding: 14px 18px; }
.summary-row {
  display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
  padding: 5px 0; font-size: 14px; border-bottom: 1px solid var(--faint-rule);
}
.summary-row:last-child { border-bottom: 0; }
.summary-row span { color: var(--muted-ink); }
.summary-row strong { font-family: var(--font-numeric); font-weight: 700; text-align: right; }
.summary-row strong.mono-id { font-size: 11px; word-break: break-all; }
.summary-row strong.ts { font-size: 11px; }

.exec-error {
  margin: 4px 18px 0; padding: 9px 12px; border: 1px solid var(--risk);
  color: var(--risk); font-size: 12px; display: grid; gap: 3px;
}

.detail-heading {
  display: flex; align-items: baseline; gap: 8px;
  padding: 14px 18px 6px; margin: 0; font-size: 13px; font-weight: 900;
  letter-spacing: 0.03em; border-bottom: 1px solid var(--faint-rule);
}
.detail-heading small { color: var(--muted-ink); font-family: var(--font-numeric); font-size: 10px; font-weight: 700; }
.detail-empty { padding: 10px 18px; color: var(--muted-ink); font-size: 12px; }

.timeline { list-style: none; margin: 0; padding: 10px 18px; display: grid; gap: 8px; }
.timeline-item {
  display: grid; grid-template-columns: auto 1fr; gap: 2px 10px;
  padding-left: 12px; border-left: 2px solid var(--rule); font-size: 12px;
}
.tl-status { font-weight: 900; }
.tl-time { font-family: var(--font-numeric); color: var(--muted-ink); text-align: right; }
.tl-detail { grid-column: 1 / -1; color: var(--muted-ink); }

.fills-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.fills-table th, .fills-table td {
  padding: 6px 18px; border-bottom: 1px solid var(--faint-rule); text-align: left;
}
.fills-table thead th {
  color: var(--muted-ink); font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
}
.fills-table .num { text-align: right; font-family: var(--font-numeric); font-weight: 700; }
.fills-table .ts { font-family: var(--font-numeric); font-size: 11px; }

.detail-actions { padding: 14px 18px 0; display: grid; gap: 8px; }

.summary-empty { padding: 28px 18px; color: var(--muted-ink); font-size: 13px; text-align: center; }

.up { color: var(--positive); }
.down { color: var(--risk); }
</style>
