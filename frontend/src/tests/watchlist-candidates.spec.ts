import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import WatchlistView from '@/views/WatchlistView.vue'
import type { Candidate, CandidateResponse, WatchlistGroup } from '@/types/desk'
import * as deskApi from '@/api/desk'

vi.mock('@/stores/market', () => ({
  useMarketStore: () => ({
    quotesMap: new Map(),
    provider: 'panda-test',
    startPolling: vi.fn(),
    stopPolling: vi.fn(),
    checkHealth: vi.fn(),
    loadBars: vi.fn(),
    setWatchSymbols: vi.fn(),
  }),
}))

vi.mock('@/api/desk', () => ({
  fetchWatchlists: vi.fn(),
  fetchWatchlistInstruments: vi.fn(),
  createWatchlistGroup: vi.fn(),
  updateWatchlistGroup: vi.fn(),
  deleteWatchlistGroup: vi.fn(),
  addWatchlistInstrument: vi.fn(),
  removeWatchlistInstrument: vi.fn(),
  fetchCandidates: vi.fn(),
  createCandidateTradePlan: vi.fn(),
  newIdempotencyKey: vi.fn(() => 'candidate-trade-plan-test'),
  ignoreCandidate: vi.fn(),
  unignoreCandidate: vi.fn(),
  searchInstruments: vi.fn(),
}))

function dims(overrides: Partial<Record<string, string>> = {}) {
  const base = {
    portfolio_fit: '组合适配',
    risk: '风险',
    cost: '成本',
    liquidity: '流动性',
    evidence: '证据完整度',
  }
  return Object.entries(base).map(([dimension, label]) => ({
    dimension: dimension as Candidate['dimensions'][number]['dimension'],
    label,
    rating: (overrides[dimension] ?? 'strong') as Candidate['dimensions'][number]['rating'],
    detail: `${label}说明`,
    metrics: {},
    missing_fields: overrides[dimension] === 'missing' ? [dimension] : [],
  }))
}

const tradable: Candidate = {
  instrument_id: '000001.SZ',
  symbol: '000001.SZ',
  name: '平安银行',
  asset_type: 'stock',
  market: 'SZ',
  currency: 'CNY',
  direction: 'equities',
  direction_label: '权益股票',
  purpose: '补充权益方向敞口',
  dimensions: dims(),
  exclusions: [],
  tradable: true,
  ignored: false,
  ignore_reason: null,
  as_of: '2026-07-24T10:00:00Z',
  provider: 'panda',
}

const insufficient: Candidate = {
  instrument_id: '600519.SH',
  symbol: '600519.SH',
  name: null,
  asset_type: null,
  market: null,
  currency: null,
  direction: 'equities',
  direction_label: '权益股票',
  purpose: '对齐权益方向，当前组合尚未覆盖',
  dimensions: dims({ risk: 'missing', liquidity: 'missing', evidence: 'missing' }),
  exclusions: [{ reason_code: 'data_insufficient', detail: '缺少实时行情，数据不足时不提供进入交易台入口。' }],
  tradable: false,
  ignored: false,
  ignore_reason: null,
  as_of: null,
  provider: null,
}

const candidateResponse: CandidateResponse = {
  generated_at: '2026-07-24T10:00:00Z',
  rule_version: 'sim-rules-v1',
  purpose_summary: '系统候选：待研究资产，非买入指令。',
  candidates: [tradable, insufficient],
  unavailable_reason: null,
}

const group: WatchlistGroup = {
  group_id: 'g1',
  owner_user_id: 'u1',
  name: '核心关注',
  description: null,
  revision: 1,
  created_at: '2026-07-24T09:00:00Z',
  updated_at: '2026-07-24T09:00:00Z',
}

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/watchlist', component: WatchlistView },
      { path: '/desk', component: { template: '<div />' } },
      { path: '/trade-plans/:planId', component: { template: '<div />' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  })
}

