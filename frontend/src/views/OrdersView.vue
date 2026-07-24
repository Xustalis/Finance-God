<script setup lang="ts">
/**
 * OrdersView — 订单页
 * 左栏筛选 + 主栏订单列表 + 右栏订单详情
 * 所有数据来自仿真交易后端 API，支持取消订单操作
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import { useMarketStore } from '@/stores/market'
import { fetchOrders, fetchFills, cancelOrder } from '@/api/desk'
import { formatNumber } from '@/types/desk'

const market = useMarketStore()

const orders = ref<any[]>([])
const fills = ref<any[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const filter = ref<'all' | 'pending' | 'filled' | 'cancelled'>('all')
const selectedOrderId = ref<string | null>(null)
const cancelling = ref<string | null>(null)
const cancelError = ref<string | null>(null)

const filteredOrders = computed(() => {
  if (filter.value === 'all') return orders.value
  return orders.value.filter(o => o.status === filter.value)
})

const selectedOrder = computed(() => {
  if (!selectedOrderId.value) return null
  return orders.value.find(o => o.order_id === selectedOrderId.value) ?? null
})

const orderFills = computed(() => {
  if (!selectedOrderId.value) return []
  return fills.value.filter(f => f.order_id === selectedOrderId.value)
})

const statusCounts = computed(() => {
  const counts = { all: orders.value.length, pending: 0, filled: 0, cancelled: 0 }
  for (const o of orders.value) {
    if (o.status === 'pending' || o.status === 'submitted' || o.status === 'accepted') counts.pending++
    else if (o.status === 'filled' || o.status === 'partially_filled') counts.filled++
    else if (o.status === 'cancelled' || o.status === 'rejected') counts.cancelled++
  }
  return counts
})

function canCancel(order: any): boolean {
  return ['pending', 'submitted', 'accepted', 'open'].includes(order.status)
}

async function handleCancel(orderId: string) {
  cancelling.value = orderId
  cancelError.value = null
  try {
    await cancelOrder(orderId)
    await loadData()
  } catch (e) {
    cancelError.value = e instanceof Error ? e.message : String(e)
  } finally {
    cancelling.value = null
  }
}

async function loadData() {
  loading.value = true
  error.value = null
  try {
    const [ord, fil] = await Promise.allSettled([fetchOrders(), fetchFills()])
    if (ord.status === 'fulfilled') orders.value = Array.isArray(ord.value) ? ord.value : []
    if (fil.status === 'fulfilled') fills.value = Array.isArray(fil.value) ? fil.value : []
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
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
            v-for="f in ([['all','全部'],['pending','待成交'],['filled','已成交'],['cancelled','已取消']] as const)"
            :key="f[0]"
            class="filter-button"
            :class="{ active: filter === f[0] }"
            @click="filter = f[0]"
          >
            {{ f[1] }}
            <span class="filter-count">{{ statusCounts[f[0]] }}</span>
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
          订单管理
          <small>{{ filteredOrders.length }} 条记录</small>
        </h1>
      </div>

      <div v-if="loading" class="table-state">加载订单数据...</div>
      <div v-else-if="error" class="table-state">
        <strong class="down">订单加载失败</strong>
        <span>{{ error }}</span>
        <button class="secondary-button" style="margin-top:10px" @click="loadData">重试</button>
      </div>
      <div v-else-if="filteredOrders.length === 0" class="table-state">
        <span>暂无{{ filter === 'all' ? '' : ({pending:'待成交',filled:'已成交',cancelled:'已取消'}[filter]) }}订单。</span>
        <router-link to="/desk" class="secondary-button" style="margin-top: 12px; display: inline-flex;">前往交易台</router-link>
      </div>
      <div v-else class="orders-table">
        <div class="otable-header">
          <span class="col-sym">标的</span>
          <span class="col-dir">方向</span>
          <span class="col-num">数量</span>
          <span class="col-num">价格</span>
          <span class="col-status">状态</span>
          <span class="col-action">操作</span>
        </div>
        <button
          v-for="order in filteredOrders"
          :key="order.order_id"
          class="otable-row"
          :class="{ active: selectedOrderId === order.order_id }"
          @click="selectedOrderId = selectedOrderId === order.order_id ? null : order.order_id"
        >
          <strong class="col-sym">{{ order.instrument_id || '—' }}</strong>
          <span class="col-dir" :class="order.side === 'buy' ? 'up' : 'down'">{{ order.side || '—' }}</span>
          <span class="col-num">{{ order.quantity ?? order.requested_quantity ?? '—' }}</span>
          <span class="col-num">{{ order.limit_price ? formatNumber(order.limit_price) : '市价' }}</span>
          <span class="col-status">{{ order.status || '—' }}</span>
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
        </button>
      </div>

      <p v-if="cancelError" class="form-error" style="margin: 12px 20px;" role="alert">
        {{ cancelError }}
        <button class="text-button" @click="cancelError = null">关闭</button>
      </p>
    </template>

    <template #right>
      <section class="rail-section">
        <h2 class="section-title">
          <span>订单详情</span>
          <small>DETAIL</small>
        </h2>
        <div v-if="selectedOrder" class="summary-grid">
          <div class="summary-row">
            <span>订单 ID</span>
            <strong style="font-size:11px;word-break:break-all;">{{ selectedOrder.order_id }}</strong>
          </div>
          <div class="summary-row">
            <span>标的</span>
            <strong>{{ selectedOrder.instrument_id }}</strong>
          </div>
          <div class="summary-row">
            <span>方向</span>
            <strong :class="selectedOrder.side === 'buy' ? 'up' : 'down'">{{ selectedOrder.side }}</strong>
          </div>
          <div class="summary-row">
            <span>类型</span>
            <strong>{{ selectedOrder.order_type || '—' }}</strong>
          </div>
          <div class="summary-row">
            <span>委托数量</span>
            <strong>{{ selectedOrder.quantity ?? selectedOrder.requested_quantity ?? '—' }}</strong>
          </div>
          <div class="summary-row">
            <span>委托价格</span>
            <strong>{{ selectedOrder.limit_price ? formatNumber(selectedOrder.limit_price) : '市价' }}</strong>
          </div>
          <div class="summary-row">
            <span>状态</span>
            <strong>{{ selectedOrder.status }}</strong>
          </div>
          <div class="summary-row">
            <span>成交笔数</span>
            <strong>{{ orderFills.length }}</strong>
          </div>
          <div v-if="canCancel(selectedOrder)" class="rail-action">
            <button
              class="secondary-button"
              :disabled="cancelling === selectedOrder.order_id"
              @click="handleCancel(selectedOrder.order_id)"
            >
              {{ cancelling === selectedOrder.order_id ? '取消中...' : '撤销此单' }}
            </button>
          </div>
        </div>
        <div v-else class="summary-empty">
          <span>点击订单查看详情</span>
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

.orders-table { border-top: 1px solid var(--rule); }
.otable-header {
  display: grid; grid-template-columns: minmax(0,1fr) 50px 70px 80px 70px 60px; gap: 4px;
  padding: 8px 20px 6px; font-size: 11px; font-weight: 900;
  color: var(--muted-ink); letter-spacing: 0.04em; border-bottom: 1px solid var(--rule);
}
.otable-header .col-num, .otable-header .col-status, .otable-header .col-action { text-align: right; }

.otable-row {
  display: grid; grid-template-columns: minmax(0,1fr) 50px 70px 80px 70px 60px; gap: 4px;
  width: 100%; padding: 10px 20px; border: 0;
  border-bottom: 1px solid var(--faint-rule); background: transparent;
  font-size: 14px; text-align: left; cursor: pointer; transition: background 0.15s;
}
.otable-row:hover { background: var(--faint-rule); }
.otable-row.active { background: rgb(45 34 22 / 10%); border-left: 3px solid var(--risk); padding-left: 17px; }

.otable-row .col-sym {
  font-family: var(--font-numeric); font-weight: 700;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.otable-row .col-num, .otable-row .col-status {
  text-align: right; font-family: var(--font-numeric); font-size: 13px;
}
.otable-row .col-dir { font-size: 12px; font-weight: 700; }
.otable-row .col-action { text-align: right; }

.cancel-btn {
  padding: 2px 8px; font-size: 11px; font-weight: 700;
  background: transparent; border: 1px solid var(--risk); color: var(--risk);
  cursor: pointer; transition: all 0.15s;
}
.cancel-btn:hover:not(:disabled) { background: var(--risk); color: var(--paper-light); }

.summary-grid { padding: 14px 18px; }
.summary-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 5px 0; font-size: 14px; border-bottom: 1px solid var(--faint-rule);
}
.summary-row:last-child { border-bottom: 0; }
.summary-row span { color: var(--muted-ink); }
.summary-row strong { font-family: var(--font-numeric); font-weight: 700; }

.summary-empty { padding: 28px 18px; color: var(--muted-ink); font-size: 13px; text-align: center; }
</style>
