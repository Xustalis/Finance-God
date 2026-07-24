<script setup lang="ts">
/**
 * OverviewView — 总览 · 市场头版
 * 复制 localhost:3001 的报纸式双栏布局：
 *   左栏 = 头条 + 指数条 + K线 + 成交量
 *   右栏 = 市场信号（行情派生）+ 关键驱动 + 技术指标
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Masthead from '@/components/desk/Masthead.vue'
import MarketChart from '@/components/desk/MarketChart.vue'
import { useMarketStore } from '@/stores/market'
import {
  DEFAULT_SYMBOLS,
  directionOf,
  formatPercent,
  formatNumber,
} from '@/types/desk'
import type { MarketQuote } from '@/types/desk'

const market = useMarketStore()
const activeTab = ref('市场')
// 仅保留有真实行情数据的栏目：PandaData 当前仅提供 A 股实时快照。
const TABS = ['市场', '股票', '观察列表']

/* ── 行情数据 ─────────────────────────────────── */
const leadSymbol = ref(DEFAULT_SYMBOLS[0])
const leadQuote = computed<MarketQuote | null>(
  () => market.quotesMap.get(leadSymbol.value) ?? null,
)

/* 市场信号（从真实行情派生，非模型输出） */
const signal = computed(() => market.marketSignal)

/** 关键驱动：从真实行情数据提取前 4 个信号 */
const marketForces = computed(() => {
  const qs = market.quotes
  if (qs.length === 0) return []
  const sorted = [...qs].sort((a, b) => (b.change_percent ?? 0) - (a.change_percent ?? 0))
  const top = sorted[0]
  const bottom = sorted[sorted.length - 1]
  const avgChg = qs.reduce((s, q) => s + (q.change_percent ?? 0), 0) / qs.length
  const volLeader = [...qs].sort((a, b) => b.volume - a.volume)[0]

  const forces: { label: string; icon: string }[] = []
  if (top && (top.change_percent ?? 0) > 0)
    forces.push({ label: `${top.symbol} 领涨 ${formatPercent(top.change_percent)}`, icon: '↑' })
  if (bottom && (bottom.change_percent ?? 0) < 0)
    forces.push({ label: `${bottom.symbol} 领跌 ${formatPercent(bottom.change_percent)}`, icon: '↓' })
  forces.push({
    label: avgChg >= 0 ? `市场均涨幅 ${formatPercent(avgChg)}` : `市场均跌幅 ${formatPercent(avgChg)}`,
    icon: avgChg >= 0 ? '↗' : '↘',
  })
  if (volLeader)
    forces.push({ label: `${volLeader.symbol} 成交活跃`, icon: '▪' })
  return forces
})

/** 技术指标：从 K 线数据派生的指标评分（行情统计，非模型输出） */
const technicalIndicators = computed(() => {
  const bars = market.bars
  const qs = market.quotes
  if (bars.length < 2 && qs.length === 0)
    return [
      { name: '价格趋势', score: 0 }, { name: '波动强度', score: 0 },
      { name: '成交量趋势', score: 0 }, { name: '数据新鲜度', score: 0 },
    ]

  let trendScore = 50
  if (bars.length >= 5) {
    const recent = bars.slice(-5)
    const ups = recent.filter((b, i) => i > 0 && b.close > recent[i - 1].close).length
    trendScore = Math.round((ups / (recent.length - 1)) * 100)
  }

  let volScore = 50
  if (bars.length >= 3) {
    const ranges = bars.slice(-20).map(b => b.high - b.low)
    const avg = ranges.reduce((a, b) => a + b, 0) / ranges.length
    const stdDev = Math.sqrt(ranges.reduce((a, b) => a + (b - avg) ** 2, 0) / ranges.length)
    volScore = avg > 0 ? Math.min(100, Math.round((stdDev / avg) * 200)) : 50
  }

  let volumeScore = 50
  if (bars.length >= 10) {
    const recent = bars.slice(-5).reduce((s, b) => s + b.volume, 0) / 5
    const earlier = bars.slice(-10, -5).reduce((s, b) => s + b.volume, 0) / 5
    if (earlier > 0) volumeScore = Math.min(100, Math.round((recent / earlier) * 50))
  }

  let freshScore = 0
  if (qs.length > 0) {
    const freshCount = qs.filter(q => q.freshness === 'current').length
    freshScore = Math.round((freshCount / qs.length) * 100)
  }

  return [
    { name: '价格趋势', score: trendScore },
    { name: '波动强度', score: volScore },
    { name: '成交量趋势', score: volumeScore },
    { name: '数据新鲜度', score: freshScore },
  ]
})