async function mountView() {
  const router = makeRouter()
  await router.push('/watchlist')
  await router.isReady()
  const wrapper = mount(WatchlistView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('WatchlistView 自选与候选', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    vi.mocked(deskApi.fetchWatchlists).mockResolvedValue([group])
    vi.mocked(deskApi.fetchWatchlistInstruments).mockResolvedValue([])
    vi.mocked(deskApi.fetchCandidates).mockResolvedValue(candidateResponse)
    vi.mocked(deskApi.createCandidateTradePlan).mockResolvedValue({
      object: {
        plan_id: 'plan-from-candidate',
      },
    } as Awaited<ReturnType<typeof deskApi.createCandidateTradePlan>>)
    vi.mocked(deskApi.ignoreCandidate).mockResolvedValue(undefined as never)
  })

  it('自选与系统候选为互斥 Tab，不并排为两张长表', async () => {
    const { wrapper } = await mountView()
    // 默认展示自选 Tab
    expect(wrapper.find('.group-bar').exists()).toBe(true)
    expect(wrapper.find('.candidate-list').exists()).toBe(false)

    const tabs = wrapper.findAll('[role="tab"]')
    await tabs[1].trigger('click')
    await flushPromises()
    // 切换到系统候选后，自选主表消失
    expect(wrapper.find('.candidate-list').exists()).toBe(true)
    expect(wrapper.find('.group-bar').exists()).toBe(false)
  })

  it('候选展示五维独立评分且无综合总分', async () => {
    const { wrapper } = await mountView()
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await flushPromises()

    const firstCard = wrapper.findAll('.candidate-card')[0]
    const badges = firstCard.findAll('.dim-row .rate-badge')
    expect(badges).toHaveLength(5)
    const text = firstCard.text()
    expect(text).toContain('组合适配')
    expect(text).toContain('风险')
    expect(text).toContain('证据完整度')
    // 不得出现单一综合/总分
    expect(text).not.toContain('综合分')
    expect(text).not.toContain('总分')
  })

  it('数据不足的候选禁用进入交易台入口并显式标注缺失', async () => {
    const { wrapper } = await mountView()
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await flushPromises()

    const cards = wrapper.findAll('.candidate-card')
    const insufficientCard = cards[1]
    const enterBtn = insufficientCard.find('.mini-btn.primary')
    expect(enterBtn.attributes('disabled')).toBeDefined()
    expect(insufficientCard.text()).toContain('排除')
  })

  it('比较托盘选 2 个候选后可进入全宽比较态', async () => {
    const { wrapper } = await mountView()
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await flushPromises()

    const cards = wrapper.findAll('.candidate-card')
    const compareButton = (card: (typeof cards)[number]) =>
      card.findAll('.mini-btn').find((button) => button.text().includes('加入比较'))!
    await compareButton(cards[0]).trigger('click')
    await compareButton(cards[1]).trigger('click')
    await flushPromises()

    const compareBtn = wrapper.find('.tray-actions .mini-btn.primary')
    expect(compareBtn.attributes('disabled')).toBeUndefined()
    await compareBtn.trigger('click')
    await flushPromises()

    expect(wrapper.find('.compare-view').exists()).toBe(true)
    expect(wrapper.find('.compare-table').text()).toContain('000001.SZ')
    expect(wrapper.find('.compare-table').text()).toContain('600519.SH')
  })

  it('忽略候选调用持久化接口且不删除证据', async () => {
    const { wrapper } = await mountView()
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await flushPromises()

    const card = wrapper.findAll('.candidate-card')[0]
    // 触发忽略表单
    const ignoreLink = card.findAll('.link-btn').find((b) => b.text() === '忽略')
    await ignoreLink!.trigger('click')
    await flushPromises()
    await card.find('.ignore-form').trigger('submit')
    await flushPromises()

    expect(deskApi.ignoreCandidate).toHaveBeenCalledWith('000001.SZ', 'not_now', undefined)
  })

  it('从可交易候选创建版本化交易计划并进入详情页', async () => {
    const { wrapper, router } = await mountView()
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    await flushPromises()

    const createButton = wrapper
      .findAll('.candidate-card .mini-btn.primary')
      .find((button) => button.text() === '创建交易计划' && button.attributes('disabled') === undefined)!
    await createButton.trigger('click')
    await flushPromises()

    expect(deskApi.createCandidateTradePlan).toHaveBeenCalledWith(
      '000001.SZ',
      expect.stringContaining('candidate-trade-plan'),
    )
    expect(router.currentRoute.value.path).toBe('/trade-plans/plan-from-candidate')
  })
})
