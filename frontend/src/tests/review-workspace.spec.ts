import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ReviewWorkspace from '@/components/desk/ReviewWorkspace.vue'
import type { AgentLearningSummary } from '@/services/tradingDesk'

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
