import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import DeskView from '@/views/DeskView.vue'
import PortfolioView from '@/views/PortfolioView.vue'
import { profileApi } from '@/api'
import {
  confirmOrderDraft,
  createOrderDraft,
  createSimulationAccount,
  fetchBars,
  fetchCurrentAccount,
  fetchHealth,
  fetchNotificationPreferences,
  fetchOrders,
  fetchQuotes,
  fetchWatchlists,
  isDeskApiError,
  newIdempotencyKey,
  reviewOrderDraft,
  submitOrderDraft,
} from '@/api/desk'
import type { StoredDraft } from '@/types/desk'
import { symbolsForDirection } from '@/services/directionDesk'

const quote = {
  symbol: '000001.SZ',
  name: '平安银行',
  asset_type: 'equity',
  market: 'CN',
  currency: 'CNY',
  last: 10,
  open: 9.8,
  high: 10.2,
  low: 9.7,
  previous_close: 9.9,
  change: 0.1,
  change_percent: 0.01,
  volume: 1000,
  amount: 10000,
  provider: 'PandaData',
  provider_time: '2026-07-24T08:00:00Z',
  retrieved_at: '2026-07-24T08:00:01Z',
  frequency: 'snapshot',
  freshness: 'current',
  market_status: 'released',
  source_endpoint: 'snapshot',
  capability_version: 'v1',
  instrument_master_identity: '000001.SZ',
  instrument_master_version: 'v1',
  trade_eligible: false,
}

const account = {
  account_id: 'account-1',
  owner_id: 'user-1',
  status: 'active',
  cash_total_rmb: 100000,
  cash_available_rmb: 100000,
  cash_frozen_rmb: 0,
  margin_rmb: 0,
  revision: 1,
}

const draft: StoredDraft = {
  record_revision: 1,
  owner_id: 'user-1',
  mode: 'manual',
  draft: {
    draft_id: 'draft-1',
    revision: 1,
    status: 'draft',
    account_id: 'account-1',
    instrument_id: '000001.SZ',
    side: 'buy',
    order_type: 'market',
    quantity: 100,
    amount: null,
    limit_price: null,
    time_in_force: 'day',
    fund_rule_version: null,
    valid_until: '2026-07-24T09:00:00Z',
    input_versions: [],
    audit_reference: {
      audit_id: 'audit-1',
      actor_id: 'user-1',
      recorded_at: '2026-07-24T08:00:00Z',
    },
  },
  plan_reference: null,
  review: null,
  risk_result: null,
  immutable_summary_hash: null,
  confirmed_at: null,
  reference_price: null,
  cost_estimate: null,
}

const reviewed: StoredDraft = {
  ...draft,
  record_revision: 2,
  draft: { ...draft.draft, status: 'pending_review' },
  review: { succeeded: true, summary: 'reviewed', error: null },
  risk_result: {
    risk_check_id: 'risk-1',
    revision: 1,
    status: 'passed',
    order_version: { object_type: 'order_draft', object_id: 'draft-1', version: '1' },
    rule_version: { object_type: 'risk_rules', object_id: 'simulation-risk-v1', version: '1' },
    reasons: [],
    reason_hash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    checked_at: '2026-07-24T08:00:00Z',
    expires_at: '2026-07-24T08:30:00Z',
    soft_confirmation: null,
    input_versions: [],
    audit_reference: {
      audit_id: 'audit-2',
      actor_id: 'risk',
      recorded_at: '2026-07-24T08:00:00Z',
    },
  },
  immutable_summary_hash: 'a'.repeat(64),
}

vi.mock('@/api/desk', () => ({
  fetchQuotes: vi.fn(),
  fetchBars: vi.fn(),
  fetchHealth: vi.fn(),
  fetchCurrentAccount: vi.fn(),
  createSimulationAccount: vi.fn(),
  resetSimulationAccount: vi.fn(),
  fetchOrders: vi.fn().mockResolvedValue([]),
  fetchPortfolio: vi.fn().mockResolvedValue(null),
  fetchFills: vi.fn().mockResolvedValue([]),
  createOrderDraft: vi.fn(),
  reviewOrderDraft: vi.fn(),
  confirmSoftRisk: vi.fn(),
  confirmOrderDraft: vi.fn(),
  submitOrderDraft: vi.fn(),
  isDeskApiError: vi.fn((error: unknown, status?: number) => (
    error instanceof Error
    && 'status' in error
    && (status === undefined || (error as Error & { status: number }).status === status)
  )),
  newIdempotencyKey: vi.fn((scope: string) => `${scope}:test-key`),
  fetchWatchlists: vi.fn().mockResolvedValue([]),
  createWatchlistGroup: vi.fn(),
  addWatchlistInstrument: vi.fn(),
  fetchNotificationPreferences: vi.fn().mockResolvedValue({ category_preferences: {} }),
  updateNotificationPreferences: vi.fn(),
}))

vi.mock('@/api', () => ({
  profileApi: {
    latest: vi.fn().mockRejectedValue(Object.assign(new Error('no profile'), { status: 404 })),
    select: vi.fn(),
  },
}))

const layoutStub = {
  template: '<div><slot name="left" /><slot name="main" /><slot name="right" /></div>',
}

