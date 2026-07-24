import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import OrdersView from '@/views/OrdersView.vue'
import PortfolioView from '@/views/PortfolioView.vue'
import ReviewsView from '@/views/ReviewsView.vue'
import { fetchCurrentAccount, fetchFills, fetchOrders, fetchPortfolio } from '@/api/desk'
import type { PortfolioView as PortfolioViewData, SimulationFill, StoredOrderView } from '@/types/desk'

const market = vi.hoisted(() => ({
  quotesMap: new Map<string, { last: number }>(),
  quotesError: null as string | null,
  quoteErrors: {} as Record<string, string>,
  isStale: false,
  startPolling: vi.fn(),
  stopPolling: vi.fn(),
  checkHealth: vi.fn(),
  setWatchSymbols: vi.fn(),
}))

vi.mock('@/stores/market', () => ({
  useMarketStore: () => market,
}))

vi.mock('@/api/desk', () => ({
  fetchCurrentAccount: vi.fn(),
  fetchOrders: vi.fn(),
  fetchFills: vi.fn(),
  fetchPortfolio: vi.fn(),
  cancelOrder: vi.fn(),
  reconcileOrder: vi.fn(),
  createSimulationAccount: vi.fn(),
  resetSimulationAccount: vi.fn(),
  newIdempotencyKey: vi.fn((scope: string) => `${scope}:test-key`),
  isDeskApiError: vi.fn((error: unknown, status?: number) => (
    error instanceof Error
    && 'status' in error
    && (status === undefined || (error as Error & { status: number }).status === status)
  )),
}))

vi.mock('@/components/desk/DeskLayout.vue', () => ({
  default: {
    template: '<div><aside><slot name="left" /></aside><main><slot name="main" /></main><aside><slot name="right" /></aside></div>',
  },
}))

const account = {
  account_id: 'account-1',
  owner_id: 'user-1',
  status: 'active',
  cash_total_rmb: 100_000,
  cash_available_rmb: 90_000,
  cash_frozen_rmb: 10_000,
  margin_rmb: 0,
  revision: 1,
}

const orderView = {
  order_id: 'order-1',
  owner_id: 'user-1',
  order_kind: 'exchange',
  status: 'accepted',
  instrument_id: '000001.SZ',
  side: 'buy',
  order_type: 'limit',
  time_in_force: 'day',
  limit_price: 10,
  quantity: 100,
  cumulative_filled: 0,
  remaining_quantity: 100,
  average_fill_price: null,
  total_fee_rmb: 0,
  filled_notional_rmb: 0,
  revision: 1,
  confirmed_at: '2026-07-24T10:00:00+08:00',
  updated_at: '2026-07-24T10:00:00+08:00',
  draft_reference: { object_type: 'order_draft', object_id: 'draft-1', version: '1' },
  execution_error: null,
  fills: [],
  timeline: [
    { status: 'accepted', occurred_at: '2026-07-24T10:00:00+08:00', actor_id: 'user-1', detail: null },
  ],
} satisfies StoredOrderView

const fill = {
  fill_id: 'fill-1',
  order_id: 'order-1',
  account_id: 'account-1',
  instrument_id: '000001.SZ',
  side: 'buy',
  quantity: 100,
  price: 10,
  fee: 1,
  slippage_bps: 2,
  market_evidence: {
    object_type: 'market_data',
    object_id: '000001.SZ',
    version: '1',
  },
  model_version: 'simulation-matcher-v1',
  rule_version: 'simulation-rules-v1',
  occurred_at: '2026-07-24T10:01:00+08:00',
  ledger_fill_id: 'ledger-fill-1',
} satisfies SimulationFill

const portfolio = {
  account_id: 'account-1',
  owner_id: 'user-1',
  as_of: '2026-07-24T10:00:00+08:00',
  rule_version: 'simulation-rules-v1',
  realized_pnl_rmb: 0,
  positions: [
    {
      instrument_id: '000001.SZ',
      currency: 'CNY',
      quantity: 100,
      settled_quantity: 100,
      frozen_quantity: 0,
      available_quantity: 100,
      cost_basis_rmb: 1000,
      average_cost_rmb: 10,
      realized_pnl_rmb: 0,
      revision: 1,
    },
  ],
} satisfies PortfolioViewData

