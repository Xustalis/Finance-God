import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '@/App.vue'
import { createAppRouter } from '@/router'
import TradingDeskView from '@/views/TradingDeskView.vue'
import OverviewWorkspace from '@/components/desk/OverviewWorkspace.vue'
import PortfolioWorkspace from '@/components/desk/PortfolioWorkspace.vue'
import TradingWorkspace from '@/components/desk/TradingWorkspace.vue'
import WatchlistWorkspace from '@/components/desk/WatchlistWorkspace.vue'
import * as tradingDeskApi from '@/services/tradingDesk'
import { useTradingDeskStore } from '@/stores/tradingDesk'

vi.mock('@/services/notificationStream', () => ({
  NotificationStreamError: class NotificationStreamError extends Error {},
  consumeNotificationStream: vi.fn(({ signal }: { signal: AbortSignal }) => (
    new Promise<void>((resolve) => {
      signal.addEventListener('abort', () => resolve(), { once: true })
    })
  )),
}))

vi.mock('@/services/tradingDesk', () => ({
  canUseQuoteAsDraftReference: vi.fn((quote: { last: number | null; freshness: string; market_status: string }) => (
    quote.last !== null
    && quote.last > 0
    && !['error', 'unavailable', 'missing'].includes(quote.freshness)
    && ['in_session', 'released'].includes(quote.market_status)
  )),
  draftReferenceBlockedReason: vi.fn(() => '真实行情不可用'),
  isDeskCapabilityEnabled: vi.fn((capabilities: Record<string, boolean> | null | undefined, key: string) => capabilities?.[key] === true),
  fetchMarketOverview: vi.fn().mockResolvedValue({ quotes: [], warnings: [] }),
  fetchBars: vi.fn().mockResolvedValue([]),
  fetchSimulationMarketOverview: vi.fn().mockResolvedValue({ quotes: [], warnings: [] }),
  fetchSimulationBars: vi.fn().mockResolvedValue([]),
  fetchDeskBootstrap: vi.fn(),
  fetchDeskQuickCommands: vi.fn(),
  previewDeskAgent: vi.fn(),
  fetchProfile: vi.fn().mockRejectedValue(new Error('画像不可用')),
  fetchNotifications: vi.fn().mockResolvedValue([]),
  fetchNotificationHistory: vi.fn().mockResolvedValue([]),
  fetchInformationFacts: vi.fn().mockRejectedValue(new Error('市场资讯不可用')),
  fetchSentimentFacts: vi.fn().mockRejectedValue(new Error('市场情绪不可用')),
  markNotificationRead: vi.fn(),
  streamDeskAgentDecision: vi.fn(),
  runDeskDirectAnswer: vi.fn(),
  createWorkflow: vi.fn(),
  fetchWorkflow: vi.fn(),
  fetchWorkflowProgress: vi.fn(),
  fetchWorkflowEvidence: vi.fn(),
  applyDeskUiAction: vi.fn(),
  fetchSimulationAccount: vi.fn().mockRejectedValue(new Error('账户不存在')),
  fetchSimulationPortfolio: vi.fn().mockResolvedValue({ positions: [] }),
  fetchSimulationOrders: vi.fn().mockResolvedValue([]),
  fetchSimulationFills: vi.fn().mockResolvedValue([]),
  fetchTradeEpisodes: vi.fn().mockResolvedValue([]),
  fetchTradeEpisodeDecisions: vi.fn().mockResolvedValue([]),
  fetchTradeEpisodeReview: vi.fn(),
  retryTradeEpisodeReview: vi.fn(),
  fetchAgentLearningSummary: vi.fn().mockResolvedValue({
    status: 'unavailable',
    message: '尚无学习周期',
    last_cycle: null,
    snapshot: null,
    recent_verified_lessons: [],
    freshness: { configured_interval_seconds: 900, age_seconds: null, is_stale: false },
  }),
  fetchWatchlistGroups: vi.fn().mockResolvedValue([]),
  fetchWatchlistInstruments: vi.fn().mockResolvedValue([]),
  fetchResearchCandidates: vi.fn().mockResolvedValue({ candidates: [] }),
  createSimulationAccount: vi.fn(),
  createSimulationDraft: vi.fn(),
  reviewSimulationDraft: vi.fn(),
  confirmSimulationSoftRisk: vi.fn(),
  confirmSimulationDraft: vi.fn(),
  submitSimulationDraft: vi.fn(),
  submitSimulationMarketOrder: vi.fn(),
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
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  vi.mocked(tradingDeskApi.fetchDeskBootstrap).mockImplementation(async (input) => ({
    owner_id: 'user-1',
    section: input?.section ?? 'information',
    symbol: input?.symbol ?? '000001.SZ',
    context_version: `desk:user-1:${input?.section ?? 'information'}:${input?.symbol ?? '000001.SZ'}:1`,
    profile_projection: {
      version: null,
      archetype_code: null,
      archetype_title: null,
      risk_level: null,
      loss_tolerance_percent: null,
      confidence: null,
      completeness: null,
      education_only: null,
      selected_direction: null,
      recommended_directions: [],
      projection_version: 'suitability-v1',
      available: false,
      degraded: false,
    },
    ui_action_catalog: [],
    capabilities: {
      workflow_create: true,
      workflow_worker: true,
      agent_answer: true,
      market_data: true,
      settings_excluded: true,
      ui_actions: true,
      order_submit: false,
    },
    generated_at: '2026-07-25T01:00:00Z',
  }))
  vi.mocked(tradingDeskApi.fetchDeskQuickCommands).mockResolvedValue({
    quick_commands: ['分析当前标的行情', '核查当前行情数据新鲜度', '研究当前公司基本面'],
    quick_commands_error: null,
    generated_at: '2026-07-25T01:00:08Z',
  })
  vi.mocked(tradingDeskApi.previewDeskAgent).mockImplementation(async (input) => (
    input.message.startsWith('什么是')
      ? {
          mode: 'answer',
          workflow_key: null,
          workflow_title: null,
          expected_roles: ['对话 Agent'],
          artifact_types: ['文字答复'],
          can_start: true,
        }
      : {
          mode: 'workflow',
          workflow_key: 'company_research',
          workflow_title: '公司研究',
          expected_roles: ['tradingagents:market_analyst'],
          artifact_types: ['ResearchMemo'],
          can_start: true,
        }
  ))
  vi.mocked(tradingDeskApi.fetchMarketOverview).mockResolvedValue({
    quotes: [],
    warnings: [],
  })
  vi.mocked(tradingDeskApi.fetchProfile).mockRejectedValue(new Error('画像不可用'))
  vi.mocked(tradingDeskApi.fetchNotifications).mockResolvedValue([])
  vi.mocked(tradingDeskApi.fetchInformationFacts).mockRejectedValue(new Error('市场资讯不可用'))
  vi.mocked(tradingDeskApi.fetchSentimentFacts).mockRejectedValue(new Error('市场情绪不可用'))
  vi.mocked(tradingDeskApi.fetchSimulationAccount).mockResolvedValue(null)
  vi.mocked(tradingDeskApi.fetchSimulationPortfolio).mockResolvedValue({ account_id: '', owner_id: '', as_of: '', rule_version: '', positions: [], realized_pnl_rmb: '0' })
  vi.mocked(tradingDeskApi.fetchSimulationOrders).mockResolvedValue([])
  vi.mocked(tradingDeskApi.fetchSimulationFills).mockResolvedValue([])
  vi.mocked(tradingDeskApi.fetchTradeEpisodes).mockResolvedValue([])
  vi.mocked(tradingDeskApi.streamDeskAgentDecision).mockImplementation(async (input) => ({
    decision_id: 'decision-test-workflow',
    decision_source: 'agent_generated_policy_approved',
    mode: 'workflow',
    message: '需要多阶段工作流。',
    workflow_key: input.message.includes('候选') ? 'research_candidates' : 'company_research',
    workflow_title: input.message.includes('候选') ? '研究候选' : '公司研究',
    routing_reason: '需要真实数据与多个研究角色交叉复核。',
    expected_stages: ['输入', '研究', '复核'],
    can_start: true,
    answer_text: null,
    ui_actions: [],
  }))
})

const LEGACY_TRADING_PATHS = [
  '/markets', '/watchlist', '/overview', '/portfolio', '/trade-plans/plan-1',
  '/orders', '/reviews', '/data', '/data/evidence/evidence-1', '/settings',
]

function authenticate() {
  localStorage.setItem('finance-god-token', 'token')
  localStorage.setItem('finance-god-user', JSON.stringify({ id: 'user-1', role: 'user' }))
}

describe('trading workspace routing', () => {
  it('restores the last local workspace hint before the first bootstrap request', async () => {
    authenticate()
    localStorage.setItem(
      'finance-god:desk-context:v1:user-1',
      JSON.stringify({ section: 'trading', symbol: '600519.SH' }),
    )
    const store = useTradingDeskStore(createPinia())

    await store.refreshBootstrap()

    expect(store.section).toBe('trading')
    expect(store.symbol).toBe('600519.SH')
    expect(tradingDeskApi.fetchDeskBootstrap).toHaveBeenCalledTimes(1)
    expect(tradingDeskApi.fetchDeskBootstrap).toHaveBeenCalledWith({
      section: 'trading',
      symbol: '600519.SH',
    })
  })

  it('persists only the page context hint and never server authorization facts', async () => {
    authenticate()
    const store = useTradingDeskStore(createPinia())

    store.setSection('watchlist')
    store.setSymbol('300750.SZ')
    await flushPromises()

    const saved = JSON.parse(
      localStorage.getItem('finance-god:desk-context:v1:user-1') || '{}',
    )
    expect(saved).toEqual({ section: 'watchlist', symbol: '300750.SZ' })
    expect(saved).not.toHaveProperty('context_version')
    expect(saved).not.toHaveProperty('capabilities')
    expect(saved).not.toHaveProperty('profile_projection')
    expect(saved).not.toHaveProperty('ui_action_catalog')
  })

  it('ignores an invalid local context hint', () => {
    authenticate()
    localStorage.setItem(
      'finance-god:desk-context:v1:user-1',
      JSON.stringify({ section: 'settings', symbol: '' }),
    )

    const store = useTradingDeskStore(createPinia())

    expect(store.section).toBe('information')
    expect(store.symbol).toBe('000001.SZ')
  })

  it('marks bootstrap ready before initial quick commands finish loading', async () => {
    let resolveCommands!: (value: Awaited<ReturnType<typeof tradingDeskApi.fetchDeskQuickCommands>>) => void
    vi.mocked(tradingDeskApi.fetchDeskQuickCommands).mockImplementation(() => new Promise((resolve) => {
      resolveCommands = resolve
    }))
    const store = useTradingDeskStore(createPinia())

    await store.refreshBootstrap()

    expect(store.bootstrapStatus).toBe('ready')
    expect(store.serverContextVersion).toBe('desk:user-1:information:000001.SZ:1')
    expect(store.quickCommandsLoading).toBe(true)
    expect(store.quickCommands).toEqual([])

    resolveCommands({
      quick_commands: ['指令一', '指令二', '指令三'],
      quick_commands_error: null,
      generated_at: '2026-07-25T01:00:08Z',
    })
    await flushPromises()

    expect(store.quickCommandsLoading).toBe(false)
    expect(store.quickCommands).toEqual(['指令一', '指令二', '指令三'])
  })

  it('keeps the synchronized context ready when initial quick commands fail', async () => {
    vi.mocked(tradingDeskApi.fetchDeskQuickCommands).mockRejectedValue(
      new Error('快捷指令服务不可用'),
    )
    const store = useTradingDeskStore(createPinia())

    await store.refreshBootstrap()
    await flushPromises()

    expect(store.bootstrapStatus).toBe('ready')
    expect(store.serverContextVersion).toBe('desk:user-1:information:000001.SZ:1')
    expect(store.quickCommandsError).toBe('快捷指令服务不可用')
  })

  it('invalidates the old audit context and ignores a late bootstrap failure after the context changes', async () => {
    const requests: Array<{
      resolve: (value: Awaited<ReturnType<typeof tradingDeskApi.fetchDeskBootstrap>>) => void
      reject: (reason: Error) => void
    }> = []
    vi.mocked(tradingDeskApi.fetchDeskBootstrap).mockImplementation(() => new Promise((resolve, reject) => {
      requests.push({ resolve, reject })
    }))
    const pinia = createPinia()
    const store = useTradingDeskStore(pinia)

    const firstRequest = store.refreshBootstrap()
    expect(store.bootstrapStatus).toBe('loading')
    expect(store.serverContextVersion).toBeNull()

    store.setSymbol('600519.SH')
    expect(requests).toHaveLength(2)
    requests[1].resolve({
      owner_id: 'user-1',
      section: 'information',
      symbol: '600519.SH',
      context_version: 'desk:user-1:information:600519.SH:2',
      profile_projection: {
        version: null,
        archetype_code: null,
        archetype_title: null,
        risk_level: null,
        loss_tolerance_percent: null,
        confidence: null,
        completeness: null,
        education_only: null,
        selected_direction: null,
        recommended_directions: [],
        projection_version: 'suitability-v1',
        available: false,
        degraded: false,
      },
      ui_action_catalog: [],
      capabilities: { agent_answer: true },
      generated_at: '2026-07-25T01:00:02Z',
    })
    await flushPromises()

    expect(store.bootstrapStatus).toBe('ready')
    expect(store.serverContextVersion).toBe('desk:user-1:information:600519.SH:2')

    requests[0].reject(new Error('旧请求失败'))
    await firstRequest
    expect(store.bootstrapStatus).toBe('ready')
    expect(store.bootstrapError).toBeNull()
    expect(store.serverContextVersion).toBe('desk:user-1:information:600519.SH:2')
  })

  it('applies approved Agent actions to the left trading workspace and blocks stale context', async () => {
    const pinia = createPinia()
    const store = useTradingDeskStore(pinia)
    store.serverContextVersion = 'desk:user-1:information:000001.SZ:1'
    store.uiActionCatalog = [
      { id: 'select_symbol', object: 'instrument', mutation: 'ui_only', descriptor_version: '1' },
      { id: 'navigate_trading', object: 'workspace', mutation: 'ui_only', descriptor_version: '1' },
      { id: 'fill_trade_draft', object: 'order_draft', mutation: 'ui_only', descriptor_version: '1' },
    ]
    vi.mocked(tradingDeskApi.applyDeskUiAction).mockImplementation(async (input) => ({
      receipt: 'applied',
      action_id: input.actionId,
      reason: null,
      owner_id: 'user-1',
      parameters: input.parameters ?? {},
      applied_at: '2026-07-25T01:00:00Z',
    }))

    const symbolReceipt = await store.applyUiAction('select_symbol', { symbol: '600519.SH' })
    expect(symbolReceipt.receipt).toBe('applied')
    expect(store.symbol).toBe('600519.SH')
    await flushPromises()
    store.uiActionCatalog = [
      { id: 'select_symbol', object: 'instrument', mutation: 'ui_only', descriptor_version: '1' },
      { id: 'navigate_trading', object: 'workspace', mutation: 'ui_only', descriptor_version: '1' },
      { id: 'fill_trade_draft', object: 'order_draft', mutation: 'ui_only', descriptor_version: '1' },
    ]

    await store.applyUiAction('navigate_trading')
    expect(store.section).toBe('trading')
    await flushPromises()
    store.uiActionCatalog = [
      { id: 'select_symbol', object: 'instrument', mutation: 'ui_only', descriptor_version: '1' },
      { id: 'navigate_trading', object: 'workspace', mutation: 'ui_only', descriptor_version: '1' },
      { id: 'fill_trade_draft', object: 'order_draft', mutation: 'ui_only', descriptor_version: '1' },
    ]

    await store.applyUiAction('fill_trade_draft', {
      side: 'buy',
      quantity: '100',
      price_type: 'limit',
      limit_price: '1500.00',
    }, store.serverContextVersion)
    expect(store.section).toBe('trading')
    expect(store.tradeDraftPrefill).toEqual({
      side: 'buy',
      quantity: '100',
      priceType: 'limit',
      limitPrice: '1500.00',
    })
    store.uiActionCatalog = [
      { id: 'select_symbol', object: 'instrument', mutation: 'ui_only', descriptor_version: '1' },
    ]

    const stale = await store.applyUiAction(
      'select_symbol',
      { symbol: '300750.SZ' },
      'desk:user-1:information:000001.SZ:stale',
    )
    expect(stale.receipt).toBe('stale_context')
    expect(store.symbol).toBe('600519.SH')
  })

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
    const agentHeading = wrapper.get('.agent-heading')
    expect(agentHeading.find('p').exists()).toBe(false)
    expect(agentHeading.text()).not.toContain('上下文 ·')
    expect(agentHeading.text()).not.toContain('重置布局')
    expect(agentHeading.find('[aria-label="收起交易 Agent"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="交易台工作区"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="调整工作区布局"]').exists()).toBe(false)
    expect(wrapper.find('[role="separator"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="交易台工作区"]').text()).toContain('总览')
    expect(wrapper.find('[aria-label="打开提醒"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('FINANCE GOD')
    expect(wrapper.text()).toContain('金融教父 · 投研与决策档案')
    expect(wrapper.find('.agent-ready').exists()).toBe(false)
    expect(wrapper.find('[aria-label="提交前任务上下文"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('本次提交依据')
    await wrapper.get('[aria-label="打开我的"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('[aria-label="我的"]').exists()).toBe(true))
    expect(wrapper.find('[aria-label="我的"]').text()).toContain('钱包')
    expect(wrapper.find('[aria-label="我的"]').text()).toContain('交易记录')
  })

  it('creates a server-routed workflow and renders persisted evidence', async () => {
    vi.mocked(tradingDeskApi.createWorkflow).mockResolvedValue({
      run_id: 'workflow-1',
      status: 'queued',
      workflow_key: 'company_research',
      workflow_version: 'finance-god-workflows-v2',
      revision: 1,
      final_artifact: null,
    })
    vi.mocked(tradingDeskApi.fetchWorkflow).mockResolvedValue({
      run_id: 'workflow-1',
      status: 'completed',
      workflow_key: 'company_research',
      workflow_version: 'finance-god-workflows-v2',
      revision: 8,
      final_artifact: {
        object_type: 'ResearchMemo',
        object_id: 'workflow-1',
        version: 'agent-run-1',
      },
    })
    vi.mocked(tradingDeskApi.fetchWorkflowProgress).mockResolvedValue({
      run_id: 'workflow-1',
      status: 'completed',
      workflow_key: 'company_research',
      workflow_version: 'finance-god-workflows-v2',
      revision: 8,
      updated_at: '2026-07-25T01:00:08Z',
      total_node_count: 4,
      completed_node_artifact_count: 4,
      completed_node_artifacts: [],
      errors: [],
      is_terminal: true,
    })
    vi.mocked(tradingDeskApi.fetchWorkflowEvidence).mockResolvedValue({
      object_type: 'ResearchMemo',
      object_id: 'workflow-1',
      version: 'agent-run-1',
      subject: '研究当前公司基本面',
      conclusion: '收入增长仍需核对最新披露。',
      provider: 'multi-agent-runtime',
      generated_at: '2026-07-25T01:00:07Z',
      facts: [],
      inferences: [{
        kind: 'inference',
        statement: '估值结论对利润率假设敏感。',
        author_agent_id: 'finrobot:equity:ValuationOverviewAgent',
        evidence_ids: ['input-1'],
        unknowns: [],
        invalidation_conditions: [],
      }],
      counterpoints: [],
      unknowns: ['最新季度利润率'],
      invalidation_conditions: [],
      sources: [{ identifier: 'input-1', source: 'instrument_context:000001.SZ', excerpt: '版本化输入' }],
      agent_nodes: [],
      notices: [],
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(TradingDeskView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    expect(wrapper.findAll('.quick-commands button')).toHaveLength(3)
    await wrapper.findAll('.quick-commands button')[2].trigger('click')
    await flushPromises()

    expect(tradingDeskApi.createWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      intent: '研究当前公司基本面',
      section: 'information',
      symbol: '000001.SZ',
      contextVersion: 'desk:user-1:information:000001.SZ:1',
    }))
    expect(tradingDeskApi.fetchWorkflowProgress).toHaveBeenCalledWith('workflow-1')
    expect(tradingDeskApi.fetchWorkflowEvidence).toHaveBeenCalledWith({
      object_type: 'ResearchMemo',
      object_id: 'workflow-1',
      version: 'agent-run-1',
    })
    expect(wrapper.get('[aria-label="工作流产物"]').text()).toContain('收入增长仍需核对最新披露')
    expect(wrapper.get('[aria-label="工作流产物"]').text()).toContain('最新季度利润率')
    expect(wrapper.text()).toContain('4 / 4 个节点产物')
    expect(tradingDeskApi.fetchDeskQuickCommands).toHaveBeenCalledWith({
      stage: 'after_workflow',
      section: 'information',
      symbol: '000001.SZ',
      contextVersion: 'desk:user-1:information:000001.SZ:1',
      runId: 'workflow-1',
    })
  })

  it('routes a simple question to one Agent without creating a workflow', async () => {
    vi.mocked(tradingDeskApi.streamDeskAgentDecision).mockImplementation(async (_input, onDelta) => {
      onDelta('市盈率通常表示')
      onDelta('股价相对于每股收益的倍数。')
      return {
        decision_id: 'decision-test-answer',
        decision_source: 'agent_generated_policy_approved',
        mode: 'answer',
        message: '这个问题可以直接回答。',
        workflow_key: null,
        workflow_title: null,
        routing_reason: '问题是概念说明，不依赖新的多源研究产物。',
        expected_stages: [],
        can_start: true,
        answer_text: '市盈率通常表示股价相对于每股收益的倍数。',
        ui_actions: [],
      }
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(TradingDeskView, {
      global: { plugins: [createPinia(), router] },
    })
    await flushPromises()

    await wrapper.get('textarea[aria-label="向交易 Agent 输入指令"]').setValue('什么是市盈率？')
    await wrapper.get('button[aria-label="发送给 Agent"]').trigger('submit')
    await flushPromises()

    expect(tradingDeskApi.streamDeskAgentDecision).toHaveBeenCalledOnce()
    expect(tradingDeskApi.createWorkflow).not.toHaveBeenCalled()
    expect(wrapper.get('[aria-label="用户消息"]').text()).toContain('什么是市盈率？')
    expect(wrapper.get('[aria-label="Agent 回复"]').text()).toContain(
      '市盈率通常表示股价相对于每股收益的倍数',
    )
    expect(wrapper.text()).not.toContain('Agent 执行判断')
    expect(wrapper.text()).not.toContain('问题是概念说明')
    expect(tradingDeskApi.fetchDeskQuickCommands).toHaveBeenCalledWith({
      stage: 'after_answer',
      section: 'information',
      symbol: '000001.SZ',
      contextVersion: 'desk:user-1:information:000001.SZ:1',
      decisionId: 'decision-test-answer',
    })
    expect(wrapper.findAll('.quick-commands button')).toHaveLength(3)
  })

  it('rerolls the current quick-command stage without bypassing Agent submit', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(TradingDeskView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    await wrapper.get('.quick-command-toolbar button').trigger('click')
    await flushPromises()

    expect(tradingDeskApi.fetchDeskQuickCommands).toHaveBeenCalledWith({
      stage: 'initial',
      section: 'information',
      symbol: '000001.SZ',
      contextVersion: 'desk:user-1:information:000001.SZ:1',
    })
    expect(tradingDeskApi.streamDeskAgentDecision).not.toHaveBeenCalled()
  })

  it('ignores late quick commands after the symbol context changes', async () => {
    let resolveLate!: (value: Awaited<ReturnType<typeof tradingDeskApi.fetchDeskQuickCommands>>) => void
    vi.mocked(tradingDeskApi.fetchDeskQuickCommands).mockImplementationOnce(() => new Promise((resolve) => {
      resolveLate = resolve
    }))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(TradingDeskView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    const store = useTradingDeskStore()

    const pending = store.rerollQuickCommands()
    store.setSymbol('600519.SH')
    await flushPromises()
    resolveLate({
      quick_commands: ['平安银行迟到建议一', '平安银行迟到建议二', '平安银行迟到建议三'],
      quick_commands_error: null,
      generated_at: '2026-07-25T01:00:09Z',
    })
    await pending
    await flushPromises()

    expect(store.symbol).toBe('600519.SH')
    expect(store.quickCommands).not.toContain('平安银行迟到建议一')
    expect(wrapper.text()).not.toContain('平安银行迟到建议一')
  })

  it('executes validated Agent UI actions before showing the direct reply', async () => {
    const contextVersion = 'desk:user-1:information:000001.SZ:1'
    vi.mocked(tradingDeskApi.fetchDeskBootstrap).mockImplementation(async (input) => ({
      owner_id: 'user-1',
      section: input?.section ?? 'information',
      symbol: input?.symbol ?? '000001.SZ',
      context_version: `desk:user-1:${input?.section ?? 'information'}:${input?.symbol ?? '000001.SZ'}:1`,
      profile_projection: {
        version: null, archetype_code: null, archetype_title: null, risk_level: null,
        loss_tolerance_percent: null, confidence: null, completeness: null,
        education_only: null, selected_direction: null, recommended_directions: [],
        projection_version: 'suitability-v1', available: false, degraded: false,
      },
      ui_action_catalog: [
        { id: 'select_symbol', object: 'instrument', mutation: 'ui_only', descriptor_version: '1' },
        { id: 'navigate_trading', object: 'workspace', mutation: 'ui_only', descriptor_version: '1' },
        { id: 'fill_trade_draft', object: 'order_draft', mutation: 'draft_only', descriptor_version: '1' },
      ],
      capabilities: { ui_actions: true, agent_answer: true },
      generated_at: '2026-07-25T01:00:00Z',
    }))
    vi.mocked(tradingDeskApi.applyDeskUiAction).mockImplementation(async (input) => ({
      receipt: 'applied',
      action_id: input.actionId,
      reason: null,
      owner_id: 'user-1',
      parameters: input.parameters ?? {},
      applied_at: '2026-07-25T01:00:01Z',
    }))
    vi.mocked(tradingDeskApi.streamDeskAgentDecision).mockResolvedValue({
      decision_id: 'decision-actions',
      decision_source: 'agent_generated_policy_approved',
      mode: 'answer',
      message: '可以直接执行界面动作。',
      workflow_key: null,
      workflow_title: null,
      routing_reason: '这是界面操作。',
      expected_stages: [],
      can_start: true,
      answer_text: '已为你打开贵州茅台并预填模拟买入草稿，请在交易区复核。',
      ui_actions: [
        { action_id: 'select_symbol', parameters: { symbol: '600519.SH' }, context_version: contextVersion },
        { action_id: 'navigate_trading', parameters: {}, context_version: contextVersion },
        {
          action_id: 'fill_trade_draft',
          parameters: { side: 'buy', quantity: '100', price_type: 'market' },
          context_version: contextVersion,
        },
      ],
    })
    const pinia = createPinia()
    const store = useTradingDeskStore(pinia)
    await store.initialize()

    await store.submitAgentIntent('打开贵州茅台，切到交易页并帮我填买入100股')

    expect(tradingDeskApi.applyDeskUiAction).toHaveBeenCalledTimes(3)
    expect(store.symbol).toBe('600519.SH')
    expect(store.section).toBe('trading')
    expect(store.tradeDraftPrefill).toEqual({
      side: 'buy',
      quantity: '100',
      priceType: 'market',
      limitPrice: null,
    })
    expect(tradingDeskApi.submitSimulationDraft).not.toHaveBeenCalled()
  })

  it('answers a read-only question without replacing the running workflow', async () => {
    vi.mocked(tradingDeskApi.streamDeskAgentDecision).mockResolvedValue({
      decision_id: 'decision-read-only',
      decision_source: 'agent_generated_policy_approved',
      mode: 'answer',
      message: '可以直接回答。',
      workflow_key: null,
      workflow_title: null,
      routing_reason: '术语解释不需要正式任务。',
      expected_stages: [],
      can_start: true,
      answer_text: '市盈率是股价与每股收益的比值。',
      ui_actions: [],
    })
    const store = useTradingDeskStore(createPinia())
    await store.initialize()
    store.activeWorkflow = {
      run_id: 'run-active',
      status: 'running',
      workflow_key: 'company_research',
      workflow_version: '1',
      request_intent: '研究贵州茅台',
      revision: 2,
      created_at: '2026-07-25T00:00:00Z',
      updated_at: '2026-07-25T00:01:00Z',
      final_artifact: null,
    }

    await store.submitAgentIntent('什么是市盈率？')

    expect(tradingDeskApi.streamDeskAgentDecision).toHaveBeenCalledWith(
      expect.objectContaining({ activeWorkflow: true }),
      expect.any(Function),
    )
    expect(store.activeWorkflow?.run_id).toBe('run-active')
    expect(store.agentMessages.at(-1)).toMatchObject({
      role: 'assistant',
      kind: 'text',
      text: '市盈率是股价与每股收益的比值。',
    })
  })

  it('queues a second formal task while the current workflow remains active', async () => {
    vi.mocked(tradingDeskApi.streamDeskAgentDecision).mockResolvedValue({
      decision_id: 'decision-queued-workflow',
      decision_source: 'agent_generated_policy_approved',
      mode: 'workflow',
      message: '当前已有任务，本次不会重复创建。',
      workflow_key: 'company_research',
      workflow_title: '公司研究',
      routing_reason: '需要多阶段证据。',
      expected_stages: ['行情研究', '反方复核'],
      can_start: false,
      answer_text: null,
      ui_actions: [],
    })
    const store = useTradingDeskStore(createPinia())
    await store.initialize()
    store.activeWorkflow = {
      run_id: 'run-active',
      status: 'running',
      workflow_key: 'company_research',
      workflow_version: '1',
      request_intent: '研究贵州茅台',
      revision: 2,
      created_at: '2026-07-25T00:00:00Z',
      updated_at: '2026-07-25T00:01:00Z',
      final_artifact: null,
    }

    await store.submitAgentIntent('研究宁德时代供应链风险')

    expect(tradingDeskApi.createWorkflow).not.toHaveBeenCalled()
    expect(store.activeWorkflow.run_id).toBe('run-active')
    expect(store.queuedWorkflowIntents).toHaveLength(1)
    expect(store.queuedWorkflowIntents[0].intent).toBe('研究宁德时代供应链风险')
    expect(store.agentMessages.at(-1)).toMatchObject({
      kind: 'text',
      text: expect.stringContaining('已加入待办'),
    })
  })

  it('refreshes the shared candidate list after a candidate workflow completes', async () => {
    vi.mocked(tradingDeskApi.fetchDeskQuickCommands).mockResolvedValue({
      quick_commands: ['分析当前标的行情', '核查当前行情数据新鲜度', '结合画像生成可研究候选'],
      quick_commands_error: null,
      generated_at: '2026-07-25T01:00:08Z',
    })
    vi.mocked(tradingDeskApi.fetchDeskBootstrap).mockResolvedValue({
      owner_id: 'user-1',
      section: 'information',
      symbol: '000001.SZ',
      context_version: 'desk:user-1:information:000001.SZ:1',
      profile_projection: {
        version: 3,
        archetype_code: 'balanced',
        archetype_title: '均衡型',
        risk_level: 'moderate',
        loss_tolerance_percent: 15,
        confidence: 0.8,
        completeness: 1,
        education_only: false,
        selected_direction: 'equities',
        recommended_directions: ['equities'],
        projection_version: 'suitability-v1',
        available: true,
        degraded: false,
      },
      ui_action_catalog: [],
      capabilities: {
        workflow_create: true,
        workflow_worker: true,
        market_data: true,
      },
      generated_at: '2026-07-25T01:00:00Z',
    })
    vi.mocked(tradingDeskApi.createWorkflow).mockResolvedValue({
      run_id: 'workflow-candidates',
      status: 'queued',
      workflow_key: 'research_candidates',
      workflow_version: 'finance-god-workflows-v2',
      revision: 1,
      final_artifact: null,
    })
    vi.mocked(tradingDeskApi.fetchWorkflow).mockResolvedValue({
      run_id: 'workflow-candidates',
      status: 'completed',
      workflow_key: 'research_candidates',
      workflow_version: 'finance-god-workflows-v2',
      revision: 5,
      final_artifact: {
        object_type: 'ResearchCandidateSet',
        object_id: 'workflow-candidates',
        version: 'candidate-v1',
      },
    })
    vi.mocked(tradingDeskApi.fetchWorkflowProgress).mockResolvedValue({
      run_id: 'workflow-candidates',
      status: 'completed',
      workflow_key: 'research_candidates',
      workflow_version: 'finance-god-workflows-v2',
      revision: 5,
      updated_at: '2026-07-25T01:00:05Z',
      total_node_count: 4,
      completed_node_artifact_count: 4,
      completed_node_artifacts: [],
      errors: [],
      is_terminal: true,
    })
    vi.mocked(tradingDeskApi.fetchWorkflowEvidence).mockResolvedValue({
      object_type: 'ResearchCandidateSet',
      object_id: 'workflow-candidates',
      version: 'candidate-v1',
      subject: '结合画像生成可研究候选',
      conclusion: '已生成 3 个可继续研究的候选。',
      provider: 'finance-god-candidate-scoring',
      generated_at: '2026-07-25T01:00:04Z',
      facts: [],
      inferences: [],
      counterpoints: [],
      unknowns: [],
      invalidation_conditions: [],
      sources: [],
      agent_nodes: [],
      notices: [],
    })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(TradingDeskView, {
      global: { plugins: [createPinia(), router] },
    })
    await flushPromises()

    await wrapper.findAll('.quick-commands button')[2].trigger('click')
    await flushPromises()

    expect(tradingDeskApi.createWorkflow).toHaveBeenCalledWith(
      expect.objectContaining({ intent: '结合画像生成可研究候选' }),
    )
    expect(tradingDeskApi.fetchResearchCandidates).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[aria-label="工作流产物"]').text()).toContain(
      '已生成 3 个可继续研究的候选',
    )
  })

  it('hides a reminder toast without marking the reminder as read', async () => {
    vi.mocked(tradingDeskApi.fetchNotifications).mockResolvedValue([{
      notification_id: 'notice-1',
      severity: 'warning',
      title: '价格提醒',
      message: '已达到服务端提醒条件',
      created_at: '2026-07-25T01:00:00Z',
      status: 'unread',
    }])
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(TradingDeskView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    const toast = wrapper.get('.alert-toast')
    await toast.findAll('button').find((button) => button.text() === '隐藏')!.trigger('click')

    expect(wrapper.find('.alert-toast').exists()).toBe(false)
    expect(tradingDeskApi.markNotificationRead).not.toHaveBeenCalled()
    expect(wrapper.get('[aria-label="打开提醒"]').text()).toContain('提醒')
  })

  it('keeps a required market alert visible until the user acts', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(tradingDeskApi.fetchNotifications).mockResolvedValue([{
        notification_id: 'notice-required',
        severity: 'required',
        required: true,
        title: '重大行情提醒',
        message: '持仓标的达到高优先级阈值',
        created_at: '2026-07-25T01:00:00Z',
        status: 'unread',
        details: {
          symbol: '300750.SZ',
          provider_time: '2026-07-25T00:59:50Z',
          detected_at: '2026-07-25T01:00:00Z',
        },
      }])
      const router = createRouter({
        history: createMemoryHistory(),
        routes: [{ path: '/desk', component: TradingDeskView }],
      })
      await router.push('/desk')
      await router.isReady()
      const wrapper = mount(TradingDeskView, {
        global: { plugins: [createPinia(), router] },
      })
      await flushPromises()

      await vi.advanceTimersByTimeAsync(8_001)

      expect(wrapper.get('.alert-toast').text()).toContain('重大行情提醒')
      expect(tradingDeskApi.markNotificationRead).not.toHaveBeenCalled()
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('never renders facts from another symbol and keeps refresh errors visible', () => {
    const selectSymbol = vi.fn()
    const wrapper = mount(OverviewWorkspace, {
      props: {
        quotes: [{
          symbol: '600519.SH', name: '贵州茅台', last: 1400, change: 5, change_percent: 0.36,
          provider_time: '2026-07-25T01:00:00Z', frequency: '1m', freshness: 'current',
        }],
        selectedSymbol: '600519.SH',
        loading: false,
        marketError: null,
        marketLoadedAt: '2026-07-25T01:00:02Z',
        sentimentFacts: { symbol: '000001.SZ', requested_at: 'old', facts: [{ source: { data_time: 'old', evidence_ref: 'old-fact' }, fields: [{ name: '旧事实', value: '不应显示' }] }] },
        sentimentError: '新标的融资事实不可用',
        informationFacts: null,
        informationError: null,
        onSelectSymbol: selectSymbol,
        onRefresh: vi.fn(),
      },
    })

    expect(wrapper.text()).not.toContain('不应显示')
    expect(wrapper.get('[role="alert"]').text()).toContain('新标的融资事实不可用')
    const instrumentButton = wrapper.get('.index-tab.active')
    expect(instrumentButton.element.tagName).toBe('BUTTON')
    expect(instrumentButton.text()).toContain('贵州茅台')
  })

  it('discloses mock reference data without turning mock news into external links', () => {
    const generatedAt = '2026-07-25T01:00:00Z'
    const wrapper = mount(OverviewWorkspace, {
      props: {
        quotes: [],
        bars: [],
        selectedSymbol: '600519.SH',
        loading: false,
        marketError: null,
        barsError: null,
        marketLoadedAt: null,
        sentimentFacts: {
          provider: 'Finance-God Mock',
          fact_kind: 'market_sentiment',
          symbol: '600519.SH',
          requested_at: generatedAt,
          generated_at: generatedAt,
          data_mode: 'mock',
          fallback_reason: '真实市场情绪源暂时不可用。',
          facts: [{ fields: [{ name: 'score', value: 50 }, { name: 'level', value: 'neutral' }] }],
        },
        sentimentError: null,
        informationFacts: {
          provider: 'Finance-God Mock',
          fact_kind: 'industry_news',
          symbol: '600519.SH',
          requested_at: generatedAt,
          generated_at: generatedAt,
          data_mode: 'mock',
          fallback_reason: '真实市场资讯源暂时不可用。',
          facts: [{
            fields: [
              { name: 'title', value: '市场公告示例' },
              { name: 'source', value: 'Finance-God Mock' },
              { name: 'sector', value: '公告' },
              { name: 'url', value: '' },
            ],
          }],
        },
        informationError: null,
        onSelectSymbol: vi.fn(),
        onRefresh: vi.fn(),
      },
    })

    const disclosures = wrapper.findAll('.mock-data-disclosure')
    expect(disclosures).toHaveLength(2)
    expect(wrapper.text()).toContain('模拟数据')
    expect(wrapper.text()).toContain('真实市场情绪源暂时不可用')
    expect(wrapper.text()).toContain('真实市场资讯源暂时不可用')
    expect(wrapper.text()).toContain('刷新可重试真实数据')
    expect(wrapper.find('.news-item a').exists()).toBe(false)
    expect(wrapper.get('.news-item .news-source').text()).toBe('Finance-God Mock')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('does not offer account creation while the account request is failing', () => {
    const wrapper = mount(PortfolioWorkspace, {
      props: {
        account: null,
        accountState: 'error',
        portfolio: null,
        quotes: [],
        loading: false,
        error: '服务暂不可用',
        onLoad: vi.fn(),
        onCreateAccount: vi.fn(),
      },
    })

    expect(wrapper.text()).toContain('已暂停建立账户操作')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('presents historical candidate unavailability as a status instead of a read failure', () => {
    const wrapper = mount(WatchlistWorkspace, {
      props: {
        groups: [],
        candidates: [],
        loading: false,
        watchlistError: null,
        candidateError: null,
        candidateNotice: '历史演示不提供研究候选，避免引入未来信息。',
        onLoad: vi.fn(),
        onCreateGroup: vi.fn(),
        onRenameGroup: vi.fn(),
        onDeleteGroup: vi.fn(),
        onAddInstrument: vi.fn(),
        onRemoveInstrument: vi.fn(),
        onIgnoreCandidate: vi.fn(),
      },
    })

    expect(wrapper.get('[role="status"]').text()).toBe('历史演示不提供研究候选，避免引入未来信息。')
    expect(wrapper.text()).not.toContain('候选读取失败')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('presents historical market-fact boundaries as statuses instead of refresh failures', () => {
    const wrapper = mount(OverviewWorkspace, {
      props: {
        quotes: [],
        bars: [],
        selectedSymbol: '000001.SH',
        loading: false,
        marketError: null,
        barsError: null,
        marketLoadedAt: null,
        sentimentFacts: null,
        sentimentError: null,
        sentimentNotice: '历史演示不提供时点还原的市场情绪事实。',
        informationFacts: null,
        informationError: null,
        informationNotice: '历史演示不展示现实资讯，避免引入未来信息。',
        onSelectSymbol: vi.fn(),
        onRefresh: vi.fn(),
      },
    })

    expect(wrapper.findAll('[role="status"]').map((item) => item.text())).toEqual([
      '历史演示不提供时点还原的市场情绪事实。',
      '历史演示不展示现实资讯，避免引入未来信息。',
    ])
    expect(wrapper.text()).not.toContain('刷新失败')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('mounts all five workspaces and preserves explicit empty states', async () => {
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
    expect(buttons).toHaveLength(5)
    await buttons[1].trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('建立模拟账户'))
    expect(wrapper.text()).toContain('建立模拟账户')
    await buttons[2].trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('自选分组'))
    expect(wrapper.text()).toContain('自选分组')
    expect(wrapper.text()).toContain('可研究候选')
    await buttons[3].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('尚未建立模拟账户')
    await buttons[4].trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('暂无交易案例'))
    expect(tradingDeskApi.fetchTradeEpisodes).toHaveBeenCalledOnce()
    expect(tradingDeskApi.fetchAgentLearningSummary).toHaveBeenCalledOnce()

    await wrapper.get('.review-workspace .refresh-button').trigger('click')
    await vi.waitFor(() => expect(tradingDeskApi.fetchTradeEpisodes).toHaveBeenCalledTimes(2))
    expect(tradingDeskApi.fetchAgentLearningSummary).toHaveBeenCalledTimes(2)
  })

  it('loads orders only once when the trading workspace opens', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(TradingDeskView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    await wrapper.findAll('[aria-label="交易台工作区"] button')[3].trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('尚未建立模拟账户'))
    expect(tradingDeskApi.fetchSimulationOrders).toHaveBeenCalledTimes(1)
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
      simulation_time: '2026-07-24T01:30:00Z',
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
    await vi.waitFor(() => expect(wrapper.find('[aria-label="我的内容"]').exists()).toBe(true))
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

    await wrapper.get('[aria-label="关闭我的"]').trigger('click')
    await wrapper.findAll('[aria-label="交易台工作区"] button')[3].trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('成交回执'))
    expect(wrapper.text()).toContain('order-1')
  })

  it('keeps the Agent expanded without exposing layout settings', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    expect(wrapper.find('[aria-label="调整工作区布局"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="展开交易 Agent"]').exists()).toBe(false)
    expect(wrapper.find('[role="separator"]').exists()).toBe(false)
    expect(wrapper.get('[aria-label="交易 Agent"]').text()).toContain('AI AGENT')
    const labels = wrapper.findAll('[aria-label="交易台工作区"] button').map((button) => button.text())
    expect(labels).toEqual(['总览', '持仓', '自选', '交易', '复盘'])
  })

  it('submits one immediate market trade with only symbol, side, and quantity', async () => {
    const onSubmit = vi.fn()
    const onSelectSymbol = vi.fn()
    const onPeriodChange = vi.fn()
    const wrapper = mount(TradingWorkspace, {
      props: {
        account: { account_id: 'account-1', cash_available_rmb: '100000' }, accountState: 'available',
        portfolio: { account_id: 'account-1', owner_id: 'user-1', as_of: '2026-07-25T01:00:00Z', rule_version: 'simulation-rules-v1', positions: [], realized_pnl_rmb: '0' },
        selectedSymbol: '000001.SZ',
        quotes: [{
          symbol: '000001.SZ', name: '平安银行', last: 11.12, change: 0.12, change_percent: 1.09,
          provider: 'PandaData', provider_time: '2026-07-25T01:00:00Z', frequency: '1m',
          freshness: 'current', market_status: 'in_session',
        }],
        bars: [{
          time: '2026-07-25T01:00:00Z',
          open: 11,
          high: 11.2,
          low: 10.9,
          close: 11.12,
          volume: 1000,
        }],
        barsError: null,
        fills: [],
        receipt: null,
        loading: false, error: null, onLoad: vi.fn(), onSubmit, onSelectSymbol, onPeriodChange,
      },
    })
    expect(wrapper.text()).toContain('交易股票实时 K 线')
    expect(wrapper.text()).toContain('000001.SZ')
    await wrapper.get('input:not([type])').setValue('600519.sh')
    await wrapper.get('input:not([type])').trigger('change')
    expect(onSelectSymbol).toHaveBeenCalledWith('600519.SH')
    await wrapper.findAll('.period-tab').find((tab) => tab.text() === '5分')!.trigger('click')
    expect(onPeriodChange).toHaveBeenCalledWith('1m')

    await wrapper.get('input:not([type])').setValue('000001.SZ')
    await wrapper.get('input:not([type])').trigger('change')
    await wrapper.get('input[type="number"]').setValue('100')
    expect(wrapper.text()).toContain('立即买入')
    expect(wrapper.text()).not.toContain('订单草稿')
    expect(wrapper.text()).not.toContain('风险复核')
    await wrapper.get('form').trigger('submit')
    expect(onSubmit).toHaveBeenCalledWith({ instrumentId: '000001.SZ', side: 'buy', quantity: '100' })
    expect(wrapper.text()).toContain('真实行情')
    expect(wrapper.text()).toContain('2026-07-25T01:00:00Z')
  })

  it('routes absent simulation accounts to portfolio and surfaces quote gate reasons', async () => {
    const openPortfolio = vi.fn()
    const ensureQuote = vi.fn()
    const absent = mount(TradingWorkspace, {
      props: {
        account: null,
        accountState: 'absent',
        portfolio: null,
        selectedSymbol: '000001.SZ',
        quotes: [],
        fills: [],
        receipt: null,
        loading: false,
        error: null,
        onLoad: vi.fn(),
        onOpenPortfolio: openPortfolio,
        onEnsureQuoteSymbol: ensureQuote,
        onSubmit: vi.fn(),
      },
    })
    expect(absent.text()).toContain('尚未建立模拟账户')
    expect(absent.text()).toContain('前往持仓')
    await absent.get('button.ink-button').trigger('click')
    expect(openPortfolio).toHaveBeenCalledTimes(1)

    vi.mocked(tradingDeskApi.draftReferenceBlockedReason).mockReturnValue('行情新鲜度不可用，不能作为订单引用价。')
    const blocked = mount(TradingWorkspace, {
      props: {
        account: { account_id: 'account-1', cash_available_rmb: '100000' },
        accountState: 'available',
        portfolio: null,
        selectedSymbol: '000001.SZ',
        quotes: [{
          symbol: '000001.SZ', name: '平安银行', last: 11.12, change: 0.12, change_percent: 1.09,
          provider: 'PandaData', provider_time: '2026-07-25T01:00:00Z', frequency: '1m',
          freshness: 'unavailable', market_status: 'in_session',
        }],
        fills: [],
        receipt: null,
        loading: false,
        error: null,
        onLoad: vi.fn(),
        onEnsureQuoteSymbol: ensureQuote,
        onSubmit: vi.fn(),
      },
    })
    expect(blocked.text()).toContain('行情新鲜度不可用，不能作为订单引用价。')
    expect(blocked.get('button.ink-button').attributes('disabled')).toBeDefined()
  })

  it('keeps portfolio cost basis when market value is unavailable and never invents last prices', () => {
    const wrapper = mount(PortfolioWorkspace, {
      props: {
        account: {
          account_id: 'account-1',
          cash_total_rmb: '100000',
          cash_available_rmb: '90000',
          cash_frozen_rmb: '10000',
          revision: 1,
          simulation_time: '2026-07-24T01:30:00Z',
        },
        accountState: 'available',
        portfolio: {
          as_of: '2026-07-25T01:00:00Z',
          rule_version: 'sim-v1',
          realized_pnl_rmb: '12.5',
          positions: [{
            instrument_id: '000001.SZ',
            quantity: '100',
            available_quantity: '100',
            average_cost_rmb: '10',
            cost_basis_rmb: '1000',
            realized_pnl_rmb: '12.5',
          }],
        },
        quotes: [{
          symbol: '000001.SZ',
          last: null,
          provider_time: '2026-07-25T01:00:00Z',
          freshness: 'error',
          market_status: 'closed',
        }],
        loading: false,
        error: null,
        onLoad: vi.fn(),
        onCreateAccount: vi.fn(),
      },
    })
    expect(wrapper.text()).toContain('无最新价')
    expect(wrapper.text()).toContain('¥1,000')
    expect(wrapper.text()).toContain('2026-07-25T01:00:00Z · error · closed')
    expect(wrapper.text()).toContain('不会用本地估算填充')
    expect(wrapper.text()).not.toMatch(/市值[\s\S]*¥1,1/)
    expect(wrapper.text()).not.toContain('自动卖出策略')
    expect(wrapper.text()).not.toContain('设止盈止损')
    expect(wrapper.find('th[scope="col"]:last-child').text()).toBe('已实现')
  })

  it('treats only explicit true capabilities as enabled', () => {
    expect(tradingDeskApi.isDeskCapabilityEnabled({ workflow_create: true }, 'workflow_create')).toBe(true)
    expect(tradingDeskApi.isDeskCapabilityEnabled({ workflow_create: false }, 'workflow_create')).toBe(false)
    expect(tradingDeskApi.isDeskCapabilityEnabled({}, 'workflow_create')).toBe(false)
    expect(tradingDeskApi.isDeskCapabilityEnabled(null, 'workflow_create')).toBe(false)
    expect(tradingDeskApi.isDeskCapabilityEnabled(undefined, 'workflow_worker')).toBe(false)
  })

  it('blocks workflow submit when bootstrap capabilities are not live-true', async () => {
    vi.mocked(tradingDeskApi.fetchDeskBootstrap).mockImplementation(async (input) => ({
      owner_id: 'user-1',
      section: input?.section ?? 'information',
      symbol: input?.symbol ?? '000001.SZ',
      context_version: `desk:user-1:${input?.section ?? 'information'}:${input?.symbol ?? '000001.SZ'}:1`,
      profile_projection: {
        version: null,
        archetype_code: null,
        archetype_title: null,
        risk_level: null,
        loss_tolerance_percent: null,
        confidence: null,
        completeness: null,
        education_only: null,
        selected_direction: null,
        recommended_directions: [],
        projection_version: 'suitability-v1',
        available: false,
        degraded: false,
      },
      ui_action_catalog: [],
      capabilities: {
        workflow_create: true,
        // worker absent → must not enable submit
        market_data: true,
        settings_excluded: true,
        ui_actions: true,
        order_submit: false,
      },
      generated_at: '2026-07-25T01:00:00Z',
    }))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(TradingDeskView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    const submit = wrapper.find('button[aria-label="发送给 Agent"]')
    expect(submit.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('服务端未确认 Workflow Worker 正在运行')
    expect(tradingDeskApi.createWorkflow).not.toHaveBeenCalled()
  })

  it('clears capabilities and context when bootstrap fails', async () => {
    vi.mocked(tradingDeskApi.fetchDeskBootstrap).mockRejectedValue(new Error('bootstrap down'))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/desk', component: TradingDeskView }],
    })
    await router.push('/desk')
    await router.isReady()
    const wrapper = mount(TradingDeskView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    expect(wrapper.text()).toMatch(/bootstrap down|交易台引导状态不可用/)
    const submit = wrapper.find('button[aria-label="发送给 Agent"]')
    expect(submit.attributes('disabled')).toBeDefined()
    expect(tradingDeskApi.createWorkflow).not.toHaveBeenCalled()
  })
})