async function mountView(component: object, path = '/desk') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/desk', component: { template: '<div />' } },
      { path: '/settings', component: { template: '<div />' } },
      { path: '/portfolio', component: { template: '<div />' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  return mount(component, {
    global: {
      plugins: [createPinia(), router],
      stubs: {
        DeskLayout: layoutStub,
        MarketTable: true,
        MarketChart: true,
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
}

function prepareCommonMocks() {
  vi.mocked(fetchQuotes).mockResolvedValue({ quotes: [quote], errors: {} } as never)
  vi.mocked(fetchBars).mockResolvedValue({ symbol: quote.symbol, frequency: 'day', bars: [] } as never)
  vi.mocked(fetchHealth).mockResolvedValue({ market_data: 'PandaData', readiness: 'ready' } as never)
  vi.mocked(fetchOrders).mockResolvedValue([])
  vi.mocked(fetchWatchlists).mockResolvedValue([])
  vi.mocked(fetchNotificationPreferences).mockResolvedValue({
    owner_user_id: 'user-1',
    category_preferences: {},
    updated_at: '2026-07-24T08:00:00Z',
  })
  vi.mocked(profileApi.latest).mockRejectedValue(
    Object.assign(new Error('no profile'), { status: 404 }),
  )
  vi.mocked(isDeskApiError).mockImplementation((error: unknown, status?: number) => (
    error instanceof Error
    && 'status' in error
    && (status === undefined || (error as Error & { status: number }).status === status)
  ))
  vi.mocked(newIdempotencyKey).mockImplementation((scope: string) => `${scope}:test-key`)
}

describe('simulation account initialization', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    prepareCommonMocks()
    vi.mocked(fetchCurrentAccount).mockRejectedValue(
      Object.assign(new Error('simulation account not found'), { status: 404 }),
    )
    vi.mocked(createSimulationAccount).mockResolvedValue(account)
  })

  it('shows an explicit initialization action and then renders the server account', async () => {
    const wrapper = await mountView(PortfolioView, '/portfolio')
    await flushPromises()

    expect(wrapper.text()).toContain('尚未初始化仿真账户')
    await wrapper.get('[data-test="initial-cash"]').setValue('100000')
    await wrapper.get('[data-test="account-initialization-form"]').trigger('submit')
    await flushPromises()

    expect(createSimulationAccount).toHaveBeenCalledWith(100000, expect.any(String))
    expect(wrapper.text()).toContain('account-1')
    wrapper.unmount()
  })
})

describe('draft review confirmation and submission', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    prepareCommonMocks()
    vi.mocked(fetchCurrentAccount).mockResolvedValue(account)
    vi.mocked(createOrderDraft).mockResolvedValue(draft)
    vi.mocked(reviewOrderDraft).mockResolvedValue(reviewed)
    vi.mocked(confirmOrderDraft).mockResolvedValue({
      ...reviewed,
      record_revision: 3,
      draft: { ...reviewed.draft, status: 'confirmed' },
      confirmed_at: '2026-07-24T08:02:00Z',
    })
    vi.mocked(submitOrderDraft).mockResolvedValue({
      owner_id: 'user-1',
      draft_reference: { object_type: 'order_draft', object_id: 'draft-1', version: '1' },
      exchange_order: {
        order_id: 'order-1',
        revision: 1,
        status: 'submitting',
        idempotency_key: 'submit:test-key',
        draft_reference: { object_type: 'order_draft', object_id: 'draft-1', version: '1' },
        quantity: 100,
        cumulative_filled: 0,
        audit_reference: {
          audit_id: 'audit-order-1',
          actor_id: 'user-1',
          recorded_at: '2026-07-24T08:02:00Z',
        },
      },
      fund_order: null,
      execution_error: null,
    })
  })

  it('applies the selected investment direction from the route query to the desk universe', async () => {
    const fundQuote = { ...quote, symbol: '600519.SH', name: '贵州茅台', asset_type: 'equity' }
    vi.mocked(fetchQuotes).mockResolvedValue({ quotes: [fundQuote], errors: {} } as never)
    vi.mocked(fetchBars).mockResolvedValue({ symbol: '600519.SH', frequency: 'day', bars: [] } as never)
    const wrapper = await mountView(DeskView, '/desk?direction=public_funds')
    await flushPromises()

    expect(wrapper.get('[data-test="desk-direction"]').text()).toContain('百川谱')
    expect(wrapper.get('[data-test="direction-scope"]').text()).toContain('公募基金')
    expect(fetchQuotes).toHaveBeenCalledWith(symbolsForDirection('public_funds'))
    expect(fetchBars).toHaveBeenCalledWith('600519.SH', expect.anything())
    wrapper.unmount()
  })

  it('keeps each server transition explicit and uses one submit idempotency key', async () => {
    const wrapper = await mountView(DeskView)
    await flushPromises()
    expect(wrapper.text()).toContain('account-1')
    expect(wrapper.text()).toContain('000001.SZ')
    await wrapper.get('[data-test="order-quantity"]').setValue('100')
    expect(wrapper.get('[data-test="create-review-draft"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-test="order-ticket-form"]').trigger('submit')
    await flushPromises()

    expect(createOrderDraft).toHaveBeenCalledOnce()
    expect(reviewOrderDraft).toHaveBeenCalledWith('draft-1', 1)
    expect(wrapper.text()).toContain('风险复核通过')

    await wrapper.get('[data-test="summary-acknowledgement"]').setValue(true)
    await wrapper.get('[data-test="confirm-draft"]').trigger('click')
    await flushPromises()
    expect(confirmOrderDraft).toHaveBeenCalledWith('draft-1', 2, 'a'.repeat(64))
    expect(wrapper.text()).toContain('草稿已确认')

    await wrapper.get('[data-test="submit-draft"]').trigger('click')
    await flushPromises()
    expect(submitOrderDraft).toHaveBeenCalledWith('draft-1', expect.any(String))
    expect(wrapper.text()).toContain('order-1')
    expect(wrapper.find('[data-test="submit-draft"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
