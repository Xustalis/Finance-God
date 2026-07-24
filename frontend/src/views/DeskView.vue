<script setup lang="ts">
/**
 * DeskView — 交易台页
 * 左栏标的列表 + 主栏图表/行情 + 右栏研究/草稿
 * 标的池优先使用画像已选投资方向（路由 query 或服务端 selected）
 */
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRoute } from 'vue-router'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import MarketTable from '@/components/desk/MarketTable.vue'
import MarketChart from '@/components/desk/MarketChart.vue'
import SimulationOrderTicket from '@/components/desk/SimulationOrderTicket.vue'
import { profileApi } from '@/api'
import {
  defaultSymbolForDirection,
  directionDisplayName,
  directionKindLabel,
  parseInvestmentDirection,
  symbolsForDirection,
} from '@/services/directionDesk'
import { useMarketStore } from '@/stores/market'
import { fetchCurrentAccount, fetchOrders, isDeskApiError, searchInstruments } from '@/api/desk'
import { DEFAULT_SYMBOLS, directionOf, formatPercent, formatChange, formatNumber } from '@/types/desk'
import type { InvestmentDirection } from '@/types/api'
import type {
  InstrumentSummary,
  MarketQuote,
  SimulationAccount,
  StoredOrder,
  StoredOrderView,
} from '@/types/desk'

const route = useRoute()
const market = useMarketStore()
const selectedDirection = ref<InvestmentDirection | null>(null)
const directionLoading = ref(true)
const directionError = ref<string | null>(null)
const watchSymbols = ref<string[]>([...DEFAULT_SYMBOLS])
const activeSymbol = ref(DEFAULT_SYMBOLS[0])

// 仿真交易状态
const account = ref<SimulationAccount | null>(null)
const accountLoading = ref(true)
const accountMissing = ref(false)
const accountError = ref<string | null>(null)
const orders = ref<StoredOrderView[]>([])
const ordersError = ref<string | null>(null)

// 标的搜索（标的主数据）
const searchQuery = ref('')
const searchResults = ref<InstrumentSummary[]>([])
const searchLoading = ref(false)
const searchError = ref<string | null>(null)
const searchOpen = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null

const activeQuote = computed<MarketQuote | null>(() => {
  return market.quotesMap.get(activeSymbol.value) ?? null
})

const directionTitle = computed(() => (
  selectedDirection.value ? directionDisplayName(selectedDirection.value) : null
))

const directionKind = computed(() => (
  selectedDirection.value ? directionKindLabel(selectedDirection.value) : null
))

watch(activeSymbol, (sym) => {
  if (sym) market.loadBars(sym)
}, { immediate: true })

watch(searchQuery, (value) => {
  if (searchTimer) clearTimeout(searchTimer)
  const query = value.trim()
  searchError.value = null
  if (!query) {
    searchResults.value = []
    searchOpen.value = false
    return
  }
  searchTimer = setTimeout(() => {
    void runSearch(query)
  }, 250)
})

async function runSearch(query: string) {
  searchLoading.value = true
  searchError.value = null
  searchOpen.value = true
  try {
    const data = await searchInstruments(query)
    searchResults.value = data.instruments
  } catch (err) {
    searchResults.value = []
    searchError.value = err instanceof Error ? err.message : String(err)
  } finally {
    searchLoading.value = false
  }
}

function selectInstrument(instrument: InstrumentSummary) {
  const symbol = instrument.symbol
  if (!watchSymbols.value.includes(symbol)) {
    watchSymbols.value = [symbol, ...watchSymbols.value]
    market.setWatchSymbols(watchSymbols.value)
  }
  activeSymbol.value = symbol
  market.loadBars(symbol)
  searchQuery.value = ''
  searchResults.value = []
  searchOpen.value = false
}

function applyDirection(direction: InvestmentDirection | null) {
  selectedDirection.value = direction
  watchSymbols.value = symbolsForDirection(direction)
  activeSymbol.value = defaultSymbolForDirection(direction)
  market.startPolling(watchSymbols.value)
  if (activeSymbol.value) market.loadBars(activeSymbol.value)
}

async function resolveDirection() {
  directionLoading.value = true
  directionError.value = null
  const fromQuery = parseInvestmentDirection(route.query.direction)
  if (fromQuery) {
    applyDirection(fromQuery)
    directionLoading.value = false
    return
  }
  try {
    const data = await profileApi.latest()
    const selected = data.recommendations.find((item) => item.selected)
    applyDirection(selected ? selected.direction : null)
  } catch (err) {
    directionError.value = err instanceof Error ? err.message : String(err)
    applyDirection(null)
  } finally {
    directionLoading.value = false
  }
}

async function loadAccount() {
  accountLoading.value = true
  accountMissing.value = false
  accountError.value = null
  try {
    account.value = await fetchCurrentAccount()
  } catch (err) {
    account.value = null
    if (isDeskApiError(err, 404)) {
      accountMissing.value = true
    } else {
      accountError.value = err instanceof Error ? err.message : String(err)
    }
  } finally {
    accountLoading.value = false
  }
}

async function loadOrders() {
  ordersError.value = null
  try {
    const data = await fetchOrders()
    orders.value = data
  } catch (err) {
    ordersError.value = err instanceof Error ? err.message : String(err)
    orders.value = []
  }
}

function orderIdentity(order: StoredOrderView): string {
  return order.order_id
}

function orderStatus(order: StoredOrderView): string {
  return order.status
}

function handleSubmitted(_order: StoredOrder) {
  void loadOrders()
}

onMounted(() => {
  market.checkHealth()
  void resolveDirection()
  loadAccount()
  loadOrders()
})

