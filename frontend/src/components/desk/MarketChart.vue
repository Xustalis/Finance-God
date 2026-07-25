<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch, computed } from 'vue'
import { createChart, type IChartApi, ColorType, CrosshairMode, CandlestickSeries, HistogramSeries, LineSeries } from 'lightweight-charts'
import type { DeskBar } from '@/services/tradingDesk'

export type ChartPeriod = '1m' | '5m' | '15m' | '60m' | 'daily' | 'weekly' | 'monthly'

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
  freshness: string
}

const props = defineProps<{
  quote: ChartQuote | null
  bars: readonly DeskBar[]
  loading: boolean
  error: string | null
  onPeriodChange?: (period: ChartPeriod) => void
}>()

const activePeriod = ref<ChartPeriod>('daily')

const chartContainer = ref<HTMLDivElement | null>(null)
let chart: IChartApi | null = null
let candleSeries: any = null
let volumeSeries: any = null
let ma5Series: any = null
let ma10Series: any = null
let ma20Series: any = null
let ma60Series: any = null

const changeColor = computed(() => {
  if (!props.quote?.change) return 'var(--ink)'
  return props.quote.change >= 0 ? 'var(--positive)' : 'var(--risk)'
})

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

function calcMA(data: readonly DeskBar[], period: number): Array<{ time: string; value: number }> {
  const result: Array<{ time: string; value: number }> = []
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0
    for (let j = 0; j < period; j++) sum += data[i - j].close
    result.push({ time: data[i].time, value: +(sum / period).toFixed(2) })
  }
  return result
}

/** Aggregate daily bars into weekly candles (Mon-Fri grouped by ISO week). */
function aggregateWeekly(daily: readonly DeskBar[]): DeskBar[] {
  const sorted = [...daily].sort((a, b) => a.time.localeCompare(b.time))
  const weeks: Map<string, DeskBar[]> = new Map()
  for (const bar of sorted) {
    const d = new Date(bar.time)
    const day = d.getDay()
    const diff = d.getDate() - day + (day === 0 ? -6 : 1)
    const monday = new Date(d)
    monday.setDate(diff)
    const key = monday.toISOString().slice(0, 10)
    if (!weeks.has(key)) weeks.set(key, [])
    weeks.get(key)!.push(bar)
  }
  const result: DeskBar[] = []
  for (const [weekStart, bars] of weeks) {
    if (!bars.length) continue
    result.push({
      time: weekStart,
      open: bars[0].open,
      high: Math.max(...bars.map(b => b.high)),
      low: Math.min(...bars.map(b => b.low)),
      close: bars[bars.length - 1].close,
      volume: bars.reduce((s, b) => s + b.volume, 0),
    })
  }
  return result
}

/** Aggregate daily bars into monthly candles. */
function aggregateMonthly(daily: readonly DeskBar[]): DeskBar[] {
  const sorted = [...daily].sort((a, b) => a.time.localeCompare(b.time))
  const months: Map<string, DeskBar[]> = new Map()
  for (const bar of sorted) {
    const key = bar.time.slice(0, 7) + '-01'
    if (!months.has(key)) months.set(key, [])
    months.get(key)!.push(bar)
  }
  const result: DeskBar[] = []
  for (const [monthStart, bars] of months) {
    if (!bars.length) continue
    result.push({
      time: monthStart,
      open: bars[0].open,
      high: Math.max(...bars.map(b => b.high)),
      low: Math.min(...bars.map(b => b.low)),
      close: bars[bars.length - 1].close,
      volume: bars.reduce((s, b) => s + b.volume, 0),
    })
  }
  return result
}

/** Get display bars based on the active period. */
const displayBars = computed<readonly DeskBar[]>(() => {
  if (activePeriod.value === 'weekly') return aggregateWeekly(props.bars)
  if (activePeriod.value === 'monthly') return aggregateMonthly(props.bars)
  if (activePeriod.value === '5m') return aggregateMinutes(props.bars, 5)
  if (activePeriod.value === '15m') return aggregateMinutes(props.bars, 15)
  if (activePeriod.value === '60m') return aggregateMinutes(props.bars, 60)
  return props.bars
})

