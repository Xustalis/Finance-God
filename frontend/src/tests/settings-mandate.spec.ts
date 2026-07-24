import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import SettingsView from '@/views/SettingsView.vue'
import type { InvestmentMandate } from '@/types/desk'
import * as deskApi from '@/api/desk'

vi.mock('@/stores/market', () => ({
  useMarketStore: () => ({
    provider: 'panda-test',
    quotes: [],
    quotesMap: new Map(),
    bars: [],
    overview: null,
    startPolling: vi.fn(),
    stopPolling: vi.fn(),
    checkHealth: vi.fn(),
  }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { display_name: 'Tester', base_currency: 'CNY', region: 'CN', email: 't@test.cn' },
    updateProfile: vi.fn(),
  }),
}))

vi.mock('@/api', () => ({
  profileApi: { latest: vi.fn().mockRejectedValue({ status: 404 }) },
}))

vi.mock('@/api/desk', () => ({
  fetchWatchlists: vi.fn().mockResolvedValue([]),
  createWatchlistGroup: vi.fn(),
  addWatchlistInstrument: vi.fn(),
  fetchNotificationPreferences: vi.fn().mockResolvedValue({ category_preferences: {} }),
  updateNotificationPreferences: vi.fn(),
  fetchCurrentMandate: vi.fn(),
  fetchMandateHistory: vi.fn(),
  saveMandate: vi.fn(),
  pauseMandate: vi.fn(),
  resumeMandate: vi.fn(),
  revokeMandate: vi.fn(),
  fetchMandateImpact: vi.fn(),
  newIdempotencyKey: vi.fn().mockReturnValue('mandate-save:key'),
}))

function mandate(overrides: Partial<InvestmentMandate> = {}): InvestmentMandate {
  return {
    mandate_id: 'mandate-1',
    owner_user_id: 'owner-1',
    version: 1,
    status: 'active',
    autonomy_level: 'L0',
    allowed_markets: ['CN', 'HK', 'US'],
    allowed_assets: ['stock', 'etf'],
    allowed_sides: ['buy', 'sell'],
    allowed_order_types: ['limit', 'market'],
    short_markets: [],
    limits: {
      max_single_order_amount: '1000000',
      max_daily_turnover_amount: '5000000',
      max_single_asset_ratio: '1',
      max_broad_etf_ratio: '1',
      max_otc_fund_ratio: '1',
      max_industry_ratio: '1',
      max_gross_ratio: '1',
      max_short_gross_ratio: '1',
      max_single_short_ratio: '1',
      max_price_deviation_ratio: '1',
      max_all_in_cost_ratio: '1',
      max_slippage_bps: '100',
    },
    valid_from: '2026-07-24T00:00:00Z',
    valid_until: '2027-07-24T00:00:00Z',
    created_at: '2026-07-24T00:00:00Z',
    created_by: 'owner-1',
    note: null,
    ...overrides,
  }
}

function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
  })
  return mount(SettingsView, { global: { plugins: [createPinia(), router] } })
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.mocked(deskApi.fetchCurrentMandate).mockResolvedValue(mandate())
  vi.mocked(deskApi.fetchMandateHistory).mockResolvedValue([mandate()])
  vi.mocked(deskApi.fetchMandateImpact).mockResolvedValue({ evaluated: 0, affected: [] })
  vi.mocked(deskApi.newIdempotencyKey).mockReturnValue('mandate-save:key')
})

describe('SettingsView 交易授权分区', () => {
  it('渲染当前授权摘要并标注为仿真业务数据', async () => {
    const wrapper = mountView()
    await flushPromises()
    await wrapper.get('.settings-nav-item:nth-child(2)').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('交易授权')
    expect(wrapper.text()).toContain('仿真业务数据')
    expect(wrapper.text()).toContain('生效中')
    expect(wrapper.text()).toContain('L0')
  })

  it('暂停授权调用后端并刷新为新版本状态', async () => {
    vi.mocked(deskApi.pauseMandate).mockResolvedValue(mandate({ version: 2, status: 'paused' }))
    const wrapper = mountView()
    await flushPromises()
    await wrapper.get('.settings-nav-item:nth-child(2)').trigger('click')
    await flushPromises()

    const pause = wrapper.findAll('button').find((b) => b.text() === '暂停授权')
    expect(pause).toBeTruthy()
    await pause!.trigger('click')
    await flushPromises()

    expect(deskApi.pauseMandate).toHaveBeenCalledWith(1)
    expect(wrapper.text()).toContain('已暂停')
  })

  it('保存新版本时携带幂等键并回传乐观并发版本号', async () => {
    vi.mocked(deskApi.saveMandate).mockResolvedValue(mandate({ version: 2 }))
    const wrapper = mountView()
    await flushPromises()
    await wrapper.get('.settings-nav-item:nth-child(2)').trigger('click')
    await flushPromises()

    await wrapper.get('input[inputmode="decimal"]').setValue('500000')
    const forms = wrapper.findAll('form')
    const editor = forms.find((f) => f.find('input[inputmode="decimal"]').exists())
    await editor!.trigger('submit')
    await flushPromises()

    expect(deskApi.saveMandate).toHaveBeenCalledTimes(1)
    const [payload, key] = vi.mocked(deskApi.saveMandate).mock.calls[0]
    expect(payload.expected_revision).toBe(1)
    expect(payload.limits.max_single_order_amount).toBe('500000')
    expect(key).toBe('mandate-save:key')
  })
})
