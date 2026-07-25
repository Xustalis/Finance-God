<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch, computed } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { DeskBar } from '@/services/tradingDesk'

export type ChartPeriod = '1m' | '5m' | '15m' | '60m' | 'daily' | 'weekly' | 'monthly'

const MINUTE_PERIODS = new Set<ChartPeriod>(['1m', '5m', '15m', '60m'])
const MOVING_AVERAGE_PERIODS = [5, 10, 20, 60] as const

export interface ChartQuote {
  symbol: string
  name: string
  last: number | null
  open?: number | null
  high?: number | null
  low?: number | null
  previous_close?: number | null
  change: number | null
  change_percent: number | null
  volume?: number | null
  amount?: number | null
  provider_time: string
  frequency?: string
  freshness: string
  market_status?: string
  session_alignment?: string
}

const props = withDefaults(defineProps<{
  quote: ChartQuote | null
  bars: readonly DeskBar[]
  loading: boolean
  error: string | null
  minutePeriodsAvailable?: boolean
  onPeriodChange?: (period: ChartPeriod) => void
}>(), {
  minutePeriodsAvailable: true,
})

const activePeriod = ref<ChartPeriod>('daily')

const chartContainer = ref<HTMLDivElement | null>(null)
let chart: IChartApi | null = null
let candleSeries: ISeriesApi<'Candlestick'> | null = null
let volumeSeries: ISeriesApi<'Histogram'> | null = null
let ma5Series: ISeriesApi<'Line'> | null = null
let ma10Series: ISeriesApi<'Line'> | null = null
let ma20Series: ISeriesApi<'Line'> | null = null
let ma60Series: ISeriesApi<'Line'> | null = null

const changeColor = computed(() => {
  if (!props.quote?.change) return 'var(--ink)'
  return props.quote.change >= 0 ? 'var(--positive)' : 'var(--risk)'
})

const marketStateLabel = computed(() => {
  if (props.quote?.session_alignment === 'latest_released_session') {
    return '休市 · 最近交易日'
  }
  if (props.quote?.market_status === 'in_session') return '交易时段'
  if (props.quote?.market_status === 'released') return '已发布收盘'
  if (props.quote?.market_status === 'closed') return '休市'
  return props.quote?.market_status || '市场状态未知'
})

function formatProviderTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value || '时间未知'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function formatVolume(vol: number | null | undefined): string {
  if (vol == null) return '—'
  if (vol >= 1e8) return `${(vol / 1e8).toFixed(2)}亿`
  if (vol >= 1e4) return `${(vol / 1e4).toFixed(2)}万`
  return String(Math.round(vol))
}

function formatAmount(amt: number | null | undefined): string {
  if (amt == null) return '—'
  if (amt >= 1e8) return `${(amt / 1e8).toFixed(2)}亿`
  if (amt >= 1e4) return `${(amt / 1e4).toFixed(2)}万`
  return String(Math.round(amt))
}

function aggregateBars(bars: readonly DeskBar[], keyFor: (bar: DeskBar) => string): DeskBar[] {
  const result: DeskBar[] = []
  for (const bar of bars) {
    const key = keyFor(bar)
    const current = result.at(-1)
    if (!current || current.time !== key) {
      result.push({ ...bar, time: key })
      continue
    }
    current.high = Math.max(current.high, bar.high)
    current.low = Math.min(current.low, bar.low)
    current.close = bar.close
    current.volume += bar.volume
  }
  return result
}

function weekStart(bar: DeskBar): string {
  const date = new Date(bar.time)
  const day = date.getDay()
  date.setDate(date.getDate() - day + (day === 0 ? -6 : 1))
  return date.toISOString().slice(0, 10)
}

const sortedBars = computed<readonly DeskBar[]>(() =>
  [...props.bars].sort((a, b) => a.time.localeCompare(b.time)),
)

const displayBars = computed<readonly DeskBar[]>(() => {
  const bars = sortedBars.value
  if (activePeriod.value === 'daily') return aggregateBars(bars, bar => bar.time.slice(0, 10))
  if (activePeriod.value === 'weekly') return aggregateBars(bars, weekStart)
  if (activePeriod.value === 'monthly') return aggregateBars(bars, bar => `${bar.time.slice(0, 7)}-01`)
  if (activePeriod.value === '5m') return aggregateMinutes(bars, 5)
  if (activePeriod.value === '15m') return aggregateMinutes(bars, 15)
  if (activePeriod.value === '60m') return aggregateMinutes(bars, 60)
  return bars
})

