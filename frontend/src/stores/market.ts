/* ═══════════════════════════════════════════════════
   行情轮询状态 — Pinia Store
   支持自动轮询、标签页隐藏暂停、缓存过期
   ═══════════════════════════════════════════════════ */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { fetchQuotes, fetchBars, fetchHealth } from '@/api/desk'
import type {
  MarketQuote,
  MarketBar,
  QuoteBatch,
  HealthResponse,
  BarsResponse,
} from '@/types/desk'
import { DEFAULT_SYMBOLS } from '@/types/desk'

/** 允许的轮询间隔（毫秒），对应设计 §8.2 可选频率：1/3/5/15/60 秒 */
export const POLL_INTERVAL_OPTIONS = [1_000, 3_000, 5_000, 15_000, 60_000] as const
/** 默认轮询间隔（毫秒） */
const DEFAULT_POLL_INTERVAL = 5_000
/** 缓存过期基线（毫秒） */
const CACHE_TTL = 30_000

export const useMarketStore = defineStore('market', () => {
  // ─── 状态 ──────────────────────────────────────

  const quotes = ref<MarketQuote[]>([])
  const quoteErrors = ref<Record<string, string>>({})
  const quotesLoading = ref(false)
  const quotesError = ref<string | null>(null)
  const quotesUpdatedAt = ref<number>(0)

  const bars = ref<MarketBar[]>([])
  const barsSymbol = ref<string>('')
  const contextSymbol = ref<string>('')
  const barsFrequency = ref<string>('')
  const barsLoading = ref(false)
  const barsError = ref<string | null>(null)

  const health = ref<HealthResponse | null>(null)
  const healthError = ref<string | null>(null)

  // 轮询控制
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let visibilityHandler: (() => void) | null = null
  let activeSymbols: string[] = DEFAULT_SYMBOLS
  let quotesInFlight = false
  const isPolling = ref(false)
  /** 当前轮询间隔（毫秒），用户可通过 setPollInterval 调整 */
  const pollIntervalMs = ref<number>(DEFAULT_POLL_INTERVAL)
  /** 是否已被用户暂停（区别于标签页隐藏的临时停止） */
  const isPaused = ref(false)
  /** 最近一次拉取失败的时间戳（0 表示无失败或已恢复） */
  const quotesFailedAt = ref<number>(0)

  // ─── 计算属性 ───────────────────────────────────

  const quotesMap = computed(() => {
    const map = new Map<string, MarketQuote>()
    for (const q of quotes.value) map.set(q.symbol, q)
    return map
  })

  const isStale = computed(() => {
    // 过期阈值随轮询间隔自适应，避免低频（如 60 秒）时被误判为过期
    const threshold = Math.max(CACHE_TTL, pollIntervalMs.value * 2)
    return Date.now() - quotesUpdatedAt.value > threshold
  })

  const provider = computed(() => health.value?.market_data ?? '—')

  // ─── 派生指标（从真实行情数据计算） ───────────────

  /** 市场趋势：多数标的涨跌方向 */
  const marketTrend = computed<'up' | 'down' | 'neutral'>(() => {
    const qs = quotes.value
    if (qs.length === 0) return 'neutral'
    const ups = qs.filter(q => (q.change ?? 0) > 0).length
    const downs = qs.filter(q => (q.change ?? 0) < 0).length
    if (ups > downs && ups >= qs.length / 2) return 'up'
    if (downs > ups && downs >= qs.length / 2) return 'down'
    return 'neutral'
  })

  /** 波动率：涨跌幅标准差（百分比） */
  const marketVolatility = computed(() => {
    const pcts = quotes.value.map(q => Math.abs(q.change_percent ?? 0) * 100)
    if (pcts.length === 0) return 0
    const mean = pcts.reduce((a, b) => a + b, 0) / pcts.length
    const variance = pcts.reduce((a, b) => a + (b - mean) ** 2, 0) / pcts.length
    return Math.sqrt(variance)
  })

  /** 市场宽度：上涨占比（0-1） */
  const marketBreadth = computed(() => {
    const qs = quotes.value
    if (qs.length === 0) return 0
    const advancing = qs.filter(q => (q.change ?? 0) > 0).length
    return advancing / qs.length
  })

  /** 上涨/下跌/持平计数 */
  const advanceDecline = computed(() => {
    const qs = quotes.value
    const advancing = qs.filter(q => (q.change ?? 0) > 0).length
    const declining = qs.filter(q => (q.change ?? 0) < 0).length
    const unchanged = qs.length - advancing - declining
    return { advancing, declining, unchanged }
  })

  /** 市场信号：从真实行情派生的方向倾向与方向一致性（统计派生，非模型/AI 输出） */
  const marketSignal = computed(() => {
    const trend = marketTrend.value
    const vol = marketVolatility.value
    const breadth = marketBreadth.value

    // 倾向
    let tendency: string
    if (trend === 'up' && breadth > 0.6) tendency = '积极'
    else if (trend === 'down' && breadth < 0.4) tendency = '谨慎'
    else tendency = '中性'

    // 方向一致性：涨跌方向越集中 → 一致性越高
    const agreement = Math.abs(breadth - 0.5) * 2  // 0-1
    const consistency = Math.round(50 + agreement * 40 + (vol > 1 ? -5 : 5))

    return {
      tendency,
      consistency: Math.max(40, Math.min(95, consistency)),
    }
  })

  // ─── 行情拉取 ───────────────────────────────────

  async function loadQuotes(symbols: string[] = DEFAULT_SYMBOLS) {
    // 请求进行中不启动下一次相同拉取（设计 §8.2）
    if (quotesInFlight) return
    quotesInFlight = true
    quotesLoading.value = true
    quotesError.value = null
    try {
      const batch: QuoteBatch = await fetchQuotes(symbols)
      quotes.value = [...batch.quotes]
      quoteErrors.value = { ...batch.errors }
      quotesUpdatedAt.value = Date.now()
      quotesFailedAt.value = 0
    } catch (err) {
      // 失败时保留最后一次成功值，仅记录错误与失败时间
      quotesError.value = err instanceof Error ? err.message : String(err)
      quotesFailedAt.value = Date.now()
    } finally {
      quotesLoading.value = false
      quotesInFlight = false
    }
  }

  // ─── 当前上下文标的 ──────────────────────────────

  /** 设置当前聚焦标的（用于 AI 侧栏跟随当前对象）；null 表示清空 */
  function setContextSymbol(symbol: string | null) {
    contextSymbol.value = symbol ?? ''
  }

  // ─── K线拉取 ────────────────────────────────────

  async function loadBars(symbol: string, limit = 80) {
    contextSymbol.value = symbol
    barsLoading.value = true
    barsError.value = null
    try {
      const result: BarsResponse = await fetchBars(symbol, limit)
      bars.value = [...result.bars]
      barsSymbol.value = result.symbol
      barsFrequency.value = result.frequency
    } catch (err) {
      barsError.value = err instanceof Error ? err.message : String(err)
      bars.value = []
    } finally {
      barsLoading.value = false
    }
  }

  // ─── 健康检查 ───────────────────────────────────

  async function checkHealth() {
    healthError.value = null
    try {
      health.value = await fetchHealth()
    } catch (err) {
      healthError.value = err instanceof Error ? err.message : String(err)
      health.value = null
    }
  }

  // ─── 轮询控制 ───────────────────────────────────

  /** 更新当前观察标的池；若已在轮询则立即用新列表刷新。 */
  function setWatchSymbols(symbols: string[]) {
    activeSymbols = symbols.length > 0 ? [...symbols] : [...DEFAULT_SYMBOLS]
    if (isPolling.value && !isPaused.value) loadQuotes(activeSymbols)
  }

  function startPolling(symbols: string[] = DEFAULT_SYMBOLS) {
    activeSymbols = symbols.length > 0 ? [...symbols] : [...DEFAULT_SYMBOLS]
    if (isPolling.value) {
      if (!isPaused.value) loadQuotes(activeSymbols)
      return
    }
    isPolling.value = true
    isPaused.value = false

    // 立即拉取一次
    loadQuotes(activeSymbols)
    scheduleTimer()

    // 标签页隐藏暂停，恢复可见时立即拉取
    visibilityHandler = () => {
      if (!document.hidden && isPolling.value) loadQuotes(activeSymbols)
    }
    document.addEventListener('visibilitychange', visibilityHandler)
  }

  /** 按当前 pollIntervalMs 重建定时器 */
  function scheduleTimer() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    pollTimer = setInterval(() => {
      if (!document.hidden) loadQuotes(activeSymbols)
    }, pollIntervalMs.value)
  }

  /**
   * 设置轮询频率。传入 POLL_INTERVAL_OPTIONS 中的毫秒值切换频率；
   * 传入 0（或非正值）表示“暂停”，停止轮询但保留已有数据。
   */
  function setPollInterval(ms: number) {
    if (ms > 0) {
      pollIntervalMs.value = ms
      isPaused.value = false
      if (isPolling.value) {
        scheduleTimer()
      } else {
        startPolling(activeSymbols)
      }
      return
    }
    // 暂停：清除定时器但保留可见性监听与已拉取数据
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    isPolling.value = false
    isPaused.value = true
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    if (visibilityHandler) {
      document.removeEventListener('visibilitychange', visibilityHandler)
      visibilityHandler = null
    }
    isPolling.value = false
    isPaused.value = false
  }

  return {
    // 状态
    quotes,
    quoteErrors,
    quotesLoading,
    quotesError,
    quotesUpdatedAt,
    bars,
    barsSymbol,
    contextSymbol,
    barsFrequency,
    barsLoading,
    barsError,
    health,
    healthError,
    isPolling,
    isPaused,
    pollIntervalMs,
    quotesFailedAt,
    isStale,
    // 计算
    quotesMap,
    provider,
    marketTrend,
    marketVolatility,
    marketBreadth,
    advanceDecline,
    marketSignal,
    // 方法
    loadQuotes,
    loadBars,
    setContextSymbol,
    checkHealth,
    startPolling,
    stopPolling,
    setWatchSymbols,
    setPollInterval,
  }
})
