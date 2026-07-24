<script setup lang="ts">
/**
 * MarketChart — SVG K 线图
 * 悬停预览 / 点击锁定 / 方向键浏览 / Esc 取消
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { MarketBar } from '@/types/desk'

const props = defineProps<{
  bars: MarketBar[]
  symbol?: string
  loading?: boolean
  error?: string | null
}>()

// ─── 布局常量 ─────────────────────────────────────
const PADDING = { top: 28, right: 60, bottom: 60, left: 12 }
const VOLUME_HEIGHT = 50
const CHART_GAP = 12

// ─── 交互状态 ─────────────────────────────────────
const svgRef = ref<SVGSVGElement | null>(null)
const hoverIndex = ref<number | null>(null)
const lockedIndex = ref<number | null>(null)
const svgSize = ref({ width: 800, height: 400 })

// ─── 尺寸计算 ─────────────────────────────────────
const chartWidth = computed(() => svgSize.value.width - PADDING.left - PADDING.right)
const chartHeight = computed(() => svgSize.value.height - PADDING.top - PADDING.bottom - VOLUME_HEIGHT - CHART_GAP)

// ─── 数据预处理 ───────────────────────────────────
const closes = computed(() => props.bars.map((b) => b.close))
const highs = computed(() => props.bars.map((b) => b.high))
const lows = computed(() => props.bars.map((b) => b.low))
const volumes = computed(() => props.bars.map((b) => b.volume))

const priceMin = computed(() => lows.value.length > 0 ? Math.min(...lows.value) : 0)
const priceMax = computed(() => highs.value.length > 0 ? Math.max(...highs.value) : 1)
const priceRange = computed(() => priceMax.value - priceMin.value || 1)
const volMax = computed(() => Math.max(...volumes.value) || 1)

const referencePrice = computed(() => {
  if (props.bars.length === 0) return 0
  return props.bars[props.bars.length - 1].close
})

// ─── 坐标映射 ─────────────────────────────────────
function xAt(i: number): number {
  const n = props.bars.length || 1
  return PADDING.left + (i / Math.max(n - 1, 1)) * chartWidth.value
}

function yAt(price: number): number {
  return PADDING.top + (1 - (price - priceMin.value) / priceRange.value) * chartHeight.value
}

function volY(v: number): number {
  const base = PADDING.top + chartHeight.value + CHART_GAP
  return base + VOLUME_HEIGHT - (v / volMax.value) * VOLUME_HEIGHT
}

const referenceY = computed(() => yAt(referencePrice.value))
const candleWidth = computed(() => Math.max(
  2,
  Math.min(8, chartWidth.value / Math.max(props.bars.length, 1) * .62),
))
const candles = computed(() => props.bars.map((bar, index) => {
  const x = xAt(index)
  const openY = yAt(bar.open)
  const closeY = yAt(bar.close)
  return {
    x,
    wickTop: yAt(bar.high),
    wickBottom: yAt(bar.low),
    bodyY: Math.min(openY, closeY),
    bodyHeight: Math.max(1.5, Math.abs(closeY - openY)),
    rising: bar.close >= bar.open,
  }
}))

const chartSummary = computed(() => {
  if (props.bars.length === 0) return '暂无可用 K 线数据。'
  const first = props.bars[0]
  const last = props.bars[props.bars.length - 1]
  const direction = last.close >= first.close ? '上涨' : '下跌'
  return `${props.symbol || '当前标的'} 共 ${props.bars.length} 根 K 线，区间由 ${first.close.toFixed(2)} ${direction}至 ${last.close.toFixed(2)}，区间最高 ${priceMax.value.toFixed(2)}，最低 ${priceMin.value.toFixed(2)}。`
})

// 网格线
const gridLines = computed(() => {
  const lines: { y: number; label: string }[] = []
  const steps = 5
  for (let i = 0; i <= steps; i++) {
    const price = priceMin.value + (priceRange.value * i) / steps
    lines.push({ y: yAt(price), label: price.toFixed(2) })
  }
  return lines
})

// 时间标签
const timeLabels = computed(() => {
  if (props.bars.length === 0) return []
  const n = props.bars.length
  const labels: { x: number; text: string }[] = []
  const step = Math.max(1, Math.floor(n / 6))
  for (let i = 0; i < n; i += step) {
    const t = props.bars[i].time
    const d = new Date(t)
    const text = `${d.getMonth() + 1}/${d.getDate()}`
    labels.push({ x: xAt(i), text })
  }
  return labels
})

// 成交量柱
const volumeBars = computed(() => {
  return props.bars.map((b, i) => ({
    x: xAt(i) - 2,
    y: volY(b.volume),
    width: Math.max(2, chartWidth.value / (props.bars.length || 1) - 1),
    height: PADDING.top + chartHeight.value + CHART_GAP + VOLUME_HEIGHT - volY(b.volume),
    rising: b.close >= b.open,
  }))
})

// ─── 交互指示器 ───────────────────────────────────
const activeIndex = computed(() => lockedIndex.value ?? hoverIndex.value)
const activeBar = computed(() => {
  if (activeIndex.value === null) return null
  return props.bars[activeIndex.value] ?? null
})
const activeX = computed(() => activeIndex.value !== null ? xAt(activeIndex.value) : 0)
const activeY = computed(() => activeIndex.value !== null ? yAt(closes.value[activeIndex.value]) : 0)

// ─── 鼠标交互 ─────────────────────────────────────
function nearestIndex(event: MouseEvent): number | null {
  if (!svgRef.value || props.bars.length === 0) return null
  const rect = svgRef.value.getBoundingClientRect()
  const mx = event.clientX - rect.left
  const n = props.bars.length
  let best = 0
  let bestDist = Infinity
  for (let i = 0; i < n; i++) {
    const d = Math.abs(xAt(i) - mx)
    if (d < bestDist) { bestDist = d; best = i }
  }
  return best
}

function onMouseMove(e: MouseEvent) {
  if (lockedIndex.value !== null) return
  hoverIndex.value = nearestIndex(e)
}

function onMouseLeave() {
  hoverIndex.value = null
}

function onClick(e: MouseEvent) {
  const idx = nearestIndex(e)
  if (idx === null) return
  if (lockedIndex.value === idx) {
    lockedIndex.value = null
  } else {
    lockedIndex.value = idx
  }
}

// ─── 键盘交互 ─────────────────────────────────────
function onKeyDown(e: KeyboardEvent) {
  if (props.bars.length === 0) return
  if (e.key === 'Escape') {
    lockedIndex.value = null
    hoverIndex.value = null
    return
  }
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault()
    const current = lockedIndex.value ?? hoverIndex.value ?? 0
    const delta = e.key === 'ArrowRight' ? 1 : -1
    const next = Math.max(0, Math.min(props.bars.length - 1, current + delta))
    lockedIndex.value = next
  }
}

// ─── 尺寸监听 ─────────────────────────────────────
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  if (svgRef.value) {
    resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        svgSize.value = {
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        }
      }
    })
    resizeObserver.observe(svgRef.value)
  }
  svgRef.value?.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  svgRef.value?.removeEventListener('keydown', onKeyDown)
})
</script>

<template>
  <div class="chart-frame">
    <!-- 加载中 -->
    <div v-if="loading && bars.length === 0" class="chart-placeholder">
      <span>加载 K 线数据...</span>
    </div>
    <!-- 错误 -->
    <div v-else-if="error && bars.length === 0" class="chart-placeholder chart-error">
      <strong>K 线加载失败</strong>
      <span>{{ error }}</span>
    </div>
    <!-- 空 -->
    <div v-else-if="bars.length === 0" class="chart-placeholder">
      <span>选择标的查看 K 线</span>
    </div>

    <svg
      v-show="bars.length > 0"
      ref="svgRef"
      class="market-chart"
      tabindex="0"
      role="img"
      :aria-label="`${symbol || ''} K 线图`"
      @mousemove="onMouseMove"
      @mouseleave="onMouseLeave"
      @click="onClick"
    >
      <desc>{{ chartSummary }}</desc>
      <!-- 网格线 -->
      <line
        v-for="(g, i) in gridLines"
        :key="'g' + i"
        class="grid-line"
        :x1="PADDING.left"
        :x2="PADDING.left + chartWidth"
        :y1="g.y"
        :y2="g.y"
      />
      <!-- 网格价格标签 -->
      <text
        v-for="(g, i) in gridLines"
        :key="'gl' + i"
        class="axis-label"
        :x="PADDING.left + chartWidth + 6"
        :y="g.y + 4"
      >{{ g.label }}</text>

      <!-- 时间轴标签 -->
      <text
        v-for="(t, i) in timeLabels"
        :key="'t' + i"
        class="month-label"
        :x="t.x"
        :y="PADDING.top + chartHeight + CHART_GAP + VOLUME_HEIGHT + 16"
        text-anchor="middle"
      >{{ t.text }}</text>

      <!-- 成交量柱 -->
      <g class="volume-bars">
        <rect
          v-for="(v, i) in volumeBars"
          :key="'v' + i"
          class="volume-bar"
          :class="v.rising ? 'rising' : 'falling'"
          :x="v.x"
          :y="v.y"
          :width="v.width"
          :height="Math.max(0, v.height)"
        />
      </g>

      <!-- 分隔线（价格/成交量） -->
      <line
        class="chart-divider"
        :x1="PADDING.left"
        :x2="PADDING.left + chartWidth"
        :y1="PADDING.top + chartHeight + CHART_GAP / 2"
        :y2="PADDING.top + chartHeight + CHART_GAP / 2"
      />

      <!-- K 线 -->
      <g class="candles">
        <g
          v-for="(candle, i) in candles"
          :key="'c' + i"
          :class="candle.rising ? 'candle rising' : 'candle falling'"
        >
          <line
            class="candle-wick"
            :x1="candle.x"
            :x2="candle.x"
            :y1="candle.wickTop"
            :y2="candle.wickBottom"
          />
          <rect
            class="candle-body"
            :x="candle.x - candleWidth / 2"
            :y="candle.bodyY"
            :width="candleWidth"
            :height="candle.bodyHeight"
          />
        </g>
      </g>

      <!-- 参考价参考线 -->
      <line
        v-if="referencePrice > 0"
        class="reference-line"
        :x1="PADDING.left"
        :x2="PADDING.left + chartWidth"
        :y1="referenceY"
        :y2="referenceY"
      />
      <!-- 参考价标签 -->
      <g v-if="referencePrice > 0">
        <rect
          class="price-tag"
          :x="PADDING.left + chartWidth + 1"
          :y="referenceY - 8"
          width="52" height="16" rx="0"
        />
        <text
          class="price-tag-text"
          :x="PADDING.left + chartWidth + 5"
          :y="referenceY + 4"
        >{{ referencePrice.toFixed(2) }}</text>
      </g>

      <!-- 交互指示器 -->
      <g v-if="activeBar" class="chart-interaction">
        <!-- 十字线 -->
        <line
          class="crosshair"
          :x1="activeX"
          :x2="activeX"
          :y1="PADDING.top"
          :y2="PADDING.top + chartHeight"
        />
        <line
          class="crosshair"
          :x1="PADDING.left"
          :x2="PADDING.left + chartWidth"
          :y1="activeY"
          :y2="activeY"
        />
        <!-- 活跃点 -->
        <circle class="active-dot" :cx="activeX" :cy="activeY" r="4" />
        <!-- 工具提示 -->
        <g>
          <rect
            class="chart-tooltip"
            :x="Math.min(activeX + 12, PADDING.left + chartWidth - 140)"
            :y="Math.max(activeY - 56, PADDING.top)"
            width="130" height="50" rx="0"
          />
          <text
            class="tooltip-date"
            :x="Math.min(activeX + 18, PADDING.left + chartWidth - 134)"
            :y="Math.max(activeY - 56, PADDING.top) + 14"
          >{{ new Date(activeBar.time).toLocaleDateString('zh-CN') }}</text>
          <text
            class="tooltip-value"
            :x="Math.min(activeX + 18, PADDING.left + chartWidth - 134)"
            :y="Math.max(activeY - 56, PADDING.top) + 30"
          >收 {{ activeBar.close.toFixed(2) }}</text>
          <text
            class="tooltip-text"
            :x="Math.min(activeX + 18, PADDING.left + chartWidth - 134)"
            :y="Math.max(activeY - 56, PADDING.top) + 44"
          >量 {{ (activeBar.volume / 10000).toFixed(0) }}万</text>
        </g>
      </g>

      <!-- 操作提示 -->
      <text
        v-if="!activeBar"
        class="interaction-hint"
        :x="PADDING.left + 8"
        :y="PADDING.top + 16"
      >悬停预览 · 点击锁定 · 方向键浏览 · Esc取消</text>
    </svg>
  </div>
</template>

<style scoped>
.chart-frame {
  position: relative;
  min-height: 380px;
  border-block: 1px solid var(--rule);
  contain: layout paint;
  transition: border-color 0.28s ease;
}
.chart-frame:hover {
  border-color: rgb(91 50 34 / 82%);
}

.chart-placeholder {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 6px;
  color: var(--muted-ink);
  font-size: 14px;
  text-align: center;
}
.chart-error strong {
  color: var(--risk);
  display: block;
}

.market-chart {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 380px;
  cursor: crosshair;
  overflow: visible;
}
.market-chart:focus-visible {
  outline: 2px solid var(--risk);
  outline-offset: 2px;
}

.grid-line {
  stroke: var(--faint-rule);
  stroke-dasharray: 2 4;
  stroke-width: 1;
}
.chart-divider {
  stroke: var(--rule);
  stroke-width: 1;
}

.candle-wick {
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.candle-body { vector-effect: non-scaling-stroke; }
.candle.rising .candle-wick { stroke: var(--risk); }
.candle.rising .candle-body {
  fill: var(--risk);
  stroke: var(--risk);
}
.candle.falling .candle-wick { stroke: var(--positive); }
.candle.falling .candle-body {
  fill: var(--positive);
  stroke: var(--positive);
}

.reference-line {
  stroke: var(--risk);
  stroke-dasharray: 3 3;
  stroke-width: 1;
  opacity: 0.72;
}

.price-tag { fill: var(--risk); }
.price-tag-text {
  fill: var(--paper-light);
  font-family: var(--font-numeric);
  font-size: 11px;
  font-weight: 700;
}

.axis-label,
.month-label {
  fill: var(--muted-ink);
  font-family: var(--font-numeric);
  font-size: 10px;
  font-weight: 600;
}

.volume-bar {
  opacity: 0.72;
}
.volume-bar.rising { fill: var(--risk); }
.volume-bar.falling { fill: var(--positive); }
.volume-bars {
  opacity: 0.78;
}

.crosshair {
  stroke: var(--ink);
  stroke-dasharray: 3 3;
  stroke-width: 1;
  opacity: 0.48;
  vector-effect: non-scaling-stroke;
}

.active-dot {
  fill: var(--paper-light);
  stroke: var(--risk);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}

.chart-tooltip {
  fill: rgb(241 231 211 / 96%);
  stroke: var(--ink);
  stroke-width: 1;
}
.tooltip-date,
.tooltip-text,
.tooltip-value {
  fill: var(--ink);
  font-family: var(--font-serif);
}
.tooltip-date { font-size: 10px; font-weight: 800; }
.tooltip-text,
.tooltip-value { font-size: 10px; }
.tooltip-value { font-family: var(--font-numeric); font-weight: 700; }

.interaction-hint {
  fill: var(--muted-ink);
  font-family: var(--font-serif);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.chart-interaction {
  pointer-events: none;
}
</style>
