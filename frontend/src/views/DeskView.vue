<script setup lang="ts">
/**
 * DeskView — 交易台页
 * 左栏标的列表 + 主栏图表/行情 + 右栏研究/草稿
 */
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import MarketTable from '@/components/desk/MarketTable.vue'
import MarketChart from '@/components/desk/MarketChart.vue'
import { useMarketStore } from '@/stores/market'
import { fetchCurrentAccount, fetchOrders } from '@/api/desk'
import { DEFAULT_SYMBOLS, directionOf, formatPercent, formatChange, formatNumber } from '@/types/desk'
import type { MarketQuote, SimulationAccount } from '@/types/desk'

const market = useMarketStore()
const activeSymbol = ref(DEFAULT_SYMBOLS[0])

// 仿真交易状态
const account = ref<SimulationAccount | null>(null)
const accountError = ref<string | null>(null)
const orders = ref<any[]>([])
const ordersError = ref<string | null>(null)

const activeQuote = computed<MarketQuote | null>(() => {
  return market.quotesMap.get(activeSymbol.value) ?? null
})

watch(activeSymbol, (sym) => {
  if (sym) market.loadBars(sym)
})

async function loadAccount() {
  accountError.value = null
  try {
    account.value = await fetchCurrentAccount() as SimulationAccount
  } catch (err) {
    accountError.value = err instanceof Error ? err.message : String(err)
    account.value = null
  }
}

async function loadOrders() {
  ordersError.value = null
  try {
    const data = await fetchOrders()
    orders.value = Array.isArray(data) ? data : []
  } catch (err) {
    ordersError.value = err instanceof Error ? err.message : String(err)
    orders.value = []
  }
}

onMounted(() => {
  market.startPolling()
  market.checkHealth()
  if (activeSymbol.value) market.loadBars(activeSymbol.value)
  loadAccount()
  loadOrders()
})

onUnmounted(() => {
  market.stopPolling()
})
</script>

