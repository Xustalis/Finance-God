<script setup lang="ts">
/**
 * BottomRail — 底栏：后端行情统计、数据状态、观察标的
 * 浏览器仅绘制后端 DTO 和原始 K 线，不计算交易指标。
 */
import { useMarketStore } from '@/stores/market'
import { directionOf, formatPercent, formatNumber } from '@/types/desk'
import { computed } from 'vue'

const market = useMarketStore()

/** 取前 4 只作为观察标的 */
const leaders = computed(() => market.quotes.slice(0, 4))

const signal = computed(() => market.overview?.data.signal ?? null)
const indicators = computed(
  () => new Map(market.overview?.data.indicators.map(item => [item.code, item]) ?? []),
)

function metricText(code: 'change_dispersion' | 'advance_ratio'): string {
  const indicator = indicators.value.get(code)
  if (!indicator || indicator.value === null) return '—'
  return indicator.unit === 'percentage_points'
    ? `${indicator.value.toFixed(2)} 个百分点`
    : `${indicator.value.toFixed(2)}%`
}

/** 从 K 线生成 sparkline polyline 点 */
function sparklinePoints(values: number[], w = 100, h = 40): string {
  if (values.length < 2) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const step = w / (values.length - 1)
  return values.map((v, i) => {
    const x = i * step
    const y = h - ((v - min) / range) * (h - 4) - 2
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

/** K 线收盘价 sparkline */
const trendSpark = computed(() => sparklinePoints(market.bars.map(b => b.close)))
/** K 线振幅 sparkline */
const volSpark = computed(() => sparklinePoints(market.bars.map(b => b.high - b.low)))
/** K 线成交量 sparkline */
const breadthSpark = computed(() => sparklinePoints(market.bars.map(b => b.volume)))
</script>

<template>
  <section class="bottom-rail" aria-label="市场状态与事件">
    <div class="metric-panel">
      <span class="metric-kicker">趋势</span>
      <strong :class="{ up: signal?.tendency === 'positive', down: signal?.tendency === 'cautious' }">
        {{ signal?.tendency_label ?? '—' }}
      </strong>
      <svg v-if="trendSpark" class="spark-line" viewBox="0 0 100 40" preserveAspectRatio="none">
        <polyline :points="trendSpark" fill="none" stroke="var(--ink)" stroke-width="1.5" vector-effect="non-scaling-stroke" />
      </svg>
    </div>
    <div class="metric-panel">
      <span class="metric-kicker">涨跌幅离散度</span>
      <strong>{{ metricText('change_dispersion') }}</strong>
      <svg v-if="volSpark" class="spark-line" viewBox="0 0 100 40" preserveAspectRatio="none">
        <polyline :points="volSpark" fill="none" stroke="var(--ink)" stroke-width="1.5" vector-effect="non-scaling-stroke" />
      </svg>
    </div>
    <div class="metric-panel">
      <span class="metric-kicker">上涨覆盖率</span>
      <strong>{{ metricText('advance_ratio') }}</strong>
      <svg v-if="breadthSpark" class="spark-line" viewBox="0 0 100 40" preserveAspectRatio="none">
        <polyline :points="breadthSpark" fill="none" stroke="var(--ink)" stroke-width="1.5" vector-effect="non-scaling-stroke" />
      </svg>
    </div>
    <div class="event-panel">
      <span class="metric-kicker">数据状态</span>
      <div class="event-row" v-if="market.health">
        <strong>{{ market.health.market_data }}</strong>
        <span>{{ market.health.readiness === 'ready' ? '已连接' : market.health.readiness_reason }}</span>
      </div>
      <div class="event-row" v-else-if="market.healthError">
        <strong class="down">连接失败</strong>
        <span>{{ market.healthError }}</span>
      </div>
      <div class="event-row" v-else>
        <span>检测中...</span>
      </div>
    </div>
    <div class="leader-panel">
      <div v-for="q in leaders" :key="q.symbol">
        <strong>{{ q.symbol }}</strong>
        <span>{{ formatNumber(q.last) }}</span>
        <span :class="directionOf(q)">{{ formatPercent(q.change_percent) }}</span>
      </div>
      <div v-if="leaders.length === 0" class="leader-empty">
        <span>暂无数据</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.bottom-rail {
  grid-area: bottom;
  display: grid;
  grid-template-columns: 1fr 1.1fr 1.6fr 1.8fr 1.8fr;
  border-top: 4px double var(--rule);
  overflow: hidden;
}

.metric-panel {
  display: grid;
  align-content: start;
  grid-template-rows: auto 27px minmax(0, 1fr);
  min-width: 0;
  padding: 12px 18px;
  border-right: 1px solid var(--rule);
}
.metric-panel > strong {
  font-size: 14px;
}

.metric-kicker {
  display: block;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.06em;
}

.spark-line {
  display: block;
  width: 100%;
  height: 64px;
  margin-top: 3px;
  overflow: visible;
}

.event-panel {
  display: grid;
  align-content: start;
  gap: 11px;
  min-width: 0;
  padding: 12px 18px;
  border-right: 1px solid var(--rule);
}
.event-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  font-size: 13px;
}

.leader-panel {
  display: grid;
  align-content: center;
  gap: 1px;
  padding-block: 9px;
  min-width: 0;
}
.leader-panel > div {
  display: grid;
  grid-template-columns: 80px 1fr 70px;
  gap: 8px;
  font-family: var(--font-numeric), var(--font-serif);
  font-size: 13px;
  line-height: 1.12;
  padding: 0 18px;
}
.leader-panel > div span:nth-child(2),
.leader-panel > div span:nth-child(3) {
  text-align: right;
}
.leader-empty {
  padding: 0 18px;
  color: var(--muted-ink);
  font-size: 12px;
}
</style>
