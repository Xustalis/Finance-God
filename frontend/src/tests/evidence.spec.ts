import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import EvidenceDrawer from '@/components/evidence/EvidenceDrawer.vue'
import EvidenceView from '@/views/EvidenceView.vue'
import {
  compareEvidenceVersions,
  exportEvidence,
  fetchEvidence,
  fetchEvidenceLineage,
} from '@/api/desk'
import type {
  EvidenceCompareView,
  EvidenceExportView,
  EvidenceLineageView,
  EvidenceView as EvidenceViewModel,
} from '@/types/desk'

vi.mock('@/api/desk', () => ({
  fetchEvidence: vi.fn(),
  fetchEvidenceLineage: vi.fn(),
  compareEvidenceVersions: vi.fn(),
  exportEvidence: vi.fn(),
  isDeskApiError: (error: unknown, status?: number) =>
    Boolean(error) && (status === undefined || (error as { status?: number }).status === status),
  DeskApiError: class DeskApiError extends Error {},
}))

const detailView: EvidenceViewModel = {
  object_type: 'agent_run',
  object_id: 'run-1',
  version: '2',
  subject: '平安银行研究',
  conclusion: '维持观察，等待成交量确认。',
  provider: 'research_runtime',
  generated_at: '2026-07-24T08:00:00+00:00',
  tier: 'advanced',
  facts: [
    {
      kind: 'fact',
      statement: '事实A：最近收盘价站上年线。',
      author_agent_id: 'a1',
      evidence_ids: [],
      unknowns: [],
      invalidation_conditions: [],
    },
  ],
  inferences: [
    {
      kind: 'inference',
      statement: '推断B：短期存在补涨动能。',
      author_agent_id: 'a2',
      evidence_ids: [],
      unknowns: [],
      invalidation_conditions: [],
    },
  ],
  counterpoints: ['反方C：成交量尚未放大。'],
  unknowns: ['未知D：政策窗口不明。'],
  invalidation_conditions: ['失效E：跌破年线即失效。'],
  sources: [{ identifier: 's1', source: 'PandaData 快照', excerpt: '2026-07-24 收盘' }],
  agent_nodes: [{ agent_id: 'planner', reason: '编排研究任务' }],
  notices: [
    {
      agent_id: 'risk',
      reason: '缺少融资资源',
      missing_resources: ['margin_data'],
      missing_authorizations: [],
    },
  ],
  error_trace: null,
}

const lineageView: EvidenceLineageView = {
  object_type: 'agent_run',
  object_id: 'run-1',
  version: '2',
  provider: 'research_runtime',
  generated_at: '2026-07-24T08:00:00+00:00',
  inputs: [{ object_type: 'market_quote', object_id: '600000.SH', version: '1' }],
  sources: [{ identifier: 's1', source: 'PandaData 快照', excerpt: '2026-07-24 收盘' }],
}

const exportView: EvidenceExportView = {
  object_type: 'agent_run',
  object_id: 'run-1',
  exported_at: '2026-07-24T09:00:00+00:00',
  tier: 'advanced',
  versions: [
    {
      version: '1',
      subject: '平安银行研究',
      conclusion: '首次结论。',
      provider: 'research_runtime',
      generated_at: '2026-07-24T07:00:00+00:00',
    },
    {
      version: '2',
      subject: '平安银行研究',
      conclusion: '维持观察，等待成交量确认。',
      provider: 'research_runtime',
      generated_at: '2026-07-24T08:00:00+00:00',
    },
  ],
  bundle: detailView,
}

const compareView: EvidenceCompareView = {
  object_type: 'agent_run',
  object_id: 'run-1',
  base: exportView.versions[0],
  other: exportView.versions[1],
  diffs: [{ field: '事实', added: ['事实A：最近收盘价站上年线。'], removed: [] }],
}

function evidenceRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/data/evidence/:id', name: 'evidence', component: EvidenceView },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  })
}