<template>
  <DeskLayout>
    <!-- 左栏：标的列表 -->
    <template #left>
      <section class="rail-section">
        <h2 class="section-title">
          <span>标的选择</span>
          <small>INSTRUMENTS</small>
        </h2>
        <MarketTable
          :quotes="market.quotes"
          :loading="market.quotesLoading"
          :error="market.quotesError"
          :active-symbol="activeSymbol"
          @select="(s: string) => activeSymbol = s"
        />
      </section>
    </template>

    <!-- 主栏：图表 + 行情详情 -->
    <template #main>
      <div class="lead-header">
        <div class="lead-kicker">
          <span>交易台</span>
          <span>TRADING DESK</span>
        </div>
        <h1 class="lead-title">
          {{ activeQuote ? activeQuote.symbol : '选择标的' }}
          <small v-if="activeQuote" :class="directionOf(activeQuote)">
            {{ formatNumber(activeQuote.last) }}
            {{ formatChange(activeQuote.change) }}
            ({{ formatPercent(activeQuote.change_percent) }})
          </small>
        </h1>
      </div>

      <!-- 行情条 -->
      <div class="ticker-strip" v-if="market.quotes.length > 0">
        <div
          v-for="q in market.quotes.slice(0, 6)"
          :key="q.symbol"
          class="ticker"
          :class="{ active: q.symbol === activeSymbol }"
          @click="activeSymbol = q.symbol"
        >
          <span>{{ q.symbol }}</span>
          <strong :class="directionOf(q)">{{ formatPercent(q.change_percent) }}</strong>
        </div>
      </div>

      <!-- K线图 -->
      <MarketChart
        :bars="market.bars"
        :symbol="activeSymbol"
        :loading="market.barsLoading"
        :error="market.barsError"
      />

      <!-- 行情明细 -->
      <div class="detail-grid" v-if="activeQuote">
        <div class="detail-item">
          <span>开盘</span>
          <strong>{{ formatNumber(activeQuote.open) }}</strong>
        </div>
        <div class="detail-item">
          <span>最高</span>
          <strong>{{ formatNumber(activeQuote.high) }}</strong>
        </div>
        <div class="detail-item">
          <span>最低</span>
          <strong>{{ formatNumber(activeQuote.low) }}</strong>
        </div>
        <div class="detail-item">
          <span>昨收</span>
          <strong>{{ formatNumber(activeQuote.previous_close) }}</strong>
        </div>
        <div class="detail-item">
          <span>成交量</span>
          <strong>{{ formatNumber(activeQuote.volume, 0) }}</strong>
        </div>
        <div class="detail-item">
          <span>新鲜度</span>
          <strong>{{ activeQuote.freshness }}</strong>
        </div>
      </div>
    </template>

    <!-- 右栏：研究/草稿 -->
    <template #right>
      <section class="rail-section">
        <h2 class="section-title">
          <span>仿真账户</span>
          <small>SIMULATION</small>
        </h2>
        <div v-if="account" class="summary-grid">
          <div class="summary-row">
            <span>可用资金</span>
            <strong>{{ formatNumber(account.cash_available_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>总资产</span>
            <strong>{{ formatNumber(account.cash_total_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>冻结</span>
            <strong>{{ formatNumber(account.cash_frozen_rmb) }}</strong>
          </div>
          <div class="summary-row">
            <span>状态</span>
            <strong>{{ account.status }}</strong>
          </div>
        </div>
        <div v-else class="summary-empty">
          <strong v-if="accountError" class="down">仿真服务不可用</strong>
          <span>{{ accountError || '未创建仿真账户' }}</span>
        </div>
      </section>

      <section class="rail-section">
        <h2 class="section-title">
          <span>近期订单</span>
          <small>RECENT ORDERS</small>
        </h2>
        <div v-if="orders.length > 0" class="order-list">
          <div v-for="order in orders.slice(0, 5)" :key="order.order_id" class="order-row">
            <strong>{{ order.instrument_id || '—' }}</strong>
            <span>{{ order.side || '—' }}</span>
            <span>{{ order.status || '—' }}</span>
          </div>
        </div>
        <div v-else class="summary-empty">
          <strong v-if="ordersError" class="down">订单加载失败</strong>
          <span>{{ ordersError || '暂无订单' }}</span>
        </div>
      </section>
    </template>
  </DeskLayout>
</template>

<style scoped>
.rail-section {
  padding: 0;
}
.rail-section + .rail-section {
  border-top: 1px solid var(--rule);
}

.section-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 18px 18px 7px;
  border-bottom: 1px solid var(--rule);
  font-size: 15px;
  font-weight: 900;
  letter-spacing: 0.04em;
  margin: 0;
}
.section-title small {
  color: var(--muted-ink);
  font-family: var(--font-numeric);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.1em;
  white-space: nowrap;
}

.lead-header { margin-bottom: 12px; }
.lead-kicker {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 5px;
  padding-bottom: 4px;
  border-bottom: 3px double var(--rule);
  color: var(--muted-ink);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.13em;
}
.lead-kicker span:first-child { color: var(--risk); font-size: 10px; font-weight: 900; }
.lead-title {
  font-size: clamp(1.8rem, 3vw, 2.8rem);
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -0.02em;
  margin: 0;
}
.lead-title small {
  display: block;
  font-size: 0.5em;
  font-family: var(--font-numeric);
  font-weight: 700;
  margin-top: 4px;
}

.ticker-strip {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 18px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--rule);
  overflow-x: auto;
  scrollbar-width: none;
  white-space: nowrap;
}
.ticker-strip::-webkit-scrollbar { display: none; }
.ticker {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-family: var(--font-numeric);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  padding: 4px 0;
  border-bottom: 2px solid transparent;
  transition: border-color 0.18s;
}
.ticker:hover { border-bottom-color: var(--faint-rule); }
.ticker.active { border-bottom-color: var(--risk); }
.ticker strong { font-size: 15px; }

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0;
  margin-top: 18px;
  border-top: 1px solid var(--rule);
}
.detail-item {
  padding: 12px 0;
  display: grid;
  gap: 2px;
  border-bottom: 1px solid var(--faint-rule);
}
.detail-item:nth-child(3n+1),
.detail-item:nth-child(3n+2) {
  border-right: 1px solid var(--faint-rule);
  padding-right: 12px;
}
.detail-item:nth-child(3n+2),
.detail-item:nth-child(3n+3) {
  padding-left: 12px;
}
.detail-item span { color: var(--muted-ink); font-size: 11px; }
.detail-item strong { font-family: var(--font-numeric); font-size: 14px; }

.summary-grid, .data-meta { padding: 14px 18px; }
.summary-grid + .data-meta { border-top: 1px solid var(--rule); }
.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 5px 0;
  font-size: 14px;
  border-bottom: 1px solid var(--faint-rule);
}
.summary-row:last-child { border-bottom: 0; }
.summary-row span { color: var(--muted-ink); }
.summary-row strong { font-family: var(--font-numeric); font-weight: 700; }

.summary-empty {
  padding: 22px 18px;
  color: var(--muted-ink);
  font-size: 13px;
  text-align: center;
}
.summary-empty strong { display: block; margin-bottom: 4px; }

.order-list { padding: 8px 18px; }
.order-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 50px 60px;
  gap: 6px;
  padding: 6px 0;
  border-bottom: 1px solid var(--faint-rule);
  font-size: 13px;
}
.order-row:last-child { border-bottom: 0; }
.order-row strong {
  font-family: var(--font-numeric);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.order-row span { text-align: right; }
</style>