onUnmounted(() => {
  if (searchTimer) clearTimeout(searchTimer)
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
          <small>{{ directionKind || 'INSTRUMENTS' }}</small>
        </h2>
        <p v-if="directionTitle" class="direction-scope" data-test="direction-scope">
          当前方向：{{ directionTitle }}（{{ directionKind }}）
        </p>
        <p v-else-if="directionLoading" class="direction-scope muted">正在读取投资方向…</p>
        <p v-else class="direction-scope muted" data-test="direction-scope-fallback">
          未选定投资方向，显示默认观察标的
        </p>
        <div class="symbol-search">
          <label class="search-field">
            <span class="visually-hidden">搜索标的</span>
            <input
              v-model="searchQuery"
              data-test="instrument-search"
              type="search"
              placeholder="搜索代码 / 别名，如 600519"
              autocomplete="off"
              @focus="searchOpen = searchResults.length > 0 || Boolean(searchError)"
            />
          </label>
          <div v-if="searchOpen" class="search-panel" data-test="instrument-search-panel">
            <p v-if="searchLoading" class="search-note" role="status">正在检索标的主数据…</p>
            <p v-else-if="searchError" class="search-note down" role="alert">检索失败：{{ searchError }}</p>
            <p v-else-if="searchResults.length === 0" class="search-note">无匹配标的。</p>
            <ul v-else class="search-results">
              <li v-for="item in searchResults" :key="item.symbol">
                <button
                  type="button"
                  class="search-result"
                  :data-test="`instrument-option-${item.symbol}`"
                  @click="selectInstrument(item)"
                >
                  <strong>{{ item.symbol }}</strong>
                  <span class="result-meta">{{ item.market }} · {{ item.asset_class }} · {{ item.frequency }}</span>
                  <span v-if="!item.simulation_supported" class="result-flag">不支持仿真下单</span>
                </button>
              </li>
            </ul>
          </div>
        </div>
        <MarketTable
          :quotes="market.quotes"
          :loading="market.quotesLoading || directionLoading"
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
          <span>{{ directionKind || 'TRADING DESK' }}</span>
        </div>
        <h1 class="lead-title">
          {{ activeQuote ? activeQuote.symbol : '选择标的' }}
          <small v-if="directionTitle" class="direction-badge" data-test="desk-direction">
            {{ directionTitle }} · {{ directionKind }}
          </small>
          <small v-if="activeQuote" :class="directionOf(activeQuote)">
            {{ formatNumber(activeQuote.last) }}
            {{ formatChange(activeQuote.change) }}
            ({{ formatPercent(activeQuote.change_percent) }})
          </small>
        </h1>
        <p v-if="directionError" class="direction-note" role="status">
          画像方向读取失败，已使用默认标的池。{{ directionError }}
        </p>
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
        <div v-if="accountLoading" class="summary-empty">加载仿真账户…</div>
        <div v-else-if="account" class="summary-grid">
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
        <div v-else-if="accountMissing" class="summary-empty">
          <strong>未初始化仿真账户</strong>
          <router-link to="/settings">前往设置</router-link>
        </div>
        <div v-else class="summary-empty">
          <strong v-if="accountError" class="down">仿真服务不可用</strong>
          <span>{{ accountError }}</span>
        </div>
      </section>

      <SimulationOrderTicket
        :account="account"
        :account-loading="accountLoading"
        :account-missing="accountMissing"
        :account-error="accountError"
        :quote="activeQuote"
        @submitted="handleSubmitted"
      />

      <section class="rail-section">
        <h2 class="section-title">
          <span>近期订单</span>
          <small>RECENT ORDERS</small>
        </h2>
        <div v-if="orders.length > 0" class="order-list">
          <div v-for="order in orders.slice(0, 5)" :key="orderIdentity(order)" class="order-row">
            <strong>{{ orderIdentity(order) }}</strong>
            <span>{{ order.draft_reference.object_id }}</span>
            <span>{{ orderStatus(order) }}</span>
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

.direction-scope {
  margin: 0;
  padding: 10px 18px 4px;
  color: var(--ink);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  border-bottom: 1px solid var(--faint-rule);
}
.direction-scope.muted {
  color: var(--muted-ink);
  font-weight: 500;
}

.symbol-search { position: relative; padding: 10px 18px; border-bottom: 1px solid var(--faint-rule); }
.search-field { display: block; }
.search-field input {
  width: 100%;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid var(--rule);
  background: var(--paper-light);
  font: 13px var(--font-numeric);
  color: var(--ink);
}
.search-field input:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
.search-panel {
  position: absolute;
  left: 18px;
  right: 18px;
  top: calc(100% - 6px);
  z-index: 20;
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid var(--ink);
  background: var(--paper-light);
}
.search-note { margin: 0; padding: 10px; color: var(--muted-ink); font-size: 12px; }
.search-note.down { color: var(--risk); }
.search-results { margin: 0; padding: 0; list-style: none; }
.search-result {
  display: grid;
  gap: 2px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-bottom: 1px solid var(--faint-rule);
  background: transparent;
  text-align: left;
  font: inherit;
  cursor: pointer;
}
.search-result:last-child { border-bottom: 0; }
.search-result:hover,
.search-result:focus-visible { background: var(--paper); outline: none; }
.search-result strong { font-family: var(--font-numeric); font-size: 13px; }
.result-meta { color: var(--muted-ink); font-size: 11px; }
.result-flag { color: var(--risk); font-size: 11px; }
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

.lead-header { margin-bottom: 12px; }
.direction-badge {
  display: block;
  color: var(--ink);
  font-family: var(--font-body);
  font-size: 0.42em;
  font-weight: 700;
  letter-spacing: 0.04em;
  margin-top: 6px;
}
.direction-note {
  margin: 8px 0 0;
  color: var(--muted-ink);
  font-size: 12px;
}
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