async function render(component: object) {
  const wrapper = mount(component, {
    global: {
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  market.quotesMap.clear()
  market.quotesError = null
  market.quoteErrors = {}
  market.isStale = false
  vi.mocked(fetchCurrentAccount).mockResolvedValue(account)
  vi.mocked(fetchOrders).mockResolvedValue([])
  vi.mocked(fetchFills).mockResolvedValue([])
  vi.mocked(fetchPortfolio).mockResolvedValue(portfolio)
})

describe('trading views expose partial request failures', () => {
  it('does not present an orders request failure as an empty order list', async () => {
    vi.mocked(fetchOrders).mockRejectedValue(new Error('orders offline'))

    const wrapper = await render(OrdersView)

    expect(wrapper.text()).toContain('订单数据加载失败')
    expect(wrapper.text()).toContain('orders offline')
    expect(wrapper.text()).not.toContain('暂无订单')
  })

  it('renders full order fields and has no nested buttons', async () => {
    vi.mocked(fetchOrders).mockResolvedValue([orderView])

    const wrapper = await render(OrdersView)

    expect(wrapper.text()).toContain('000001.SZ')
    expect(wrapper.text()).toContain('买入')
    expect(wrapper.find('button button').exists()).toBe(false)
  })

  it('marks positions unvalued when PandaData quotes are unavailable', async () => {
    vi.mocked(fetchPortfolio).mockResolvedValue(portfolio)
    vi.mocked(fetchOrders).mockResolvedValue([orderView])
    vi.mocked(fetchFills).mockResolvedValue([fill])

    const wrapper = await render(PortfolioView)

    expect(wrapper.text()).toContain('缺少 PandaData 行情')
    expect(wrapper.text()).toContain('暂不可估值')
    expect(wrapper.text()).toContain('部分持仓缺少行情')
  })

  it('keeps portfolio facts visible while identifying a failed orders request', async () => {
    vi.mocked(fetchPortfolio).mockResolvedValue(portfolio)
    vi.mocked(fetchOrders).mockRejectedValue(new Error('orders offline'))
    vi.mocked(fetchFills).mockResolvedValue([fill])
    market.quotesMap.set('000001.SZ', { last: 11 })

    const wrapper = await render(PortfolioView)

    expect(wrapper.text()).toContain('订单数据加载失败')
    expect(wrapper.text()).toContain('000001.SZ')
    expect(wrapper.text()).not.toContain('暂无持仓')
  })

  it('does not turn failed account and fills requests into an empty portfolio', async () => {
    vi.mocked(fetchPortfolio).mockResolvedValue(portfolio)
    vi.mocked(fetchCurrentAccount).mockRejectedValue(new Error('account offline'))
    vi.mocked(fetchFills).mockRejectedValue(new Error('fills offline'))

    const wrapper = await render(PortfolioView)

    expect(wrapper.text()).toContain('账户数据加载失败')
    expect(wrapper.text()).toContain('account offline')
    expect(wrapper.text()).toContain('成交数据加载失败')
    expect(wrapper.text()).toContain('fills offline')
    expect(wrapper.text()).not.toContain('暂无持仓')
  })

  it('shows fill failure instead of an empty review and never calculates PnL or win rate', async () => {
    vi.mocked(fetchOrders).mockRejectedValue(new Error('orders offline'))
    vi.mocked(fetchFills).mockResolvedValue([fill])

    const partial = await render(ReviewsView)

    expect(partial.text()).toContain('订单数据加载失败')
    expect(partial.text()).toContain('成交事实')
    expect(partial.text()).toContain('暂不可计算')
    expect(partial.text()).not.toContain('胜率 0%')
    expect(partial.text()).not.toContain('已实现盈亏 +0.00')

    vi.mocked(fetchFills).mockRejectedValue(new Error('fills offline'))
    const failed = await render(ReviewsView)

    expect(failed.text()).toContain('成交数据加载失败')
    expect(failed.text()).toContain('fills offline')
    expect(failed.text()).not.toContain('暂无成交记录')
  })
})
