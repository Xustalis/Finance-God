<script setup lang="ts">
/**
 * ReviewsView — 复盘页
 * 左栏成交列表 + 主栏复盘分析 + 右栏绩效统计
 * 所有数据来自仿真交易 fills + orders API，无 mock
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import { useMarketStore } from '@/stores/market'
import { fetchOrders, fetchFills } from '@/api/desk'
import { formatNumber } from '@/types/desk'
import type { SimulationFill, StoredOrderView } from '@/types/desk'

const market = useMarketStore()

const orders = ref<StoredOrderView[]>([])
const fills = ref<SimulationFill[]>([])
const loading = ref(true)
const ordersError = ref<string | null>(null)
const fillsError = ref<string | null>(null)
const selectedFillId = ref<string | null>(null)

const selectedFill = computed(() => {
  if (!selectedFillId.value) return null
  return fills.value.find(f => f.fill_id === selectedFillId.value) ?? null
})

/** 订单总数（执行中心视图），仅用于统计展示。 */
const executionOrders = computed(() => orders.value)

/* 仅整理成交事实，不在浏览器推导收益或胜率。 */
const fillFactsBySymbol = computed(() => {
  const groups = new Map<string, number>()
  for (const fill of fills.value) {
    groups.set(fill.instrument_id, (groups.get(fill.instrument_id) ?? 0) + 1)
  }
  return [...groups].map(([symbol, fillCount]) => ({ symbol, fillCount }))
})

const totalTrades = computed(() => fills.value.length)

function failureMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback
}

