import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ReviewWorkspace from '@/components/desk/ReviewWorkspace.vue'
import type { AgentLearningSummary, TradeEpisode } from '@/services/tradingDesk'

const baseSummary: AgentLearningSummary = {
  status: 'healthy',
  message: null,
  last_cycle: {
    cycle: 12,
    topic: 'market_learning',
    status: 'ok',
    started_at: '2026-07-25T01:00:00Z',
    completed_at: '2026-07-25T01:01:00Z',
    summary: '完成',
  },
  snapshot: {
    version: 8,
    total_lessons: 8,
    topics: { market_learning: 8 },
    updated_at: '2026-07-25T01:01:00Z',
  },
  recent_verified_lessons: [{
    lesson_id: 'lesson-1',
    statement: '波动扩大时需要收紧仓位上限。',
    topic: 'market_learning',
    validation_method: 'walk_forward_sma_v1',
    cycle: 12,
    created_at: '2026-07-25T01:01:00Z',
    tags: ['510300.SH'],
    invalidation_conditions: ['波动区间回落'],
  }],
  freshness: {
    configured_interval_seconds: 900,
    age_seconds: 60,
    is_stale: false,
  },
}

function mountWorkspace(overrides: Partial<{
  learningSummary: AgentLearningSummary | null
  learningLoading: boolean
  learningError: string | null
}> = {}) {
  return mount(ReviewWorkspace, {
    props: {
      episodes: [],
      selected: null,
      decisions: [],
      review: null,
      loading: false,
      error: null,
      learningSummary: baseSummary,
      learningLoading: false,
      learningError: null,
      onLoad: vi.fn(),
      onRetryLearning: vi.fn(),
      onSelect: vi.fn(),
      onRetry: vi.fn(),
      ...overrides,
    },
  })
}

describe('ReviewWorkspace Agent 自学习', () => {
  it('展示健康状态、知识摘要和已验证成果，并明确其系统级范围', () => {
    const wrapper = mountWorkspace()

    expect(wrapper.text()).toContain('Agent 自学习')
    expect(wrapper.text()).toContain('正常运行')
    expect(wrapper.text()).toContain('系统级研究知识')
    expect(wrapper.text()).toContain('知识版本')
    expect(wrapper.text()).toContain('v8')
    expect(wrapper.text()).toContain('波动扩大时需要收紧仓位上限。')
    expect(wrapper.text()).toContain('失效条件：波动区间回落')
  })

  it.each([
    ['stale', '数据陈旧'],
    ['unavailable', '尚未运行'],
    ['error', '运行异常'],
  ] as const)('展示 %s 状态', (status, label) => {
    const wrapper = mountWorkspace({
      learningSummary: {
        ...baseSummary,
        status,
        message: `${label}原因`,
      },
    })

    expect(wrapper.text()).toContain(label)
    expect(wrapper.text()).toContain(`${label}原因`)
  })

  it('后端运行但没有验证成果时展示明确空态', () => {
    const wrapper = mountWorkspace({
      learningSummary: {
        ...baseSummary,
        recent_verified_lessons: [],
        snapshot: { ...baseSummary.snapshot!, total_lessons: 0 },
      },
    })

    expect(wrapper.text()).toContain('后端已运行，当前暂无通过验证的学习结论')
  })

  it('自学习请求失败时独立展示错误和重试操作', async () => {
    const retry = vi.fn()
    const wrapper = mount(ReviewWorkspace, {
      props: {
        episodes: [],
        selected: null,
        decisions: [],
        review: null,
        loading: false,
        error: null,
        learningSummary: null,
        learningLoading: false,
        learningError: '学习摘要接口不可用',
        onLoad: vi.fn(),
        onRetryLearning: retry,
        onSelect: vi.fn(),
        onRetry: vi.fn(),
      },
    })

    expect(wrapper.text()).toContain('学习摘要接口不可用')
    expect(wrapper.text()).toContain('暂无交易案例')
    await wrapper.get('.learning-retry').trigger('click')
    expect(retry).toHaveBeenCalledOnce()
  })
})

describe('ReviewWorkspace 本地演示数据', () => {
  it('在显式演示模式且无真实案例时展示可切换的 mock 复盘', async () => {
    const wrapper = mount(ReviewWorkspace, {
      props: {
        episodes: [],
        selected: null,
        decisions: [],
        review: null,
        loading: false,
        error: null,
        learningSummary: null,
        learningLoading: false,
        learningError: null,
        demoMode: true,
        onLoad: vi.fn(),
        onRetryLearning: vi.fn(),
        onSelect: vi.fn(),
        onRetry: vi.fn(),
      },
    })

    expect(wrapper.text()).toContain('演示数据')
    expect(wrapper.text()).toContain('600519.SH')
    expect(wrapper.text()).toContain('实际收益')
    expect(wrapper.text()).toContain('¥7,552.86')

    const rows = wrapper.findAll('tbody tr')
    await rows[1].trigger('click')
    expect(wrapper.text()).toContain('持仓仍在进行')
    expect(wrapper.text()).toContain('通过宽基仓位降低单一行业暴露')
  })

  it('有真实案例时不展示 mock 或演示披露', () => {
    const realEpisode: TradeEpisode = {
      episode_id: 'real-episode',
      owner_id: 'real-user',
      account_id: 'real-account',
      instrument_id: '000001.SZ',
      status: 'open',
      review_status: null,
      opened_at: '2026-07-25 10:00',
      closed_at: null,
      opening_quantity: '100',
      current_quantity: '100',
      revision: 1,
      created_at: '2026-07-25T02:00:00Z',
      updated_at: '2026-07-25T02:00:00Z',
    }
    const wrapper = mount(ReviewWorkspace, {
      props: {
        episodes: [realEpisode],
        selected: realEpisode,
        decisions: [],
        review: null,
        loading: false,
        error: null,
        learningSummary: null,
        learningLoading: false,
        learningError: null,
        demoMode: true,
        onLoad: vi.fn(),
        onRetryLearning: vi.fn(),
        onSelect: vi.fn(),
        onRetry: vi.fn(),
      },
    })

    expect(wrapper.text()).toContain('000001.SZ')
    expect(wrapper.text()).not.toContain('600519.SH')
    expect(wrapper.text()).not.toContain('演示数据')
  })
})
