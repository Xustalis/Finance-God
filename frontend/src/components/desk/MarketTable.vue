<script setup lang="ts">
/**
 * MarketTable — 行情报价表
 * 细线分隔、右对齐数字列、涨跌着色
 */
import type { MarketQuote } from '@/types/desk'
import { directionOf, formatPercent, formatNumber } from '@/types/desk'

defineProps<{
  quotes: MarketQuote[]
  loading?: boolean
  error?: string | null
  activeSymbol?: string
}>()

const emit = defineEmits<{
  select: [symbol: string]
}>()
</script>

<template>
  <div class="market-table">
    <!-- 表头 -->
    <div class="table-header">
      <span class="col-name">标的</span>
      <span class="col-num">最新</span>
      <span class="col-num">涨跌幅</span>
    </div>

    <!-- 加载中 -->
    <div v-if="loading && quotes.length === 0" class="table-state">
      <span>加载行情数据...</span>
    </div>

    <!-- 错误 -->
    <div v-else-if="error && quotes.length === 0" class="table-state table-error">
      <strong>行情获取失败</strong>
      <span>{{ error }}</span>
    </div>

    <!-- 空 -->
    <div v-else-if="quotes.length === 0" class="table-state">
      <span>暂无行情数据</span>
    </div>

    <!-- 数据行 -->
    <button
      v-for="quote in quotes"
      v-else
      :key="quote.symbol"
      class="quote-row"
      :class="{ active: quote.symbol === activeSymbol }"
      @click="emit('select', quote.symbol)"
    >
      <strong class="col-name">
        <span>{{ quote.symbol }}</span>
        <small>{{ quote.name && quote.name !== quote.symbol ? quote.name : quote.asset_type }}</small>
      </strong>
      <span class="col-num">{{ formatNumber(quote.last) }}</span>
      <span class="col-num" :class="directionOf(quote)">
        {{ formatPercent(quote.change_percent) }}
      </span>
    </button>

    <!-- 刷新指示 -->
    <div v-if="loading && quotes.length > 0" class="refresh-bar">
      <span class="refresh-line" />
    </div>
  </div>
</template>

<style scoped>
.market-table {
  position: relative;
}

.table-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 60px 64px;
  gap: 4px;
  padding: 8px 18px 6px;
  font-size: 11px;
  font-weight: 900;
  color: var(--muted-ink);
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--rule);
}
.table-header .col-num { text-align: right; }

.quote-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 60px 64px;
  gap: 4px;
  width: 100%;
  min-height: 38px;
  padding: 5px 12px;
  border: 0;
  border-bottom: 1px solid var(--faint-rule);
  background: transparent;
  color: var(--ink);
  font-size: 14px;
  line-height: 1.25;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s;
}
.quote-row:hover {
  background: var(--faint-rule);
}
.quote-row.active {
  background: rgb(45 34 22 / 10%);
  border-left: 3px solid var(--risk);
  padding-left: 9px;
}
.quote-row .col-name {
  display: grid;
  font-family: var(--font-numeric), var(--font-serif);
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.quote-row .col-name small {
  overflow: hidden;
  color: var(--muted-ink);
  font-family: var(--font-serif);
  font-size: 9px;
  font-weight: 500;
  text-overflow: ellipsis;
}
.quote-row .col-num {
  text-align: right;
  font-family: var(--font-numeric);
  font-size: 13px;
}

.table-state {
  padding: 28px 18px;
  color: var(--muted-ink);
  font-size: 13px;
  text-align: center;
}
.table-error strong {
  display: block;
  color: var(--risk);
  margin-bottom: 4px;
}

.refresh-bar {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  overflow: hidden;
}
.refresh-line {
  display: block;
  height: 100%;
  background: var(--risk);
  opacity: 0.6;
  animation: refresh-sweep 1.2s ease-in-out;
}
@keyframes refresh-sweep {
  from { transform: scaleX(0); transform-origin: left; }
  50% { transform: scaleX(1); transform-origin: left; }
  51% { transform-origin: right; }
  to { transform: scaleX(0); transform-origin: right; }
}
</style>
