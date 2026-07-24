import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useNotificationsStore } from '@/stores/notifications'
import type { MarketAlertView } from '@/types/desk'

const fetchMarketAlerts = vi.fn()

vi.mock('@/api/desk', () => ({
  fetchMarketAlerts: (...args: unknown[]) => fetchMarketAlerts(...args),
}))

function alert(id: string, overrides: Partial<MarketAlertView> = {}): MarketAlertView {
  return {
    alert_id: id,
    symbol: '600519.SH',
    name: '贵州茅台',
    kind: 'surge',
    severity: 'warning',
    change_percent: 0.061,
    last: 1680,
    message: `异动 ${id}`,
    provider_time: '2026-07-24T09:30:00+08:00',
    detected_at: '2026-07-24T01:30:00Z',
    ...overrides,
  }
}

function resolveAlerts(alerts: MarketAlertView[]) {
  fetchMarketAlerts.mockResolvedValueOnce({ provider: 'PandaData', alerts })
}

describe('notifications store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    fetchMarketAlerts.mockReset()
  })

  it('seeds a baseline on first fetch without popping historical alerts', async () => {
    const store = useNotificationsStore()
    resolveAlerts([alert('a1'), alert('a2')])

    await store.refresh()

    expect(store.alerts).toHaveLength(2)
    expect(store.toasts).toHaveLength(0)
    expect(store.unreadCount).toBe(2)
  })

  it('pops a toast only for alerts arriving after the baseline', async () => {
    const store = useNotificationsStore()
    resolveAlerts([alert('a1')])
    await store.refresh()
    expect(store.toasts).toHaveLength(0)

    resolveAlerts([alert('a2'), alert('a1')])
    await store.refresh()

    expect(store.toasts.map((t) => t.alert_id)).toEqual(['a2'])
  })

  it('acknowledging marks read, removes the toast, and persists', async () => {
    const store = useNotificationsStore()
    resolveAlerts([alert('a1')])
    await store.refresh()
    resolveAlerts([alert('a2'), alert('a1')])
    await store.refresh()

    store.acknowledge('a2')

    expect(store.toasts).toHaveLength(0)
    expect(store.isAcknowledged('a2')).toBe(true)
    expect(store.unreadCount).toBe(1)
    expect(localStorage.getItem('finance-god-market-alerts-ack')).toContain('a2')
  })

  it('does not re-pop an acknowledged alert on later fetches', async () => {
    const store = useNotificationsStore()
    resolveAlerts([alert('a1')])
    await store.refresh()
    resolveAlerts([alert('a2'), alert('a1')])
    await store.refresh()
    store.acknowledge('a2')

    resolveAlerts([alert('a2'), alert('a1')])
    await store.refresh()

    expect(store.toasts).toHaveLength(0)
  })

  it('dismissToast hides the popup but keeps it unread', async () => {
    const store = useNotificationsStore()
    resolveAlerts([alert('a1')])
    await store.refresh()
    resolveAlerts([alert('a2'), alert('a1')])
    await store.refresh()

    store.dismissToast('a2')

    expect(store.toasts).toHaveLength(0)
    expect(store.isAcknowledged('a2')).toBe(false)
    expect(store.unreadCount).toBe(2)
  })

  it('acknowledgeAll clears toasts and unread count', async () => {
    const store = useNotificationsStore()
    resolveAlerts([alert('a1'), alert('a2')])
    await store.refresh()
    resolveAlerts([alert('a3'), alert('a1'), alert('a2')])
    await store.refresh()

    store.acknowledgeAll()

    expect(store.toasts).toHaveLength(0)
    expect(store.unreadCount).toBe(0)
  })

  it('keeps stale alerts and records the failure when a fetch fails', async () => {
    const store = useNotificationsStore()
    resolveAlerts([alert('a1')])
    await store.refresh()

    fetchMarketAlerts.mockRejectedValueOnce(new Error('network down'))
    await store.refresh()

    expect(store.alerts).toHaveLength(1)
    expect(store.error).toBe('network down')
    expect(store.failedAt).toBeGreaterThan(0)
  })
})

describe('notifications polling pauses when the tab is hidden', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    fetchMarketAlerts.mockReset()
    fetchMarketAlerts.mockResolvedValue({ provider: 'PandaData', alerts: [] })
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('skips the interval fetch while document.hidden is true', async () => {
    const store = useNotificationsStore()
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })

    store.startPolling()
    expect(fetchMarketAlerts).toHaveBeenCalledTimes(1) // immediate refresh

    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
    await vi.advanceTimersByTimeAsync(15_000)
    expect(fetchMarketAlerts).toHaveBeenCalledTimes(1) // hidden: interval skipped

    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
    await vi.advanceTimersByTimeAsync(15_000)
    expect(fetchMarketAlerts).toHaveBeenCalledTimes(2) // visible: interval fires

    store.stopPolling()
  })
})
