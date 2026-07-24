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

/** 轮询间隔（毫秒） */
const POLL_INTERVAL = 10_000
/** 缓存过期时间（毫秒） */
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
  const barsFrequency = ref<string>('')
  const barsLoading = ref(false)
  const barsError = ref<string | null>(null)

  const health = ref<HealthResponse | null>(null)
  const healthError = ref<string | null>(null)

  // 轮询控制
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let visibilityHandler: (() => void) | null = null
  const isPolling = ref(false)

  // ─── 计算属性 ───────────────────────────────────

  const quotesMap = computed(() => {
    const map = new Map<string, MarketQuote>()
    for (const q of quotes.value) map.set(q.symbol, q)
    return map
  })

  const isStale = computed(() => {
    return Date.now() - quotesUpdatedAt.value > CACHE_TTL
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

  /** AI 简报：从行情数据派生的倾向与置信度 */
  const aiSentiment = computed(() => {
    const trend = marketTrend.value
    const vol = marketVolatility.value
    const breadth = marketBreadth.value

    // 倾向
    let tendency: string
    if (trend === 'up' && breadth > 0.6) tendency = '积极'
    else if (trend === 'down' && breadth < 0.4) tendency = '谨慎'
    else tendency = '中性'

    // 置信度：方向一致性越高 → 置信度越高
    const consistency = Math.abs(breadth - 0.5) * 2  // 0-1
    const confidence = Math.round(50 + consistency * 40 + (vol > 1 ? -5 : 5))

    return {
      tendency,
      confidence: Math.max(40, Math.min(95, confidence)),
    }
  })

  // ─── 行情拉取 ───────────────────────────────────

  async function loadQuotes(symbols: string[] = DEFAULT_SYMBOLS) {
    quotesLoading.value = true
    quotesError.value = null
    try {
      const batch: QuoteBatch = await fetchQuotes(symbols)
      quotes.value = [...batch.quotes]
      quoteErrors.value = { ...batch.errors }
      quotesUpdatedAt.value = Date.now()
    } catch (err) {
      quotesError.value = err instanceof Error ? err.message : String(err)
    } finally {
      quotesLoading.value = false
    }
  }

  // ─── K线拉取 ────────────────────────────────────

  async function loadBars(symbol: string, limit = 80) {
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

  function startPolling(symbols: string[] = DEFAULT_SYMBOLS) {
    if (isPolling.value) return
    isPolling.value = true

    // 立即拉取一次
    loadQuotes(symbols)

    pollTimer = setInterval(() => {
      if (!document.hidden) {
        loadQuotes(symbols)
      }
    }, POLL_INTERVAL)

    // 标签页隐藏暂停
    visibilityHandler = () => {
      // 恢复可见时立即拉取
      if (!document.hidden) loadQuotes(symbols)
    }
    document.addEventListener('visibilitychange', visibilityHandler)
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
    barsFrequency,
    barsLoading,
    barsError,
    health,
    healthError,
    isPolling,
    isStale,
    // 计算
    quotesMap,
    provider,
    marketTrend,
    marketVolatility,
    marketBreadth,
    advanceDecline,
    aiSentiment,
    // 方法
    loadQuotes,
    loadBars,
    checkHealth,
    startPolling,
    stopPolling,
  }
})