/* ── 趋势状态 ─────────────────────────────────── */
const trendLabel = computed(() => {
  const t = market.marketTrend
  return t === 'up' ? '偏多' : t === 'down' ? '偏空' : '中性'
})

/* ── 标签过滤 ────────────────────────────────── */
const TAB_SYMBOL_FILTER: Record<string, string[] | null> = {
  '市场': null,
  '股票': ['000001.SZ', '000002.SZ', '600519.SH', '601318.SH'],
  '观察列表': null,
}

const filteredQuotes = computed(() => {
  const filter = TAB_SYMBOL_FILTER[activeTab.value]
  if (filter === null || filter === undefined) return market.quotes
  if (filter.length === 0) return []
  return market.quotes.filter(q => filter.includes(q.symbol))
})

const tabHeadline = computed(() => {
  const map: Record<string, string> = {
    '市场': 'MARKET HEADLINE · 综合版',
    '股票': 'EQUITIES · A 股市场',
    '观察列表': 'WATCHLIST · 关注标的',
  }
  return map[activeTab.value] || 'MARKET HEADLINE'
})

const isWatchlistTab = computed(() => activeTab.value === '观察列表')
const hasDataForTab = computed(() => filteredQuotes.value.length > 0 || TAB_SYMBOL_FILTER[activeTab.value] === null)

onMounted(() => {
  market.startPolling()
  market.checkHealth()
  if (leadSymbol.value) market.loadBars(leadSymbol.value)
})
onUnmounted(() => market.stopPolling())
</script>

