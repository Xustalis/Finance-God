/* ═══════════════════════════════════════════════════
   行情轮询状态 — Pinia Store
   支持自动轮询、标签页隐藏暂停、缓存过期
   ═══════════════════════════════════════════════════ */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { fetchMarketOverview, fetchBars, fetchHealth, isCanceledError } from '@/api/desk'
import type {
  MarketQuote,
  MarketBar,
  HealthResponse,
  BarsResponse,
  MarketOverviewView,
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
  /** 当前在途 K 线请求的取消控制器：切换标的时用于取消上一笔并识别过期响应。 */
  let barsAbort: AbortController | null = null
  /** 订阅计数：多个页面/组件可并发订阅，仅当归零时才真正停止轮询。 */
  let subscribers = 0
  const isPolling = ref(false)
  /** 当前轮询间隔（毫秒），用户可通过 setPollInterval 调整 */
  const pollIntervalMs = ref<number>(DEFAULT_POLL_INTERVAL)
  /** 是否已被用户暂停（区别于标签页隐藏的临时停止） */
  const isPaused = ref(false)
  /** 最近一次拉取失败的时间戳（0 表示无失败或已恢复） */
  const quotesFailedAt = ref<number>(0)
  const overview = ref<MarketOverviewView | null>(null)
  const overviewError = ref<string | null>(null)

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

  // ─── 行情拉取 ───────────────────────────────────

  async function loadQuotes(symbols: string[] = DEFAULT_SYMBOLS) {
    // 请求进行中不启动下一次相同拉取（设计 §8.2）
    if (quotesInFlight) return
    quotesInFlight = true
    quotesLoading.value = true
    quotesError.value = null
    overviewError.value = null
    try {
      const result = await fetchMarketOverview(symbols)
      overview.value = result
      quotes.value = [...result.data.quotes]
      quoteErrors.value = {}
      quotesUpdatedAt.value = Date.now()
      quotesFailedAt.value = 0
    } catch (err) {
      // 失败时保留最后一次成功值，仅记录错误与失败时间
      quotesError.value = err instanceof Error ? err.message : String(err)
      overviewError.value = quotesError.value
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
    // 取消上一笔未完成的 K 线请求，避免竞态覆盖与无谓网络开销。
    if (barsAbort) barsAbort.abort()
    const controller = new AbortController()
    barsAbort = controller
    barsLoading.value = true
    barsError.value = null
    try {
      const result: BarsResponse = await fetchBars(symbol, limit, controller.signal)
      // 已被更新的请求取代（或乱序返回）则丢弃旧结果，不覆盖当前标的的数据。
      if (barsAbort !== controller) return
      bars.value = [...result.bars]
      barsSymbol.value = result.symbol
      barsFrequency.value = result.frequency
    } catch (err) {
      // 取消或已被取代的请求静默忽略；仅当前有效请求的真实失败才置错误态。
      if (isCanceledError(err) || barsAbort !== controller) return
      barsError.value = err instanceof Error ? err.message : String(err)
      bars.value = []
    } finally {
      // 仅当自身仍是最新请求时才复位加载态，避免复位更新请求的进行中标记。
      if (barsAbort === controller) {
        barsLoading.value = false
        barsAbort = null
      }
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
  // 采用引用计数：路由切换时新页面 onMounted 与旧页面 onUnmounted 的时序可能交错，
  // 若用单一“启动/停止”开关会被误停；改为订阅数增减，仅归零时才真正停止。

  /** 启动定时器与可见性监听并立即拉取一次；仅在“未暂停且当前未激活”时调用。 */
  function activate() {
    isPolling.value = true
    loadQuotes(activeSymbols)
    scheduleTimer()
    if (!visibilityHandler) {
      visibilityHandler = () => {
        if (!document.hidden && isPolling.value) loadQuotes(activeSymbols)
      }
      document.addEventListener('visibilitychange', visibilityHandler)
    }
  }

  /** 清除定时器与可见性监听；不改变订阅计数与暂停标记。 */
  function deactivate() {
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

  /** 更新当前观察标的池；若已在轮询则立即用新列表刷新。 */
  function setWatchSymbols(symbols: string[]) {
    activeSymbols = symbols.length > 0 ? [...symbols] : [...DEFAULT_SYMBOLS]
    if (isPolling.value && !isPaused.value) loadQuotes(activeSymbols)
  }

  /** 订阅轮询（页面 onMounted 调用）：订阅数 +1，首个订阅者启动轮询。 */
  function startPolling(symbols: string[] = DEFAULT_SYMBOLS) {
    activeSymbols = symbols.length > 0 ? [...symbols] : [...DEFAULT_SYMBOLS]
    subscribers += 1
    if (isPaused.value) return
    if (isPolling.value) {
      loadQuotes(activeSymbols)
      return
    }
    activate()
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
   * 传入 0（或非正值）表示“暂停”，停止定时器但保留订阅计数与已拉取数据。
   */
  function setPollInterval(ms: number) {
    if (ms > 0) {
      pollIntervalMs.value = ms
      isPaused.value = false
      if (isPolling.value) {
        scheduleTimer()
      } else {
        activate()
      }
      return
    }
    // 暂停：停止定时器与监听但保留订阅计数与已拉取数据
    deactivate()
    isPaused.value = true
  }

  /** 取消订阅（页面 onUnmounted 调用）：订阅数 -1，归零时停止轮询并清除暂停。 */
  function stopPolling() {
    if (subscribers > 0) subscribers -= 1
    if (subscribers > 0) return
    deactivate()
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
    overview,
    overviewError,
    isStale,
    // 计算
    quotesMap,
    provider,
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
