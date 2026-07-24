/* ═══════════════════════════════════════════════════
   行情异动通知 — Pinia Store
   服务端定时轮询 + 异动检测已在后端完成；前端按间隔轮询
   /market/alerts，新告警以可关闭弹窗（toast）呈现，历史可翻看。
   标签页隐藏暂停、恢复即刷新、失败保留陈旧态。
   ═══════════════════════════════════════════════════ */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { fetchMarketAlerts } from '@/api/desk'
import type { MarketAlertView } from '@/types/desk'

/** 默认轮询间隔（毫秒）。服务端为长间隔轮询，前端读取侧可稍快感知。 */
const DEFAULT_POLL_INTERVAL = 15_000
/** 已读告警 id 的本地持久化键（客户端确认态；全局告警无服务端 per-user 读态）。 */
const ACK_STORAGE_KEY = 'finance-god-market-alerts-ack'
/** 同时最多展示的 toast 数量，超出则丢弃最旧（历史仍可在提醒中心翻看）。 */
const MAX_TOASTS = 4

function loadAcknowledged(): Set<string> {
  try {
    const raw = localStorage.getItem(ACK_STORAGE_KEY)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? new Set(parsed.map(String)) : new Set()
  } catch {
    return new Set()
  }
}

function persistAcknowledged(ids: Set<string>): void {
  try {
    localStorage.setItem(ACK_STORAGE_KEY, JSON.stringify([...ids]))
  } catch {
    // 本地存储不可用（隐私模式等）时静默降级：确认态仅存活于本次会话。
  }
}

export const useNotificationsStore = defineStore('notifications', () => {
  // ─── 状态 ──────────────────────────────────────
  const alerts = ref<MarketAlertView[]>([])
  const toasts = ref<MarketAlertView[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const updatedAt = ref<number>(0)
  const failedAt = ref<number>(0)
  const pollIntervalMs = ref<number>(DEFAULT_POLL_INTERVAL)
  const isPolling = ref(false)

  const acknowledgedIds = ref<Set<string>>(loadAcknowledged())
  /** 已知告警 id：用于区分“新到达”与“历史”，避免首屏为陈年告警弹窗。 */
  const knownIds = new Set<string>()
  /** 是否已完成首次基线拉取（首次仅登记已知 id，不弹窗）。 */
  let baselined = false

  // 轮询控制（引用计数 + 可见性暂停，与行情轮询一致）
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let visibilityHandler: (() => void) | null = null
  let subscribers = 0
  let inFlight = false

  // ─── 计算属性 ───────────────────────────────────
  const unreadCount = computed(
    () => alerts.value.filter((a) => !acknowledgedIds.value.has(a.alert_id)).length,
  )
  const hasToasts = computed(() => toasts.value.length > 0)

  function isAcknowledged(alertId: string): boolean {
    return acknowledgedIds.value.has(alertId)
  }

  // ─── 拉取 ───────────────────────────────────────
  async function refresh(): Promise<void> {
    if (inFlight) return
    inFlight = true
    loading.value = true
    error.value = null
    try {
      const response = await fetchMarketAlerts()
      const incoming = response.alerts
      if (!baselined) {
        // 首次拉取：登记为已知基线，不为历史告警弹窗。
        for (const alert of incoming) knownIds.add(alert.alert_id)
        baselined = true
      } else {
        // 后续拉取：为未见过且未确认的新告警入队 toast。
        for (const alert of incoming) {
          if (knownIds.has(alert.alert_id)) continue
          knownIds.add(alert.alert_id)
          if (!acknowledgedIds.value.has(alert.alert_id)) enqueueToast(alert)
        }
      }
      alerts.value = incoming
      updatedAt.value = Date.now()
      failedAt.value = 0
    } catch (err) {
      // 失败保留陈旧态，仅记录错误与失败时间。
      error.value = err instanceof Error ? err.message : String(err)
      failedAt.value = Date.now()
    } finally {
      loading.value = false
      inFlight = false
    }
  }

  function enqueueToast(alert: MarketAlertView): void {
    if (toasts.value.some((t) => t.alert_id === alert.alert_id)) return
    const next = [...toasts.value, alert]
    // 超出上限丢弃最旧的可见 toast（其仍留存于 alerts 历史中）。
    toasts.value = next.slice(-MAX_TOASTS)
  }

  /** 关闭某条 toast（不改变已读态；仅从可见弹窗移除）。 */
  function dismissToast(alertId: string): void {
    toasts.value = toasts.value.filter((t) => t.alert_id !== alertId)
  }

  /** 标记某告警已读（客户端确认，持久化到本地），并从可见弹窗移除。 */
  function acknowledge(alertId: string): void {
    const next = new Set(acknowledgedIds.value)
    next.add(alertId)
    acknowledgedIds.value = next
    persistAcknowledged(next)
    dismissToast(alertId)
  }

  /** 标记全部当前告警已读。 */
  function acknowledgeAll(): void {
    const next = new Set(acknowledgedIds.value)
    for (const alert of alerts.value) next.add(alert.alert_id)
    acknowledgedIds.value = next
    persistAcknowledged(next)
    toasts.value = []
  }

  // ─── 轮询控制 ───────────────────────────────────
  function activate(): void {
    isPolling.value = true
    refresh()
    scheduleTimer()
    if (!visibilityHandler) {
      visibilityHandler = () => {
        if (!document.hidden && isPolling.value) refresh()
      }
      document.addEventListener('visibilitychange', visibilityHandler)
    }
  }

  function scheduleTimer(): void {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    pollTimer = setInterval(() => {
      if (!document.hidden) refresh()
    }, pollIntervalMs.value)
  }

  function deactivate(): void {
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

  /** 订阅轮询（组件 onMounted 调用）：订阅数 +1，首个订阅者启动轮询。 */
  function startPolling(): void {
    subscribers += 1
    if (isPolling.value) {
      refresh()
      return
    }
    activate()
  }

  /** 取消订阅（组件 onUnmounted 调用）：订阅数 -1，归零时停止轮询。 */
  function stopPolling(): void {
    if (subscribers > 0) subscribers -= 1
    if (subscribers > 0) return
    deactivate()
  }

  return {
    // 状态
    alerts,
    toasts,
    loading,
    error,
    updatedAt,
    failedAt,
    pollIntervalMs,
    isPolling,
    acknowledgedIds,
    // 计算
    unreadCount,
    hasToasts,
    isAcknowledged,
    // 方法
    refresh,
    dismissToast,
    acknowledge,
    acknowledgeAll,
    startPolling,
    stopPolling,
  }
})