<template>
  <div class="headline-page">
    <Masthead />

    <!-- 栏目标签 -->
    <nav class="section-tabs">
      <button
        v-for="tab in TABS"
        :key="tab"
        class="section-tab"
        :class="{ active: activeTab === tab }"
        @click="activeTab = tab"
      >
        {{ tab }}
      </button>
      <span class="section-logo">FG 市场资本</span>
    </nav>

    <!-- 双栏主体 -->
    <div class="headline-body">
      <!-- ═══ 左栏：头条 + 指数 + 图表 ═══ -->
      <div class="col-lead">
        <!-- 头条 -->
        <div class="headline-block">
          <span class="kicker">{{ tabHeadline }}</span>
          <h1 class="headline-title">
            <template v-if="leadQuote && !isWatchlistTab">
              {{ leadQuote.name || leadQuote.symbol }}
              {{ formatPercent(leadQuote.change_percent) }}
              <span class="headline-sub">
                市场信号：{{ signal.tendency }} · 方向一致性 {{ signal.consistency }}%（行情派生）
              </span>
            </template>
            <template v-else-if="isWatchlistTab">
              观察列表
              <span class="headline-sub">共 {{ market.quotes.length }} 个标的在跟踪</span>
            </template>
            <template v-else>
              {{ activeTab }}数据加载中…
            </template>
          </h1>
          <p class="headline-edition">A 股实时行情 · PandaData</p>
        </div>

        <!-- 指数条 -->
        <div class="index-strip">
          <div
            v-for="q in filteredQuotes.slice(0, 6)"
            :key="q.symbol"
            class="index-card"
            :class="{ active: q.symbol === leadSymbol }"
            @click="leadSymbol = q.symbol; market.loadBars(q.symbol)"
          >
            <span class="index-name">{{ q.symbol }}</span>
            <strong class="index-value mono">{{ formatNumber(q.last) }}</strong>
            <span class="index-chg" :class="directionOf(q)">
              {{ formatPercent(q.change_percent) }}
            </span>
          </div>
          <div v-if="filteredQuotes.length === 0 && !hasDataForTab" class="index-card empty">
            <span>{{ activeTab }}暂无行情数据</span>
          </div>
          <div v-else-if="filteredQuotes.length === 0" class="index-card empty">
            <span>该栏目暂无匹配标的</span>
          </div>
        </div>

        <!-- 观察列表模式 -->
        <div v-if="isWatchlistTab" class="watchlist-table">
          <div class="wl-header">
            <span class="col-sym">标的</span>
            <span class="col-num">最新</span>
            <span class="col-num">涨跌</span>
            <span class="col-num">涨跌幅</span>
            <span class="col-num">成交量</span>
          </div>
          <div
            v-for="q in market.quotes"
            :key="'wl-' + q.symbol"
            class="wl-row"
            :class="{ active: q.symbol === leadSymbol }"
            @click="leadSymbol = q.symbol; market.loadBars(q.symbol)"
          >
            <strong class="col-sym">{{ q.symbol }}</strong>
            <span class="col-num">{{ formatNumber(q.last) }}</span>
            <span class="col-num" :class="directionOf(q)">{{ formatNumber(q.change) }}</span>
            <span class="col-num" :class="directionOf(q)">{{ formatPercent(q.change_percent) }}</span>
            <span class="col-num">{{ (q.volume / 10000).toFixed(0) }}万</span>
          </div>
        </div>

        <!-- K 线 + 成交量 -->
        <div v-show="!isWatchlistTab" class="chart-block">
          <div class="chart-label">
            <span>{{ leadSymbol }} · {{ market.barsFrequency || '日线' }}</span>
            <span v-if="leadQuote" class="chart-price mono">
              {{ formatNumber(leadQuote.last) }}
            </span>
          </div>
          <MarketChart
            :bars="market.bars"
            :symbol="leadSymbol"
            :loading="market.barsLoading"
            :error="market.barsError"
          />
        </div>

        <!-- 趋势底栏 -->
        <div class="trend-rail">
          <span class="trend-icon">N</span>
          <span>趋势 {{ trendLabel }}</span>
          <span v-if="market.isStale" class="stale-tag">数据延迟</span>
        </div>
      </div>

      <!-- ═══ 右栏：市场信号（行情派生） ═══ -->
      <div class="col-ai">
        <!-- 市场倾向 + 方向一致性 -->
        <section class="ai-section">
          <h2 class="ai-heading">
            <span>市场信号</span>
            <small>MARKET SIGNALS</small>
          </h2>
          <p class="signal-note">以下为真实行情的统计派生值，非模型输出；模型分析请使用右侧 AI 侧栏。</p>
          <div class="tendency-row">
            <div class="tendency-label">
              <span>市场倾向</span>
              <strong>{{ signal.tendency }}</strong>
            </div>
            <div class="confidence-gauge">
              <svg viewBox="0 0 100 56" class="gauge-arc">
                <!-- 底弧 -->
                <path d="M8,52 A44,44 0 0,1 92,52" fill="none" stroke="var(--faint-rule)" stroke-width="6" />
                <!-- 值弧 -->
                <path
                  d="M8,52 A44,44 0 0,1 92,52"
                  fill="none"
                  stroke="var(--risk)"
                  stroke-width="6"
                  :stroke-dasharray="`${signal.consistency * 1.38} 200`"
                />
              </svg>
              <span class="gauge-value mono">{{ signal.consistency }}%</span>
              <span class="gauge-label">方向一致性</span>
            </div>
          </div>
        </section>

        <!-- 关键驱动 -->
        <section class="ai-section">
          <h3 class="ai-subheading">
            <span>关键驱动</span>
            <small>MARKET FORCES</small>
          </h3>
          <ul class="forces-list">
            <li v-for="f in marketForces" :key="f.label" class="force-item">
              <span class="force-icon">{{ f.icon }}</span>
              <span class="force-label">{{ f.label }}</span>
            </li>
          </ul>
        </section>

        <!-- 技术指标 -->
        <section class="ai-section">
          <h3 class="ai-subheading">
            <span>技术指标</span>
            <small>TECHNICAL INDICATORS</small>
          </h3>
          <ul class="evidence-list">
            <li v-for="e in technicalIndicators" :key="e.name" class="evidence-item">
              <span class="evidence-name">{{ e.name }}</span>
              <div class="evidence-bar-track">
                <div class="evidence-bar-fill" :style="{ width: e.score + '%' }" />
              </div>
              <strong class="evidence-score mono">{{ e.score }}%</strong>
            </li>
          </ul>
        </section>

        <!-- 数据状态 -->
        <section class="ai-section data-status">
          <div class="status-row">
            <span>数据源</span>
            <strong>{{ market.provider }}</strong>
          </div>
          <div class="status-row">
            <span>行情标的</span>
            <strong>{{ market.quotes.length }}</strong>
          </div>
          <div class="status-row">
            <span>K 线数</span>
            <strong>{{ market.bars.length }}</strong>
          </div>
          <div class="status-row">
            <span>新鲜度</span>
            <strong :class="{ 'down': market.isStale }">
              {{ market.isStale ? '延迟' : '正常' }}
            </strong>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ═══ 页面骨架 ═══ */