describe('T10 evidence drawer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(fetchEvidence).mockReset()
    vi.mocked(fetchEvidence).mockResolvedValue(structuredClone(detailView))
  })

  it('renders immutable evidence in the fixed section order', async () => {
    const router = evidenceRouter()
    const wrapper = mount(EvidenceDrawer, {
      props: { open: true, objectType: 'agent_run', objectId: 'run-1', version: '2' },
      global: { plugins: [router], stubs: { teleport: true } },
    })
    await flushPromises()

    const labels = wrapper.findAll('.block-label').map((node) => node.text())
    expect(labels).toEqual([
      '结论 · 版本',
      '事实',
      '推断',
      '反方 / 分歧',
      '未知项',
      '来源 · 时点',
      '规则影响 / 失效条件',
    ])
    expect(wrapper.get('[data-test="evidence-version"]').text()).toBe('v2')
    expect(wrapper.get('[data-test="evidence-advanced-link"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows an explicit empty state when the object has no evidence (404)', async () => {
    vi.mocked(fetchEvidence).mockRejectedValueOnce({ status: 404, message: 'not found' })
    const router = evidenceRouter()
    const wrapper = mount(EvidenceDrawer, {
      props: { open: true, objectType: 'agent_run', objectId: 'missing', version: null },
      global: { plugins: [router], stubs: { teleport: true } },
    })
    await flushPromises()

    expect(wrapper.get('[data-test="evidence-empty"]').exists()).toBe(true)
    expect(wrapper.find('.conclusion').exists()).toBe(false)
    wrapper.unmount()
  })

  it('surfaces an explicit failure with the error code instead of a spinner', async () => {
    vi.mocked(fetchEvidence).mockRejectedValueOnce({
      status: 500,
      code: 'EVIDENCE_UNAVAILABLE',
      message: '证据服务暂不可用。',
    })
    const router = evidenceRouter()
    const wrapper = mount(EvidenceDrawer, {
      props: { open: true, objectType: 'agent_run', objectId: 'run-1', version: null },
      global: { plugins: [router], stubs: { teleport: true } },
    })
    await flushPromises()

    const error = wrapper.get('[data-test="evidence-error"]')
    expect(error.text()).toContain('证据服务暂不可用。')
    expect(error.text()).toContain('EVIDENCE_UNAVAILABLE')
    wrapper.unmount()
  })
})

describe('T10 evidence advanced page', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(fetchEvidence).mockReset()
    vi.mocked(fetchEvidenceLineage).mockReset()
    vi.mocked(exportEvidence).mockReset()
    vi.mocked(compareEvidenceVersions).mockReset()
    vi.mocked(fetchEvidence).mockResolvedValue(structuredClone(detailView))
    vi.mocked(fetchEvidenceLineage).mockResolvedValue(structuredClone(lineageView))
    vi.mocked(exportEvidence).mockResolvedValue(structuredClone(exportView))
    vi.mocked(compareEvidenceVersions).mockResolvedValue(structuredClone(compareView))
  })

  it('renders detail, version navigation, workflow, and a gated error trace note', async () => {
    const router = evidenceRouter()
    await router.push({ name: 'evidence', params: { id: 'run-1' }, query: { type: 'agent_run', version: '2' } })
    await router.isReady()
    const wrapper = mount(EvidenceView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    expect(wrapper.get('[data-test="evidence-view"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-test="evidence-version-list"] li')).toHaveLength(2)
    expect(wrapper.get('[data-test="evidence-workflow"]').text()).toContain('planner')
    // 错误栈仅限内部权限：普通 / 高级页不呈现原始 trace，而是显式说明。
    expect(wrapper.find('[data-test="evidence-error-trace"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('仅限内部权限')
    wrapper.unmount()
  })

  it('compares two versions and renders the immutable diff', async () => {
    const router = evidenceRouter()
    await router.push({ name: 'evidence', params: { id: 'run-1' }, query: { type: 'agent_run' } })
    await router.isReady()
    const wrapper = mount(EvidenceView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    await wrapper.get('[data-test="run-compare"]').trigger('click')
    await flushPromises()

    expect(compareEvidenceVersions).toHaveBeenCalledWith('agent_run', 'run-1', '1', '2')
    const result = wrapper.get('[data-test="compare-result"]')
    expect(result.text()).toContain('v1 → v2')
    expect(result.text()).toContain('事实A：最近收盘价站上年线。')
    wrapper.unmount()
  })

  it('shows an explicit empty state for an unknown object', async () => {
    vi.mocked(fetchEvidence).mockRejectedValueOnce({ status: 404, message: 'not found' })
    const router = evidenceRouter()
    await router.push({ name: 'evidence', params: { id: 'missing' }, query: { type: 'agent_run' } })
    await router.isReady()
    const wrapper = mount(EvidenceView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    expect(wrapper.get('[data-test="evidence-view-empty"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