async function loadData() {
  loading.value = true
  ordersError.value = null
  fillsError.value = null
  const [ord, fil] = await Promise.allSettled([fetchOrders(), fetchFills()])
  if (ord.status === 'fulfilled') {
    orders.value = Array.isArray(ord.value) ? ord.value : []
  } else {
    ordersError.value = failureMessage(ord.reason, '订单数据加载失败')
  }
  if (fil.status === 'fulfilled') {
    fills.value = Array.isArray(fil.value) ? fil.value : []
  } else {
    fillsError.value = failureMessage(fil.reason, '成交数据加载失败')
  }
  loading.value = false
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
          <span>成交记录</span>
          <small>FILLS</small>
        </h2>
        <div v-if="loading" class="summary-empty">加载中...</div>
        <div v-else-if="fillsError && fills.length === 0" class="summary-empty" role="alert">
          <strong class="down">成交数据加载失败</strong>
          <span>{{ fillsError }}</span>
        </div>
        <div v-else-if="fills.length === 0" class="summary-empty">
          <span>暂无成交记录</span>
        </div>
        <div v-else class="fill-list">
          <button
            v-for="fill in fills"
            :key="fill.fill_id"
            class="fill-item"
            :class="{ active: selectedFillId === fill.fill_id }"
            @click="selectedFillId = selectedFillId === fill.fill_id ? null : fill.fill_id"
          >
            <strong>{{ fill.instrument_id }}</strong>
            <span>成交</span>
            <span class="mono">{{ fill.quantity }} @ {{ formatNumber(fill.price) }}</span>
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
          <span>复盘</span>
          <span>REVIEWS</span>
        </div>
        <h1 class="lead-title">
          交易复盘
          <small v-if="totalTrades > 0">
            共 {{ totalTrades }} 笔成交 · 收益指标暂不可计算
          </small>
        </h1>
      </div>

      <div v-if="ordersError || fillsError" class="data-warning" role="alert">
        <p v-if="ordersError"><strong>订单数据加载失败：</strong>{{ ordersError }}。订单统计暂不可用。</p>
        <p v-if="fillsError"><strong>成交数据加载失败：</strong>{{ fillsError }}。无法确认当前是否存在成交。</p>
      </div>

      <div v-if="loading" class="table-state">加载复盘数据...</div>
      <div v-else-if="fillsError && fills.length === 0" class="table-state">
        <strong class="down">复盘事实不可用</strong>
        <span>成交请求失败，不能将当前结果解释为暂无成交。</span>
        <button class="secondary-button" style="margin-top:10px" @click="loadData">重试加载</button>
      </div>
      <div v-else-if="fills.length === 0" class="table-state">
        <span>暂无成交记录，无法生成复盘分析。</span>
        <router-link to="/desk" class="secondary-button" style="margin-top: 12px; display: inline-flex;">前往交易台</router-link>
      </div>

      <template v-else>
        <!-- 按标的整理成交事实；收益指标等待后端权威 projection。 -->
        <div class="review-section">
          <h2 class="section-heading">成交事实 <small>BY INSTRUMENT</small></h2>
          <div class="review-table">
            <div class="rtable-header">
              <span class="col-sym">标的</span>
              <span class="col-num">成交笔数</span>
              <span class="col-result">复盘指标</span>
            </div>
            <div v-for="p in fillFactsBySymbol" :key="p.symbol" class="rtable-row">
              <strong class="col-sym">{{ p.symbol }}</strong>
              <span class="col-num">{{ p.fillCount }}</span>
              <span class="col-result">后端暂无权威 projection，暂不可计算</span>
            </div>
          </div>
        </div>

        <!-- 选中成交详情 -->
        <div v-if="selectedFill" class="review-section">
          <h2 class="section-heading">成交详情 <small>FILL DETAIL</small></h2>
          <div class="detail-card">
            <div class="detail-row"><span>标的</span><strong>{{ selectedFill.instrument_id }}</strong></div>
            <div class="detail-row"><span>数量</span><strong>{{ selectedFill.quantity }}</strong></div>
            <div class="detail-row"><span>价格</span><strong>{{ formatNumber(selectedFill.price) }}</strong></div>
            <div class="detail-row"><span>费用</span><strong>{{ formatNumber(selectedFill.fee) }}</strong></div>
            <div class="detail-row"><span>成交时间</span><strong>{{ selectedFill.occurred_at }}</strong></div>
            <div class="detail-row"><span>订单 ID</span><strong style="font-size:11px;word-break:break-all;">{{ selectedFill.order_id }}</strong></div>
          </div>
        </div>
      </template>
    </template>

    <template #right>
      <section class="rail-section">
        <h2 class="section-title">
          <span>绩效统计</span>
          <small>PERFORMANCE</small>
        </h2>
        <div class="summary-grid">
          <div class="summary-row">
            <span>总成交</span>
            <strong>{{ fillsError && fills.length === 0 ? '暂不可用' : totalTrades }}</strong>
          </div>
          <div class="summary-row">
            <span>涉及标的</span>
            <strong>{{ fillsError && fills.length === 0 ? '暂不可用' : fillFactsBySymbol.length }}</strong>
          </div>
          <div class="summary-row">
            <span>已实现盈亏</span>
            <strong>暂不可计算</strong>
          </div>
          <div class="summary-row">
            <span>胜率</span>
            <strong>暂不可计算</strong>
          </div>
          <div class="summary-row">
            <span>总订单</span>
            <strong>{{ ordersError ? '暂不可用' : executionOrders.length }}</strong>
          </div>
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

.fill-list { max-height: 55vh; overflow-y: auto; scrollbar-width: thin; }
.fill-item {
  display: grid; grid-template-columns: minmax(0,1fr) 40px 1fr; gap: 6px;
  width: 100%; padding: 8px 18px; border: 0;
  border-bottom: 1px solid var(--faint-rule); background: transparent;
  font-size: 13px; text-align: left; cursor: pointer; transition: background 0.15s;
}
.fill-item:hover { background: var(--faint-rule); }
.fill-item.active { background: rgb(45 34 22 / 10%); border-left: 3px solid var(--risk); padding-left: 15px; }
.fill-item strong {
  font-family: var(--font-numeric); font-weight: 700;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.fill-item span:last-child {
  text-align: right; font-family: var(--font-numeric); font-size: 12px;
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
.data-warning p + p { margin-top: 4px; }

.review-section { margin-top: 20px; }
.section-heading {
  display: flex; align-items: baseline; gap: 10px;
  padding: 10px 20px 6px; font-size: 14px; font-weight: 900;
  letter-spacing: 0.03em; margin: 0; border-bottom: 1px solid var(--rule);
}
.section-heading small {
  color: var(--muted-ink); font-family: var(--font-numeric);
  font-size: 8px; font-weight: 700; letter-spacing: 0.1em;
}

.review-table { border-top: 1px solid var(--rule); }
.rtable-header {
  display: grid; grid-template-columns: minmax(0,1fr) 80px minmax(170px,1.5fr); gap: 4px;
  padding: 8px 20px 6px; font-size: 11px; font-weight: 900;
  color: var(--muted-ink); letter-spacing: 0.04em; border-bottom: 1px solid var(--rule);
}
.rtable-header .col-num { text-align: right; }
.rtable-row {
  display: grid; grid-template-columns: minmax(0,1fr) 80px minmax(170px,1.5fr); gap: 4px;
  padding: 10px 20px; border-bottom: 1px solid var(--faint-rule); font-size: 14px;
}
.rtable-row .col-num { text-align: right; font-family: var(--font-numeric); font-size: 13px; }
.rtable-row .col-sym {
  font-family: var(--font-numeric); font-weight: 700;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.col-result { text-align: right; color: var(--muted-ink); font-size: 12px; }

.detail-card { padding: 14px 20px; }
.detail-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 5px 0; font-size: 14px; border-bottom: 1px solid var(--faint-rule);
}
.detail-row:last-child { border-bottom: 0; }
.detail-row span { color: var(--muted-ink); }
.detail-row strong { font-family: var(--font-numeric); font-weight: 700; }

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
