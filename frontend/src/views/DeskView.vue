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
import { useAiContextStore } from '@/stores/aiContext'
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
const ai = useAiContextStore()
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

const quoteTime = computed(() => {
  const value = activeQuote.value?.provider_time
  if (!value) return '等待上游时点'
  return new Date(value).toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
})

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

/**
 * 入口上下文：从自选/候选/搜索进入时携带 symbol/source（可选 reason/group）。
 * 在方向解析完成后调用，以便选中具体标的并落到常驻 AI 上下文。
 */
function sourceLabel(source: string): string {
  if (source === 'candidate') return '系统候选'
  if (source === 'watchlist') return '我的自选'
  if (source === 'search') return '搜索'
  return source
}

function applyEntryContext() {
  const symbol = typeof route.query.symbol === 'string' ? route.query.symbol : null
  const source = typeof route.query.source === 'string' ? route.query.source : null
  if (!symbol) return
  if (!watchSymbols.value.includes(symbol)) {
    watchSymbols.value = [symbol, ...watchSymbols.value]
    market.setWatchSymbols(watchSymbols.value)
  }
  activeSymbol.value = symbol
  market.startPolling(watchSymbols.value)
  market.loadBars(symbol)
  ai.setContext({
    scope: 'symbol',
    subject: symbol,
    label: source ? `${symbol}（来自${sourceLabel(source)}）` : symbol,
  })
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

onMounted(async () => {
  market.checkHealth()
  await resolveDirection()
  applyEntryContext()
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
        <div class="lead-identity">
          <div class="lead-kicker">
            <span>当前标的</span>
            <span>{{ directionKind || 'TRADING DESK' }}</span>
          </div>
          <h1 class="lead-title">
            <span class="lead-symbol">{{ activeQuote ? activeQuote.symbol : '选择标的' }}</span>
            <span
              v-if="activeQuote?.name && activeQuote.name !== activeQuote.symbol"
              class="lead-name"
            >
              {{ activeQuote.name }}
            </span>
            <small v-if="activeQuote" class="instrument-tags">
              <span>{{ activeQuote.market }}</span>
              <span>{{ activeQuote.asset_type }}</span>
              <span>仿真交易</span>
            </small>
          </h1>
          <small v-if="directionTitle" class="direction-badge" data-test="desk-direction">
            当前方向：{{ directionTitle }} · {{ directionKind }}
          </small>
        </div>
        <div v-if="activeQuote" class="quote-lead" :class="directionOf(activeQuote)">
          <strong>{{ formatNumber(activeQuote.last) }}</strong>
          <span>{{ formatChange(activeQuote.change) }}　{{ formatPercent(activeQuote.change_percent) }}</span>
        </div>
        <dl v-if="activeQuote" class="quote-facts">
          <div><dt>今开</dt><dd>{{ formatNumber(activeQuote.open) }}</dd></div>
          <div><dt>最高</dt><dd>{{ formatNumber(activeQuote.high) }}</dd></div>
          <div><dt>昨收</dt><dd>{{ formatNumber(activeQuote.previous_close) }}</dd></div>
          <div><dt>最低</dt><dd>{{ formatNumber(activeQuote.low) }}</dd></div>
          <div><dt>成交量</dt><dd>{{ formatNumber(activeQuote.volume, 0) }}</dd></div>
          <div><dt>成交额</dt><dd>{{ formatNumber(activeQuote.amount, 0) }}</dd></div>
        </dl>
        <div class="data-byline">
          <span>PandaData</span>
          <span>{{ quoteTime }}</span>
          <span>{{ activeQuote?.frequency || '频率未知' }}</span>
          <strong :class="activeQuote?.freshness === 'current' ? 'up' : 'down'">
            {{ activeQuote?.freshness || '等待行情' }}
          </strong>
        </div>
        <p v-if="directionError" class="direction-note" role="status">
          画像方向读取失败，已使用默认标的池。{{ directionError }}
        </p>
      </div>

      <div class="chart-toolbar">
        <div class="chart-mode" aria-label="当前图表周期">
          <strong>{{ market.barsFrequency || 'K 线' }}</strong>
          <span>{{ market.bars.length }} 根</span>
        </div>
        <div class="chart-indicators" aria-label="图表指标">
          <span>价格</span>
          <span>成交量</span>
        </div>
      </div>

      <div class="ticker-strip" v-if="market.quotes.length > 0" aria-label="观察标的快捷切换">
        <button
          v-for="q in market.quotes.slice(0, 6)"
          :key="q.symbol"
          type="button"
          class="ticker"
          :class="{ active: q.symbol === activeSymbol }"
          @click="activeSymbol = q.symbol"
        >
          <span>{{ q.symbol }}</span>
          <strong :class="directionOf(q)">{{ formatPercent(q.change_percent) }}</strong>
        </button>
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
        <div class="detail-item">
          <span>实际频率</span>
          <strong>{{ activeQuote.frequency }}</strong>
        </div>
        <div class="detail-item">
          <span>市场状态</span>
          <strong>{{ activeQuote.market_status }}</strong>
        </div>
        <div class="detail-item">
          <span>数据源</span>
          <strong>{{ activeQuote.provider }}</strong>
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

.lead-header {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) auto minmax(220px, .72fr);
  gap: 8px 22px;
  align-items: end;
  margin-bottom: 6px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--rule);
}
.lead-identity { min-width: 0; }
.direction-badge {
  display: block;
  margin-top: 4px;
  color: var(--muted-ink);
  font-size: 11px;
  font-weight: 600;
}
.direction-note {
  grid-column: 1 / -1;
  margin: 8px 0 0;
  color: var(--muted-ink);
  font-size: 12px;
}
.lead-kicker {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  color: var(--muted-ink);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.13em;
}
.lead-kicker span:first-child { color: var(--risk); font-size: 10px; font-weight: 900; }
.lead-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 5px 12px;
  margin: 0;
  font-size: clamp(1.55rem, 2.4vw, 2.4rem);
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.015em;
}
.lead-symbol { font-family: var(--font-numeric); }
.lead-name { font-size: .72em; letter-spacing: .03em; }
.instrument-tags {
  display: inline-flex;
  gap: 4px;
  font-size: 10px;
  font-weight: 700;
}
.instrument-tags span {
  padding: 1px 5px;
  border: 1px solid var(--rule);
}
.quote-lead {
  display: grid;
  align-content: end;
  min-width: 110px;
  font-family: var(--font-numeric);
}
.quote-lead strong {
  font-size: clamp(2rem, 3.4vw, 3rem);
  line-height: .9;
}
.quote-lead span {
  margin-top: 6px;
  font-size: 16px;
  font-weight: 700;
}
.quote-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(96px, 1fr));
  gap: 2px 18px;
  margin: 0;
  font-size: 11px;
}
.quote-facts div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.quote-facts dt { color: var(--muted-ink); }
.quote-facts dd {
  margin: 0;
  font-family: var(--font-numeric);
  font-weight: 700;
  text-align: right;
}
.data-byline {
  grid-column: 1 / -1;
  display: flex;
  gap: 8px;
  align-items: baseline;
  color: var(--muted-ink);
  font-size: 10px;
}
.data-byline span + span::before,
.data-byline strong::before {
  content: "·";
  margin-right: 8px;
  color: var(--rule);
}