.headline-page {
  display: grid;
  min-height: 100vh;
  grid-template:
    "masthead" 64px
    "tabs" auto
    "body" minmax(0, 1fr)
    / 1fr;
  border-top: 10px solid var(--ink);
  background-color: var(--paper);
  background-image:
    radial-gradient(circle at 52% 38%, rgb(255 249 232 / 38%), transparent 58%),
    url("/textures/newsprint-paper.webp");
  background-blend-mode: normal, multiply;
  background-repeat: no-repeat, repeat;
  background-size: cover, 1200px 1200px;
  font-variant-numeric: tabular-nums lining-nums;
}
.headline-page > :deep(.masthead) { grid-area: masthead; }

/* ═══ 栏目标签 ═══ */
.section-tabs {
  grid-area: tabs;
  display: flex;
  align-items: center;
  gap: 0;
  padding: 0 20px;
  border-bottom: 2px solid var(--rule);
  background: var(--paper);
  overflow-x: auto;
  scrollbar-width: none;
}
.section-tabs::-webkit-scrollbar { display: none; }

.section-tab {
  padding: 10px 18px;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted-ink);
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.18s, border-color 0.18s;
}
.section-tab:hover { color: var(--ink); }
.section-tab.active {
  color: var(--risk);
  font-weight: 900;
  border-bottom-color: var(--risk);
}
.section-logo {
  margin-left: auto;
  font-family: var(--font-numeric);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--muted-ink);
  white-space: nowrap;
  padding-left: 16px;
}

/* ═══ 双栏主体 ═══ */
.headline-body {
  grid-area: body;
  display: grid;
  grid-template-columns: 1fr 340px;
  min-height: 0;
}

/* ═══ 左栏 ═══ */
.col-lead {
  padding: 20px 24px;
  border-right: 1px solid var(--rule);
  overflow-y: auto;
}

.headline-block {
  padding-bottom: 16px;
  border-bottom: 3px double var(--rule);
  margin-bottom: 16px;
}
.headline-block .kicker {
  display: block;
  margin-bottom: 8px;
}
.headline-title {
  font-size: clamp(1.6rem, 3vw, 2.6rem);
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.01em;
  margin: 0;
}
.headline-sub {
  display: block;
  font-size: 0.52em;
  font-weight: 600;
  color: var(--muted-ink);
  margin-top: 6px;
  letter-spacing: 0;
}
.headline-edition {
  color: var(--muted-ink);
  font-size: 0.82rem;
  margin: 8px 0 0;
}

/* 指数条 */
.index-strip {
  display: flex;
  gap: 12px;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--rule);
  overflow-x: auto;
  scrollbar-width: none;
}
.index-strip::-webkit-scrollbar { display: none; }

.index-card {
  flex-shrink: 0;
  min-width: 120px;
  padding: 10px 14px;
  border: 1px solid var(--faint-rule);
  background: var(--paper-light);
  cursor: pointer;
  transition: border-color 0.18s, background 0.18s;
  display: grid;
  gap: 3px;
}
.index-card:hover { border-color: var(--rule); }
.index-card.active { border-color: var(--risk); background: rgb(143 48 39 / 5%); }
.index-card.empty {
  display: grid;
  place-items: center;
  color: var(--muted-ink);
  min-width: 200px;
}
.index-name {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted-ink);
  letter-spacing: 0.06em;
}
.index-value {
  font-size: 16px;
  font-weight: 700;
}
.index-chg {
  font-size: 13px;
  font-weight: 700;
  font-family: var(--font-numeric);
}

/* 图表 */
.chart-block {
  margin-bottom: 12px;
}
.chart-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--faint-rule);
  margin-bottom: 10px;
  font-size: 12px;
  font-weight: 700;
  color: var(--muted-ink);
  letter-spacing: 0.04em;
}
.chart-price {
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
}

/* 趋势底栏 */
.trend-rail {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 0;
  border-top: 1px solid var(--rule);
  font-size: 13px;
  font-weight: 700;
  color: var(--muted-ink);
}
.trend-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--rule);
  font-family: var(--font-numeric);
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
}
.stale-tag {
  margin-left: auto;
  padding: 2px 8px;
  border: 1px solid var(--risk);
  color: var(--risk);
  font-size: 11px;
  font-weight: 800;
}

