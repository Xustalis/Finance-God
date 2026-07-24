import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '@/App.vue'
import { createAppRouter } from '@/router'
import TradingDeskView from '@/views/TradingDeskView.vue'
import TradingWorkspace from '@/components/desk/TradingWorkspace.vue'
import * as tradingDeskApi from '@/services/tradingDesk'
import { DESK_LAYOUT_STORAGE_KEY } from '@/composables/useDeskLayoutPreference'

vi.mock('@/services/tradingDesk', () => ({
  fetchMarketOverview: vi.fn().mockResolvedValue([]),
  fetchProfile: vi.fn().mockRejectedValue(new Error('画像不可用')),
  fetchNotifications: vi.fn().mockResolvedValue([]),
  fetchInformationFacts: vi.fn().mockRejectedValue(new Error('市场资讯不可用')),
  fetchSentimentFacts: vi.fn().mockRejectedValue(new Error('市场情绪不可用')),
  markNotificationRead: vi.fn(),
  createWorkflow: vi.fn(),
  fetchWorkflow: vi.fn(),
  fetchSimulationAccount: vi.fn().mockRejectedValue(new Error('账户不存在')),
  fetchSimulationPortfolio: vi.fn().mockResolvedValue({ positions: [] }),
  fetchSimulationOrders: vi.fn().mockResolvedValue([]),
  fetchSimulationFills: vi.fn().mockResolvedValue([]),
  fetchWatchlistGroups: vi.fn().mockResolvedValue([]),
  fetchWatchlistInstruments: vi.fn().mockResolvedValue([]),
  fetchResearchCandidates: vi.fn().mockResolvedValue({ candidates: [] }),
  createSimulationAccount: vi.fn(),
  createSimulationDraft: vi.fn(),
  reviewSimulationDraft: vi.fn(),
  confirmSimulationSoftRisk: vi.fn(),
  confirmSimulationDraft: vi.fn(),
  submitSimulationDraft: vi.fn(),
  createWatchlistGroup: vi.fn(),
  updateWatchlistGroup: vi.fn(),
  deleteWatchlistGroup: vi.fn(),
  addWatchlistInstrument: vi.fn(),
  removeWatchlistInstrument: vi.fn(),
  ignoreResearchCandidate: vi.fn(),
  unignoreResearchCandidate: vi.fn(),
  createTradePlanFromCandidate: vi.fn(),
  createTradePlanFromPortfolioDeviation: vi.fn(),
  fetchTradePlan: vi.fn(),
  reviseTradePlan: vi.fn(),
  confirmTradePlan: vi.fn(),
}))

beforeEach(() => {
  localStorage.clear()
  vi.mocked(tradingDeskApi.fetchMarketOverview).mockResolvedValue([])
  vi.mocked(tradingDeskApi.fetchProfile).mockRejectedValue(new Error('画像不可用'))
  vi.mocked(tradingDeskApi.fetchNotifications).mockResolvedValue([])
  vi.mocked(tradingDeskApi.fetchInformationFacts).mockRejectedValue(new Error('市场资讯不可用'))
  vi.mocked(tradingDeskApi.fetchSentimentFacts).mockRejectedValue(new Error('市场情绪不可用'))
  vi.mocked(tradingDeskApi.fetchSimulationAccount).mockResolvedValue(null)
  vi.mocked(tradingDeskApi.fetchSimulationPortfolio).mockResolvedValue({ account_id: '', owner_id: '', as_of: '', rule_version: '', positions: [], realized_pnl_rmb: '0' })
  vi.mocked(tradingDeskApi.fetchSimulationOrders).mockResolvedValue([])
  vi.mocked(tradingDeskApi.fetchSimulationFills).mockResolvedValue([])
})

const LEGACY_TRADING_PATHS = [
  '/markets', '/watchlist', '/desk', '/overview', '/portfolio', '/trade-plans/plan-1',
  '/orders', '/reviews', '/data', '/data/evidence/evidence-1', '/settings',
]

function authenticate() {
  localStorage.setItem('finance-god-token', 'token')
  localStorage.setItem('finance-god-user', JSON.stringify({ id: 'user-1', role: 'user' }))
}

