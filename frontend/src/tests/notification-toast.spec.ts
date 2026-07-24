import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import NotificationToast from '@/components/desk/NotificationToast.vue'
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

/** Drive the store so exactly one new toast (id) is enqueued. */
async function seedToast(id: string): Promise<void> {
  fetchMarketAlerts.mockResolvedValueOnce({ provider: 'PandaData', alerts: [] })
  const store = useNotificationsStore()
  await store.refresh() // baseline
  fetchMarketAlerts.mockResolvedValueOnce({ provider: 'PandaData', alerts: [alert(id)] })
  await store.refresh() // enqueue toast
}

describe('NotificationToast', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    fetchMarketAlerts.mockReset()
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders a warning toast with the alert role and auto-dismisses after its timeout', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    await seedToast('a1')
    const store = useNotificationsStore()

    const wrapper = mount(NotificationToast, { global: { plugins: [pinia] } })
    await flushPromises()

    const toast = wrapper.get('.toast')
    expect(toast.attributes('role')).toBe('alert')
    expect(toast.attributes('aria-live')).toBe('assertive')
    expect(store.toasts).toHaveLength(1)

    // Warning auto-dismiss window elapses → the popup hides but stays unread.
    await vi.advanceTimersByTimeAsync(9_000)
    expect(store.toasts).toHaveLength(0)
    expect(store.isAcknowledged('a1')).toBe(false)
    wrapper.unmount()
  })

  it('marks read when the close button is clicked', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    await seedToast('a1')
    const store = useNotificationsStore()

    const wrapper = mount(NotificationToast, { global: { plugins: [pinia] } })
    await flushPromises()

    await wrapper.get('.toast-close').trigger('click')
    expect(store.toasts).toHaveLength(0)
    expect(store.isAcknowledged('a1')).toBe(true)
    wrapper.unmount()
  })
})