/* 观察列表表格 */
.watchlist-table {
  border-top: 1px solid var(--rule);
  margin-bottom: 12px;
}
.wl-header {
  display: grid;
  grid-template-columns: minmax(0,1fr) 80px 70px 70px 70px;
  gap: 4px;
  padding: 8px 0 6px;
  font-size: 11px;
  font-weight: 900;
  color: var(--muted-ink);
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--rule);
}
.wl-header .col-num { text-align: right; }
.wl-row {
  display: grid;
  grid-template-columns: minmax(0,1fr) 80px 70px 70px 70px;
  gap: 4px;
  padding: 8px 0;
  border-bottom: 1px solid var(--faint-rule);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.15s;
}
.wl-row:hover { background: var(--faint-rule); }
.wl-row.active { background: rgb(45 34 22 / 10%); }
.wl-row .col-sym {
  font-family: var(--font-numeric);
  font-weight: 700;
}
.wl-row .col-num {
  text-align: right;
  font-family: var(--font-numeric);
  font-size: 13px;
}

/* ═══ 右栏 ═══ */
.col-ai {
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--faint-rule) transparent;
}

.ai-section {
  padding: 18px 20px;
  border-bottom: 1px solid var(--rule);
}
.ai-section:last-child { border-bottom: 0; }

.signal-note {
  margin: 0 0 12px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--muted-ink);
}

.ai-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin: 0 0 14px;
  font-size: 15px;
  font-weight: 900;
  letter-spacing: 0.04em;
}
.ai-heading small {
  color: var(--muted-ink);
  font-family: var(--font-numeric);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.ai-subheading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin: 0 0 12px;
  font-size: 13px;
  font-weight: 900;
  letter-spacing: 0.03em;
}
.ai-subheading small {
  color: var(--muted-ink);
  font-family: var(--font-numeric);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

/* 倾向 + 置信度 */
.tendency-row {
  display: flex;
  align-items: center;
  gap: 20px;
}
.tendency-label {
  display: grid;
  gap: 4px;
}
.tendency-label span {
  font-size: 12px;
  color: var(--muted-ink);
}
.tendency-label strong {
  font-size: 1.6rem;
  color: var(--risk);
  font-weight: 900;
}
.confidence-gauge {
  display: grid;
  justify-items: center;
  gap: 2px;
}
.gauge-arc {
  width: 88px;
  height: 50px;
}
.gauge-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--risk);
}
.gauge-label {
  font-size: 10px;
  color: var(--muted-ink);
  font-weight: 700;
  letter-spacing: 0.06em;
}

/* 关键驱动 */
.forces-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0;
}
.force-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--faint-rule);
  font-size: 14px;
}
.force-item:last-child { border-bottom: 0; }
.force-icon {
  width: 24px;
  text-align: center;
  font-size: 15px;
  color: var(--risk);
  flex-shrink: 0;
}
.force-label {
  font-weight: 600;
}

/* 模型证据 */
.evidence-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.evidence-item {
  display: grid;
  grid-template-columns: 1fr 80px 40px;
  align-items: center;
  gap: 10px;
}
.evidence-name {
  font-size: 13px;
  font-weight: 600;
}
.evidence-bar-track {
  height: 4px;
  background: var(--faint-rule);
}
.evidence-bar-fill {
  height: 100%;
  background: var(--risk);
  transition: width 0.4s ease;
}
.evidence-score {
  font-size: 13px;
  font-weight: 700;
  text-align: right;
}

/* 数据状态 */
.data-status .status-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 5px 0;
  font-size: 13px;
  border-bottom: 1px solid var(--faint-rule);
}
.data-status .status-row:last-child { border-bottom: 0; }
.data-status .status-row span {
  color: var(--muted-ink);
}
.data-status .status-row strong {
  font-family: var(--font-numeric);
  font-weight: 700;
}

/* ═══ 响应式 ═══ */
@media (max-width: 1100px) {
  .headline-body {
    grid-template-columns: 1fr;
  }
  .col-lead {
    border-right: 0;
    border-bottom: 1px solid var(--rule);
  }
  .col-ai {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .col-ai .ai-section:last-child {
    grid-column: 1 / -1;
  }
}
</style>
