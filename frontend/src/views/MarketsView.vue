<script setup lang="ts">
/**
 * MarketsView — 行情总览页
 * 左栏行情表 + 主栏图表 + 右栏摘要
 */
import { ref, onMounted, onUnmounted, watch } from 'vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import MarketTable from '@/components/desk/MarketTable.vue'
import MarketChart from '@/components/desk/MarketChart.vue'
import { useMarketStore } from '@/stores/market'
import { DEFAULT_SYMBOLS, directionOf, formatPercent, formatChange, formatNumber } from '@/types/desk'
import type { MarketQuote } from '@/types/desk'

const market = useMarketStore()
const activeSymbol = ref(DEFAULT_SYMBOLS[0])

// 选中的行情
const activeQuote = ref<MarketQuote | null>(null)

watch(() => market.quotesMap, (map) => {
  activeQuote.value = map.get(activeSymbol.value) ?? null
}, { immediate: true })

// 选中标的 → 加载 K 线
watch(activeSymbol, (sym) => {
  if (sym) market.loadBars(sym)
}, { immediate: true })

function onSelectSymbol(symbol: string) {
  activeSymbol.value = symbol
}

onMounted(() => {
  market.startPolling()
  market.checkHealth()
  if (activeSymbol.value) market.loadBars(activeSymbol.value)
})

onUnmounted(() => {
  market.stopPolling()
})
</script>

<template>
  <DeskLayout>
    <!-- 左栏：行情报价表 -->
    <template #left>
      <section class="rail-section">
        <h2 class="section-title">
          <span>市场概览</span>
          <small>MARKET OVERVIEW</small>
        </h2>
        <MarketTable
          :quotes="market.quotes"
          :loading="market.quotesLoading"
          :error="market.quotesError"
          :active-symbol="activeSymbol"
          @select="onSelectSymbol"
        />
      </section>
    </template>

    <!-- 主栏：标题 + 行情条 + 图表 -->
    <template #main>
      <!-- 版头 -->
      <div class="lead-header">
        <div class="lead-kicker">
          <span>行情中心</span>
          <span>MARKET CENTER</span>
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
          @click="onSelectSymbol(q.symbol)"
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
    </template>

    <!-- 右栏：摘要 -->
    <template #right>
      <section class="rail-section">
        <h2 class="section-title">
          <span>行情摘要</span>
          <small>QUOTE SUMMARY</small>
        </h2>
        <div v-if="activeQuote" class="summary-grid">
          <div class="summary-row">
            <span>最新价</span>
            <strong>{{ formatNumber(activeQuote.last) }}</strong>
          </div>
          <div class="summary-row">
            <span>涨跌</span>
            <strong :class="directionOf(activeQuote)">
              {{ formatChange(activeQuote.change) }}
            </strong>
          </div>
          <div class="summary-row">
            <span>涨跌幅</span>
            <strong :class="directionOf(activeQuote)">
              {{ formatPercent(activeQuote.change_percent) }}
            </strong>
          </div>
          <div class="summary-row">
            <span>开盘</span>
            <strong>{{ formatNumber(activeQuote.open) }}</strong>
          </div>
          <div class="summary-row">
            <span>最高</span>
            <strong>{{ formatNumber(activeQuote.high) }}</strong>
          </div>
          <div class="summary-row">
            <span>最低</span>
            <strong>{{ formatNumber(activeQuote.low) }}</strong>
          </div>
          <div class="summary-row">
            <span>昨收</span>
            <strong>{{ formatNumber(activeQuote.previous_close) }}</strong>
          </div>
          <div class="summary-row">
            <span>成交量</span>
            <strong>{{ formatNumber(activeQuote.volume, 0) }}</strong>
          </div>
        </div>
        <div v-else class="summary-empty">
          <span>选择标的查看详情</span>
        </div>

        <!-- K线数据状态 -->
        <div class="data-meta">
          <div class="summary-row" v-if="market.barsFrequency">
            <span>频率</span>
            <strong>{{ market.barsFrequency }}</strong>
          </div>
          <div class="summary-row">
            <span>K 线数</span>
            <strong>{{ market.bars.length }}</strong>
          </div>
          <div class="summary-row">
            <span>数据源</span>
            <strong>{{ market.provider }}</strong>
          </div>
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

/* 主栏 */
.lead-header {
  margin-bottom: 12px;
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
.lead-kicker span:first-child {
  color: var(--risk);
  font-size: 10px;
  font-weight: 900;
}
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

/* 右栏摘要 */
.summary-grid,
.data-meta {
  padding: 14px 18px;
}
.summary-grid + .data-meta {
  border-top: 1px solid var(--rule);
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 5px 0;
  font-size: 14px;
  border-bottom: 1px solid var(--faint-rule);
}
.summary-row:last-child { border-bottom: 0; }
.summary-row span {
  color: var(--muted-ink);
}
.summary-row strong {
  font-family: var(--font-numeric);
  font-weight: 700;
}

.summary-empty {
  padding: 28px 18px;
  color: var(--muted-ink);
  font-size: 13px;
  text-align: center;
}
</style>