.chart-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 34px;
  border-bottom: 1px solid var(--rule);
  font-size: 12px;
}
.chart-mode,
.chart-indicators { display: flex; align-items: center; gap: 2px; }
.chart-mode span,
.chart-mode strong,
.chart-indicators span {
  padding: 6px 9px 5px;
  white-space: nowrap;
}
.chart-mode strong {
  border: 1px solid var(--rule);
  background: var(--paper-light);
}

.ticker-strip {
  display: flex;
  align-items: center;
  gap: 0;
  margin: 0;
  min-height: 30px;
  overflow-x: auto;
  scrollbar-width: none;
  white-space: nowrap;
}
.ticker-strip::-webkit-scrollbar { display: none; }
.ticker {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 5px 12px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--ink);
  font-family: var(--font-numeric);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: border-color 0.18s;
}
.ticker:hover { border-bottom-color: var(--faint-rule); }
.ticker.active { border-bottom-color: var(--risk); }
.ticker strong { font-size: 11px; }

.detail-grid {
  display: grid;
  grid-template-columns: repeat(9, minmax(0, 1fr));
  gap: 0;
  margin-top: 6px;
  border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
}
.detail-item {
  min-width: 0;
  padding: 7px 8px;
  display: grid;
  gap: 2px;
  border-right: 1px solid var(--faint-rule);
}
.detail-item:last-child { border-right: 0; }
.detail-item span { color: var(--muted-ink); font-size: 11px; }
.detail-item strong {
  overflow: hidden;
  font-family: var(--font-numeric);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

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

@media (max-width: 1279px) {
  .lead-header {
    grid-template-columns: minmax(220px, 1fr) auto;
  }
  .quote-facts { display: none; }
  .detail-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); }
  .detail-item:nth-child(n + 7) { display: none; }
}
</style>