/** Aggregate 1-minute bars into N-minute candles. */
function aggregateMinutes(bars: readonly DeskBar[], minutes: number): DeskBar[] {
  if (!bars.length) return []
  const sorted = [...bars].sort((a, b) => a.time.localeCompare(b.time))
  const result: DeskBar[] = []
  for (let i = 0; i < sorted.length; i += minutes) {
    const chunk = sorted.slice(i, i + minutes)
    if (!chunk.length) break
    result.push({
      time: chunk[0].time,
      open: chunk[0].open,
      high: Math.max(...chunk.map(b => b.high)),
      low: Math.min(...chunk.map(b => b.low)),
      close: chunk[chunk.length - 1].close,
      volume: chunk.reduce((s, b) => s + b.volume, 0),
    })
  }
  return result
}

function setPeriod(period: ChartPeriod) {
  activePeriod.value = period
  // Notify parent for server-side frequency switch
  if (period === '1m' || period === '5m' || period === '15m' || period === '60m') {
    props.onPeriodChange?.('1m')
  } else {
    props.onPeriodChange?.('daily')
  }
}

function initChart() {
  if (!chartContainer.value) return
  chart = createChart(chartContainer.value, {
    layout: {
      background: { type: ColorType.Solid, color: 'transparent' },
      textColor: '#5c4a3a',
      fontFamily: 'system-ui, -apple-system, sans-serif',
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
    upColor: '#c0392b',
    downColor: '#27ae60',
    borderUpColor: '#c0392b',
    borderDownColor: '#27ae60',
    wickUpColor: '#c0392b',
    wickDownColor: '#27ae60',
  })

  volumeSeries = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  })
  chart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.85, bottom: 0 },
  })

  ma5Series = chart.addSeries(LineSeries, { color: '#e67e22', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
  ma10Series = chart.addSeries(LineSeries, { color: '#3498db', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
  ma20Series = chart.addSeries(LineSeries, { color: '#9b59b6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
  ma60Series = chart.addSeries(LineSeries, { color: '#1abc9c', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })

  updateData()
}

function toDay(time: string): string {
  // For daily/weekly/monthly: 'YYYY-MM-DD'
  // For minute bars: keep time portion for lightweight-charts BusinessDay or UTC timestamp
  return time.slice(0, 10)
}

function updateData() {
  if (!candleSeries || !volumeSeries) return
  const barsToRender = displayBars.value
  if (!barsToRender.length) return

  const isMinute = activePeriod.value === '1m' || activePeriod.value === '5m' || activePeriod.value === '15m' || activePeriod.value === '60m'

  // Update time scale visibility
  chart?.timeScale().applyOptions({ timeVisible: isMinute })

  // lightweight-charts requires ascending order
  const sorted = [...barsToRender].sort((a, b) => a.time.localeCompare(b.time))

  const candles = sorted.map(b => {
    if (isMinute) {
      // Use UTC timestamp for minute data
      const ts = Math.floor(new Date(b.time).getTime() / 1000)
      return { time: ts as any, open: b.open, high: b.high, low: b.low, close: b.close }
    }
    return { time: toDay(b.time), open: b.open, high: b.high, low: b.low, close: b.close }
  })

  const volumes = sorted.map(b => {
    const timeVal = isMinute ? Math.floor(new Date(b.time).getTime() / 1000) as any : toDay(b.time)
    return {
      time: timeVal,
      value: b.volume,
      color: b.close >= b.open ? 'rgba(192, 57, 43, 0.4)' : 'rgba(39, 174, 96, 0.4)',
    }
  })

  // lightweight-charts 对时间格式与重复时间敏感，异常不能打断周期切换与组件响应式。
  try {
    candleSeries.setData(candles as any)
    volumeSeries.setData(volumes as any)

    if (ma5Series) ma5Series.setData(calcMA(barsToRender, 5).map(d => isMinute ? { ...d, time: Math.floor(new Date(d.time).getTime() / 1000) } : d) as any)
    if (ma10Series) ma10Series.setData(calcMA(barsToRender, 10).map(d => isMinute ? { ...d, time: Math.floor(new Date(d.time).getTime() / 1000) } : d) as any)
    if (ma20Series) ma20Series.setData(calcMA(barsToRender, 20).map(d => isMinute ? { ...d, time: Math.floor(new Date(d.time).getTime() / 1000) } : d) as any)
    if (ma60Series) ma60Series.setData(calcMA(barsToRender, 60).map(d => isMinute ? { ...d, time: Math.floor(new Date(d.time).getTime() / 1000) } : d) as any)

    chart?.timeScale().fitContent()
  } catch (error) {
    // 回退：清空系列，避免渲染半态数据；错误信息由父级 error 通道呈现。
    console.warn('[MarketChart] 更新图表数据失败，已回退为空数据', error)
    try { candleSeries.setData([] as any); volumeSeries.setData([] as any) } catch { /* noop */ }
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
        <small class="chart-provider">PandaData · {{ quote.provider_time }} · {{ quote.freshness }}</small>
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
      <button type="button" class="period-tab" :class="{ active: activePeriod === '1m' }" :aria-pressed="activePeriod === '1m'" @click="setPeriod('1m')">分时</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === '5m' }" :aria-pressed="activePeriod === '5m'" @click="setPeriod('5m')">5分</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === '15m' }" :aria-pressed="activePeriod === '15m'" @click="setPeriod('15m')">15分</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === '60m' }" :aria-pressed="activePeriod === '60m'" @click="setPeriod('60m')">1小时</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === 'daily' }" :aria-pressed="activePeriod === 'daily'" @click="setPeriod('daily')">日线</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === 'weekly' }" :aria-pressed="activePeriod === 'weekly'" @click="setPeriod('weekly')">周线</button>
      <button type="button" class="period-tab" :class="{ active: activePeriod === 'monthly' }" :aria-pressed="activePeriod === 'monthly'" @click="setPeriod('monthly')">月线</button>
      <span class="chart-ma-legend">
        <i style="background:#e67e22"></i>MA5
        <i style="background:#3498db"></i>MA10
        <i style="background:#9b59b6"></i>MA20
        <i style="background:#1abc9c"></i>MA60
      </span>
    </div>

    <!-- Chart area -->
    <div ref="chartContainer" class="chart-canvas"></div>

    <p v-if="error" class="chart-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.market-chart { border: 1px solid var(--faint-rule, rgba(139,115,85,0.12)); border-radius: 4px; padding: 1rem; background: var(--paper, #faf8f5); }
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
.period-tab { padding: .25rem .6rem; font-size: .76rem; color: var(--muted-ink, #8b7355); cursor: pointer; border: 0; background: transparent; border-radius: 3px; user-select: none; transition: background .15s, color .15s; font-family: inherit; }
.period-tab:hover:not(.active) { background: rgba(139,115,85,0.08); color: var(--ink, #2c1810); }
.period-tab.active { background: var(--ink, #2c1810); color: var(--paper, #faf8f5); font-weight: 500; cursor: default; }
.period-tab:focus-visible { outline: 2px solid var(--ink, #2c1810); outline-offset: 2px; }
.chart-ma-legend { margin-left: auto; font-size: .7rem; color: var(--muted-ink); display: flex; align-items: center; gap: .5rem; }
.chart-ma-legend i { display: inline-block; width: 12px; height: 2px; border-radius: 1px; margin-right: 2px; vertical-align: middle; }
.chart-canvas { width: 100%; min-height: 340px; }
.chart-error { color: var(--risk, #c0392b); font-size: .82rem; margin-top: .5rem; }
.chart-loading { color: var(--muted-ink); font-size: .82rem; margin-top: .5rem; }
</style>