describe('trading workspace routing', () => {
  it('redirects every legacy trading URL to the protected desk', async () => {
    authenticate()
    const router = createAppRouter(createMemoryHistory())
    for (const path of LEGACY_TRADING_PATHS) {
      await router.push(path)
      await router.isReady()
      expect(router.currentRoute.value.path).toBe('/desk')
    }
  })

  it('does not expose the desk to unauthenticated users', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/desk')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query.redirect).toBe('/desk')
  })

  it('renders the formal trading desk with a persistent Agent panel', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/desk', component: TradingDeskView },
        { path: '/app/profile-report', component: { template: '<main>画像报告</main>' } },
      ],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('AI AGENT')
    expect(wrapper.find('[aria-label="交易 Agent"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="交易台工作区"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="交易台工作区"]').text()).toContain('总览')
    expect(wrapper.find('[aria-label="打开提醒"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('FINANCE GOD')
    expect(wrapper.text()).toContain('金融教父 · 投研与决策档案')
    await wrapper.get('[aria-label="打开我的"]').trigger('click')
    expect(wrapper.find('[aria-label="我的"]').text()).toContain('钱包')
    expect(wrapper.find('[aria-label="我的"]').text()).toContain('交易记录')
  })

  it('mounts all four workspaces and preserves explicit empty states', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(TradingDeskView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    const workspaceNav = wrapper.find('[aria-label="交易台工作区"]')
    const buttons = workspaceNav.findAll('button')
    expect(buttons).toHaveLength(4)
    await buttons[1].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('建立仿真账户')
    await buttons[2].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('自选分组')
    expect(wrapper.text()).toContain('可研究候选')
    await buttons[3].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('尚未建立仿真账户')
  })

  it('loads the simulation wallet, orders, and fills from service facts', async () => {
    vi.mocked(tradingDeskApi.fetchSimulationAccount).mockResolvedValue({
      account_id: 'account-1',
      owner_id: 'user-1',
      status: 'active',
      cash_total_rmb: '100000.00',
      cash_available_rmb: '87500.00',
      cash_frozen_rmb: '12500.00',
      margin_rmb: '0.00',
      revision: 3,
    })
    vi.mocked(tradingDeskApi.fetchSimulationOrders).mockResolvedValue([{
      order_id: 'order-1',
      owner_id: 'user-1',
      order_kind: 'exchange',
      status: 'filled',
      instrument_id: '000001.SZ',
      side: 'buy',
      order_type: 'limit',
      time_in_force: 'day',
      limit_price: '11.13',
      quantity: '100',
      cumulative_filled: '100',
      remaining_quantity: '0',
      average_fill_price: '11.12',
      total_fee_rmb: '1.12',
      filled_notional_rmb: '1112.00',
      revision: 2,
      confirmed_at: '2026-07-25T01:00:00Z',
      updated_at: '2026-07-25T01:00:03Z',
      execution_error: null,
      fills: [],
    }])
    vi.mocked(tradingDeskApi.fetchSimulationFills).mockResolvedValue([{
      fill_id: 'fill-1',
      order_id: 'order-1',
      account_id: 'account-1',
      instrument_id: '000001.SZ',
      side: 'buy',
      quantity: '100',
      price: '11.12',
      fee: '1.12',
      slippage_bps: '0',
      model_version: 'simulation-v1',
      rule_version: 'simulation-rules-v1',
      occurred_at: '2026-07-25T01:00:02Z',
      ledger_fill_id: 'ledger-fill-1',
    }])

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/desk', component: TradingDeskView },
        { path: '/app/profile-report', component: { template: '<main>画像报告</main>' } },
      ],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    await wrapper.get('[aria-label="打开我的"]').trigger('click')
    await wrapper.get('[aria-label="我的内容"] button:nth-child(2)').trigger('click')
    await flushPromises()
    expect(tradingDeskApi.fetchSimulationAccount).toHaveBeenCalled()
    expect(wrapper.get('[data-test="my-wallet"]').text()).toContain('¥100,000.00')
    expect(wrapper.get('[data-test="my-wallet"]').text()).toContain('¥12,500.00')

    await wrapper.get('[aria-label="我的内容"] button:nth-child(3)').trigger('click')
    await flushPromises()
    const history = wrapper.get('[data-test="my-history"]').text()
    expect(tradingDeskApi.fetchSimulationOrders).toHaveBeenCalled()
    expect(tradingDeskApi.fetchSimulationFills).toHaveBeenCalled()
    expect(history).toContain('000001.SZ')
    expect(history).toContain('全部成交')
    expect(history).toContain('11.12')
  })

  it('keeps a visible Agent rail and restores layout preferences after remount', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    await wrapper.get('[aria-label="收起交易 Agent"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[aria-label="展开交易 Agent"]').text()).toContain('AI AGENT')
    expect(JSON.parse(localStorage.getItem(DESK_LAYOUT_STORAGE_KEY) ?? '{}')).toMatchObject({ agentCollapsed: true })
    wrapper.unmount()

    const restored = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    expect(restored.find('[aria-label="展开交易 Agent"]').exists()).toBe(true)
  })

  it('supports keyboard resizing and persisted workspace tab ordering', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    await wrapper.get('[role="separator"]').trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.get('[role="separator"]').attributes('aria-valuenow')).toBe('52')

    await wrapper.get('.layout-menu > summary').trigger('click')
    await wrapper.get('[aria-label="持仓左移"]').trigger('click')
    const labels = wrapper.findAll('[aria-label="交易台工作区"] button').map((button) => button.text())
    expect(labels).toEqual(['持仓', '总览', '自选', '交易'])
    expect(JSON.parse(localStorage.getItem(DESK_LAYOUT_STORAGE_KEY) ?? '{}')).toMatchObject({
      agentWidthPercent: 52,
      tabOrder: ['portfolio', 'information', 'watchlist', 'trading'],
    })
  })

  it('requires soft-risk acknowledgement before exposing order-summary confirmation', () => {
    const wrapper = mount(TradingWorkspace, {
      props: {
        account: { account_id: 'account-1', cash_available_rmb: '100000' }, selectedSymbol: '000001.SZ', receipt: null,
        loading: false, error: null, onLoad: vi.fn(), onCreateDraft: vi.fn(), onReviewDraft: vi.fn(),
        onConfirmSoftRisk: vi.fn(), onConfirmDraft: vi.fn(), onSubmitDraft: vi.fn(),
        draft: {
          record_revision: 2,
          draft: { draft_id: 'draft-1', status: 'pending_review', instrument_id: '000001.SZ', side: 'buy', order_type: 'market', quantity: '100', limit_price: null },
          risk_result: { status: 'confirmation_required', reason_hash: 'a'.repeat(64), reasons: [{ code: 'market_volatility', severity: 'soft', message: '市场波动较大' }], soft_confirmation: null },
          immutable_summary_hash: 'b'.repeat(64), confirmed_at: null,
        },
      },
    })
    expect(wrapper.text()).toContain('确认已知风险')
    expect(wrapper.text()).not.toContain('确认订单摘要')
    expect(wrapper.text()).toContain('市场波动较大（market_volatility）')
  })
})
