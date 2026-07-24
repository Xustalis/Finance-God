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

const market = useMarketStore()

const orders = ref<any[]>([])
const fills = ref<any[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const selectedFillId = ref<string | null>(null)

const selectedFill = computed(() => {
  if (!selectedFillId.value) return null
  return fills.value.find(f => (f.fill_id || f.order_id) === selectedFillId.value) ?? null
})

/* 按标的分组的盈亏统计 */
const pnlBySymbol = computed(() => {
  const groups = new Map<string, { buys: number[]; sells: number[]; buyQty: number; sellQty: number }>()
  for (const fill of fills.value) {
    const id = fill.instrument_id || 'unknown'
    if (!groups.has(id)) groups.set(id, { buys: [], sells: [], buyQty: 0, sellQty: 0 })
    const g = groups.get(id)!
    const qty = Number(fill.quantity ?? fill.fill_quantity ?? 0)
    const price = Number(fill.price ?? fill.fill_price ?? 0)
    if (fill.side === 'buy') { g.buys.push(price); g.buyQty += qty }
    else { g.sells.push(price); g.sellQty += qty }
  }
  const results: { symbol: string; buyCount: number; sellCount: number; avgBuy: number; avgSell: number; realized: number }[] = []
  for (const [symbol, g] of groups) {
    const avgBuy = g.buys.length > 0 ? g.buys.reduce((a, b) => a + b, 0) / g.buys.length : 0
    const avgSell = g.sells.length > 0 ? g.sells.reduce((a, b) => a + b, 0) / g.sells.length : 0
    const realized = g.sellQty > 0 ? (avgSell - avgBuy) * Math.min(g.buyQty, g.sellQty) : 0
    results.push({ symbol, buyCount: g.buys.length, sellCount: g.sells.length, avgBuy, avgSell, realized })
  }
  return results
})

const totalRealized = computed(() => pnlBySymbol.value.reduce((s, p) => s + p.realized, 0))
const totalTrades = computed(() => fills.value.length)
const winTrades = computed(() => pnlBySymbol.value.filter(p => p.realized > 0).length)
const winRate = computed(() => {
  const profitable = pnlBySymbol.value.filter(p => p.sellCount > 0)
  if (profitable.length === 0) return 0
  return Math.round((winTrades.value / profitable.length) * 100)
})

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
          <span>成交记录</span>
          <small>FILLS</small>
        </h2>
        <div v-if="loading" class="summary-empty">加载中...</div>
        <div v-else-if="fills.length === 0" class="summary-empty">
          <span>暂无成交记录</span>
        </div>
        <div v-else class="fill-list">
          <button
            v-for="fill in fills"
            :key="fill.fill_id || fill.order_id"
            class="fill-item"
            :class="{ active: selectedFillId === (fill.fill_id || fill.order_id) }"
            @click="selectedFillId = selectedFillId === (fill.fill_id || fill.order_id) ? null : (fill.fill_id || fill.order_id)"
          >
            <strong>{{ fill.instrument_id || '—' }}</strong>
            <span :class="fill.side === 'buy' ? 'up' : 'down'">{{ fill.side }}</span>
            <span class="mono">{{ fill.quantity ?? fill.fill_quantity ?? '—' }} @ {{ formatNumber(fill.price ?? fill.fill_price) }}</span>
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
            共 {{ totalTrades }} 笔成交 · 胜率 {{ winRate }}%
          </small>
        </h1>
      </div>

      <div v-if="loading" class="table-state">加载复盘数据...</div>
      <div v-else-if="error" class="table-state">
        <strong class="down">加载失败</strong>
        <span>{{ error }}</span>
        <button class="secondary-button" style="margin-top:10px" @click="loadData">重试</button>
      </div>
      <div v-else-if="fills.length === 0" class="table-state">
        <span>暂无成交记录，无法生成复盘分析。</span>
        <router-link to="/desk" class="secondary-button" style="margin-top: 12px; display: inline-flex;">前往交易台</router-link>
      </div>

      <template v-else>
        <!-- 按标的分组复盘 -->
        <div class="review-section">
          <h2 class="section-heading">标的分析 <small>BY INSTRUMENT</small></h2>
          <div class="review-table">
            <div class="rtable-header">
              <span class="col-sym">标的</span>
              <span class="col-num">买入</span>
              <span class="col-num">卖出</span>
              <span class="col-num">均价买</span>
              <span class="col-num">均价卖</span>
              <span class="col-num">已实现盈亏</span>
            </div>
            <div v-for="p in pnlBySymbol" :key="p.symbol" class="rtable-row">
              <strong class="col-sym">{{ p.symbol }}</strong>
              <span class="col-num">{{ p.buyCount }}</span>
              <span class="col-num">{{ p.sellCount }}</span>
              <span class="col-num">{{ formatNumber(p.avgBuy) }}</span>
              <span class="col-num">{{ p.avgSell > 0 ? formatNumber(p.avgSell) : '—' }}</span>
              <span class="col-num" :class="p.realized >= 0 ? 'up' : 'down'">
                {{ p.realized !== 0 ? (p.realized > 0 ? '+' : '') + formatNumber(p.realized) : '—' }}
              </span>
            </div>
          </div>
        </div>

        <!-- 选中成交详情 -->
        <div v-if="selectedFill" class="review-section">
          <h2 class="section-heading">成交详情 <small>FILL DETAIL</small></h2>
          <div class="detail-card">
            <div class="detail-row"><span>标的</span><strong>{{ selectedFill.instrument_id }}</strong></div>
            <div class="detail-row"><span>方向</span><strong :class="selectedFill.side === 'buy' ? 'up' : 'down'">{{ selectedFill.side }}</strong></div>
            <div class="detail-row"><span>数量</span><strong>{{ selectedFill.quantity ?? selectedFill.fill_quantity }}</strong></div>
            <div class="detail-row"><span>价格</span><strong>{{ formatNumber(selectedFill.price ?? selectedFill.fill_price) }}</strong></div>
            <div class="detail-row"><span>订单 ID</span><strong style="font-size:11px;word-break:break-all;">{{ selectedFill.order_id || '—' }}</strong></div>
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
            <strong>{{ totalTrades }}</strong>
          </div>
          <div class="summary-row">
            <span>涉及标的</span>
            <strong>{{ pnlBySymbol.length }}</strong>
          </div>
          <div class="summary-row">
            <span>已实现盈亏</span>
            <strong :class="totalRealized >= 0 ? 'up' : 'down'">
              {{ totalRealized >= 0 ? '+' : '' }}{{ formatNumber(totalRealized) }}
            </strong>
          </div>
          <div class="summary-row">
            <span>胜率</span>
            <strong>{{ winRate }}%</strong>
          </div>
          <div class="summary-row">
            <span>总订单</span>
            <strong>{{ orders.length }}</strong>
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
  display: grid; grid-template-columns: minmax(0,1fr) 50px 50px 80px 80px 100px; gap: 4px;
  padding: 8px 20px 6px; font-size: 11px; font-weight: 900;
  color: var(--muted-ink); letter-spacing: 0.04em; border-bottom: 1px solid var(--rule);
}
.rtable-header .col-num { text-align: right; }
.rtable-row {
  display: grid; grid-template-columns: minmax(0,1fr) 50px 50px 80px 80px 100px; gap: 4px;
  padding: 10px 20px; border-bottom: 1px solid var(--faint-rule); font-size: 14px;
}
.rtable-row .col-num { text-align: right; font-family: var(--font-numeric); font-size: 13px; }
.rtable-row .col-sym {
  font-family: var(--font-numeric); font-weight: 700;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

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