function aggregateMinutes(bars: readonly DeskBar[], minutes: number): DeskBar[] {
  const result: DeskBar[] = []
  for (let index = 0; index < bars.length; index++) {
    const bar = bars[index]
    if (index % minutes === 0) {
      result.push({ ...bar })
      continue
    }
    const current = result[result.length - 1]
    current.high = Math.max(current.high, bar.high)
    current.low = Math.min(current.low, bar.low)
    current.close = bar.close
    current.volume += bar.volume
  }
  return result
}

function setPeriod(period: ChartPeriod) {
  if (MINUTE_PERIODS.has(period) && props.minutePeriodsAvailable === false) return
  activePeriod.value = period
  props.onPeriodChange?.(MINUTE_PERIODS.has(period) ? '1m' : 'daily')
}

function initChart() {
  if (!chartContainer.value) return
  chart = createChart(chartContainer.value, {
    layout: {
      background: { type: ColorType.Solid, color: 'transparent' },
      textColor: '#625541',
      fontFamily: '"Noto Serif SC", "Songti SC", Georgia, serif',
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: 'rgba(139, 115, 85, 0.08)' },
      horzLines: { color: 'rgba(139, 115, 85, 0.08)' },
    },
    crosshair: { mode: CrosshairMode.Normal },
    rightPriceScale: { borderColor: 'rgba(139, 115, 85, 0.2)' },
    timeScale: {
      borderColor: 'rgba(139, 115, 85, 0.2)',
      timeVisible: false,
    },
    width: chartContainer.value.clientWidth,
    height: 340,
  })

  candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: '#294f3e',
    downColor: '#8f3027',
    borderUpColor: '#294f3e',
    borderDownColor: '#8f3027',
    wickUpColor: '#294f3e',
    wickDownColor: '#8f3027',
  })

  volumeSeries = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  })
  chart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.85, bottom: 0 },
  })

  ma5Series = chart.addSeries(LineSeries, { color: '#211a12', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
  ma10Series = chart.addSeries(LineSeries, { color: '#625541', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
  ma20Series = chart.addSeries(LineSeries, { color: '#8f6d4b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
  ma60Series = chart.addSeries(LineSeries, { color: '#aa987a', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })

  updateData()
}

function updateData() {
  if (!candleSeries || !volumeSeries) return
  const barsToRender = displayBars.value
  if (!barsToRender.length) {
    candleSeries.setData([])
    volumeSeries.setData([])
    ma5Series?.setData([])
    ma10Series?.setData([])
    ma20Series?.setData([])
    ma60Series?.setData([])
    return
  }

  const isMinute = MINUTE_PERIODS.has(activePeriod.value)
  chart?.timeScale().applyOptions({ timeVisible: isMinute })

  const candles: CandlestickData[] = []
  const volumes: HistogramData[] = []
  const averages: Record<number, LineData[]> = Object.fromEntries(
    MOVING_AVERAGE_PERIODS.map(period => [period, []]),
  )
  const rollingSums: Record<number, number> = Object.fromEntries(
    MOVING_AVERAGE_PERIODS.map(period => [period, 0]),
  )

  for (let index = 0; index < barsToRender.length; index++) {
    const bar = barsToRender[index]
    const time: Time = isMinute
      ? Math.floor(new Date(bar.time).getTime() / 1000) as UTCTimestamp
      : bar.time.slice(0, 10)
    candles.push({ time, open: bar.open, high: bar.high, low: bar.low, close: bar.close })
    volumes.push({
      time,
      value: bar.volume,
      color: bar.close >= bar.open ? 'rgba(41, 79, 62, 0.38)' : 'rgba(143, 48, 39, 0.38)',
    })
    for (const period of MOVING_AVERAGE_PERIODS) {
      rollingSums[period] += bar.close
      if (index >= period) rollingSums[period] -= barsToRender[index - period].close
      if (index >= period - 1) {
        averages[period].push({ time, value: +(rollingSums[period] / period).toFixed(2) })
      }
    }
  }

  // lightweight-charts 对时间格式与重复时间敏感，异常不能打断周期切换与组件响应式。
  try {
    candleSeries.setData(candles)
    volumeSeries.setData(volumes)

    ma5Series?.setData(averages[5])
    ma10Series?.setData(averages[10])
    ma20Series?.setData(averages[20])
    ma60Series?.setData(averages[60])

    chart?.timeScale().fitContent()
  } catch (error) {
    // 回退：清空系列，避免渲染半态数据；错误信息由父级 error 通道呈现。
    console.warn('[MarketChart] 更新图表数据失败，已回退为空数据', error)
    try { candleSeries.setData([]); volumeSeries.setData([]) } catch { /* noop */ }
  }
}

function handleResize() {
  if (chart && chartContainer.value) {
    chart.applyOptions({ width: chartContainer.value.clientWidth })
  }
}

onMounted(() => {
  initChart()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (chart) { chart.remove(); chart = null }
})

watch(() => props.bars, () => {
  if (chart) updateData()
  else initChart()
})

watch(activePeriod, () => {
  if (chart) updateData()
})

watch(() => props.minutePeriodsAvailable, (available) => {
  if (available === false && MINUTE_PERIODS.has(activePeriod.value)) {
    activePeriod.value = 'daily'
  }
})
</script>

<template>
  <div class="market-chart">
    <!-- Header: symbol + price + change + mini stats -->
    <div v-if="quote" class="chart-header">
      <div class="chart-price-block">
        <h3 class="chart-symbol">{{ quote.symbol }} <span class="chart-name">{{ quote.name }}</span></h3>
        <div class="chart-price-row">
          <span class="chart-last" :style="{ color: changeColor }">{{ quote.last?.toFixed(2) ?? '—' }}</span>
          <span class="chart-change" :style="{ color: changeColor }">
            {{ quote.change != null ? `${quote.change >= 0 ? '+' : ''}${quote.change.toFixed(2)}` : '—' }}
          </span>
          <span class="chart-change-pct" :style="{ color: changeColor }">
            {{ quote.change_percent != null ? `${quote.change_percent >= 0 ? '+' : ''}${quote.change_percent.toFixed(2)}%` : '—' }}
          </span>
        </div>
        <small class="chart-provider">
          <strong>{{ marketStateLabel }}</strong>
          · PandaData
          · 上游 {{ formatProviderTime(quote.provider_time) }}
          · {{ quote.frequency || '频率未知' }}
          · {{ quote.freshness }}
        </small>
      </div>
      <div class="chart-mini-stats">
        <dl>
          <div><dt>今开</dt><dd>{{ quote.open?.toFixed(2) ?? '—' }}</dd></div>
          <div><dt>最高</dt><dd>{{ quote.high?.toFixed(2) ?? '—' }}</dd></div>
          <div><dt>昨收</dt><dd>{{ quote.previous_close?.toFixed(2) ?? '—' }}</dd></div>
          <div><dt>最低</dt><dd>{{ quote.low?.toFixed(2) ?? '—' }}</dd></div>
          <div><dt>成交量</dt><dd>{{ formatVolume(quote.volume) }}</dd></div>
          <div><dt>成交额</dt><dd>{{ formatAmount(quote.amount) }}</dd></div>
        </dl>
      </div>
    </div>

    <!-- Period tabs -->
    <div class="chart-period-bar" role="group" aria-label="K线周期">
      <button type="button" class="period-tab" :class="{ active: activePeriod === '1m' }" :aria-pressed="activePeriod === '1m'" :disabled="minutePeriodsAvailable === false" :title="minutePeriodsAvailable === false ? '当前指数仅支持日线、周线和月线' : undefined" @click="setPeriod('1m')">分时</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === '5m' }" :aria-pressed="activePeriod === '5m'" :disabled="minutePeriodsAvailable === false" :title="minutePeriodsAvailable === false ? '当前指数仅支持日线、周线和月线' : undefined" @click="setPeriod('5m')">5分</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === '15m' }" :aria-pressed="activePeriod === '15m'" :disabled="minutePeriodsAvailable === false" :title="minutePeriodsAvailable === false ? '当前指数仅支持日线、周线和月线' : undefined" @click="setPeriod('15m')">15分</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === '60m' }" :aria-pressed="activePeriod === '60m'" :disabled="minutePeriodsAvailable === false" :title="minutePeriodsAvailable === false ? '当前指数仅支持日线、周线和月线' : undefined" @click="setPeriod('60m')">1小时</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === 'daily' }" :aria-pressed="activePeriod === 'daily'" @click="setPeriod('daily')">日线</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === 'weekly' }" :aria-pressed="activePeriod === 'weekly'" @click="setPeriod('weekly')">周线</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === 'monthly' }" :aria-pressed="activePeriod === 'monthly'" @click="setPeriod('monthly')">月线</button>
      <span class="chart-ma-legend">
        <i class="ma5"></i>MA5
        <i class="ma10"></i>MA10
        <i class="ma20"></i>MA20
        <i class="ma60"></i>MA60
      </span>
    </div>

    <!-- Chart area -->
    <div ref="chartContainer" class="chart-canvas"></div>

    <p v-if="error" class="chart-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.market-chart { padding: 1rem 0; border-top: 3px double var(--ink); border-bottom: 1px solid var(--rule); background: transparent; }
.chart-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1.5rem; margin-bottom: .75rem; }
.chart-price-block { flex: 1; }
.chart-symbol { margin: 0; font-size: 1.1rem; font-weight: 600; color: var(--ink, #2c1810); }
.chart-name { font-weight: 400; font-size: .85rem; color: var(--muted-ink, #8b7355); margin-left: .5rem; }
.chart-price-row { display: flex; align-items: baseline; gap: .75rem; margin-top: .25rem; }
.chart-last { font-size: 1.8rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.chart-change, .chart-change-pct { font-size: .95rem; font-variant-numeric: tabular-nums; }
.chart-provider { display: block; margin-top: .25rem; color: var(--muted-ink, #8b7355); font-size: .72rem; }
.chart-mini-stats dl { display: grid; grid-template-columns: repeat(3, auto); gap: .15rem .75rem; margin: 0; font-size: .76rem; }
.chart-mini-stats dl > div { display: flex; gap: .4rem; }
.chart-mini-stats dt { color: var(--muted-ink, #8b7355); }
.chart-mini-stats dd { margin: 0; font-variant-numeric: tabular-nums; }
.chart-period-bar { display: flex; align-items: center; gap: .1rem; margin-bottom: .5rem; border-bottom: 1px solid var(--faint-rule, rgba(139,115,85,0.12)); padding-bottom: .4rem; }
.period-tab { padding: .3rem .6rem; font-size: .76rem; color: var(--muted-ink); cursor: pointer; border: 0; border-bottom: 2px solid transparent; background: transparent; border-radius: 0; user-select: none; transition: border-color .15s, color .15s; font-family: inherit; }
.period-tab:hover:not(.active) { border-bottom-color: var(--rule); color: var(--ink); }
.period-tab.active { border-bottom-color: var(--ink); color: var(--ink); font-weight: 700; cursor: default; }
.period-tab:focus-visible { outline: 2px solid var(--risk); outline-offset: 2px; }
.period-tab:disabled { color: var(--muted-ink); cursor: not-allowed; opacity: .45; }
.chart-ma-legend { margin-left: auto; font-size: .7rem; color: var(--muted-ink); display: flex; align-items: center; gap: .5rem; }
.chart-ma-legend i { display: inline-block; width: 12px; height: 2px; border-radius: 1px; margin-right: 2px; vertical-align: middle; }
.chart-ma-legend .ma5 { background: #211a12; }
.chart-ma-legend .ma10 { background: #625541; }
.chart-ma-legend .ma20 { background: #8f6d4b; }
.chart-ma-legend .ma60 { background: #aa987a; }
.chart-canvas { width: 100%; min-height: 340px; }
.chart-error { color: var(--risk, #c0392b); font-size: .82rem; margin-top: .5rem; }
.chart-loading { color: var(--muted-ink); font-size: .82rem; margin-top: .5rem; }

@media (max-width: 680px) {
  .chart-header { display: grid; gap: .75rem; }
  .chart-period-bar { align-items: flex-start; flex-wrap: wrap; }
  .chart-ma-legend { width: 100%; margin-left: 0; padding-top: .25rem; }
}
</style>
