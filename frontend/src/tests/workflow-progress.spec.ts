import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WorkflowProgress from '@/components/desk/WorkflowProgress.vue'
import { useAiContextStore } from '@/stores/aiContext'
import { deriveWorkflowSteps } from '@/services/workflowSteps'
import type { AgentRun } from '@/types/desk'

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    run_id: 'r1',
    plan: {
      run_id: 'r1',
      assignments: [
        { agent_id: 'market_context', reason: '解读行情环境' },
        { agent_id: 'risk_scan', reason: '扫描风险' },
      ],
      notices: [],
    },
    results: [
      {
        agent_id: 'market_context',
        summary: '行情偏强',
        claims: [],
        evidence: [],
        proposed_actions: ['关注 600519.SH'],
        metadata: {},
      },
      {
        agent_id: 'risk_scan',
        summary: '风险可控',
        claims: [],
        evidence: [],
        proposed_actions: [],
        metadata: {},
      },
    ],
    ...overrides,
  }
}

describe('deriveWorkflowSteps', () => {
  it('returns an empty view for a null run', () => {
    expect(deriveWorkflowSteps(null)).toEqual({
      steps: [],
      doneCount: 0,
      blockedCount: 0,
      total: 0,
    })
  })

  it('marks assigned agents with results as done', () => {
    const view = deriveWorkflowSteps(run())
    expect(view.total).toBe(2)
    expect(view.doneCount).toBe(2)
    expect(view.steps[0]).toMatchObject({
      agentId: 'market_context',
      status: 'done',
      summary: '行情偏强',
      proposedActions: ['关注 600519.SH'],
    })
  })

  it('marks assigned agents blocked by a routing notice with missing resources', () => {
    const view = deriveWorkflowSteps(
      run({
        results: [
          {
            agent_id: 'market_context',
            summary: '行情偏强',
            claims: [],
            evidence: [],
            proposed_actions: [],
            metadata: {},
          },
        ],
        plan: {
          run_id: 'r1',
          assignments: [
            { agent_id: 'market_context', reason: '解读行情环境' },
            { agent_id: 'risk_scan', reason: '扫描风险' },
          ],
          notices: [
            {
              agent_id: 'risk_scan',
              reason: '缺少授权',
              missing_resources: ['fmp_metrics'],
              missing_authorizations: ['mandate:L1'],
            },
          ],
        },
      }),
    )
    expect(view.doneCount).toBe(1)
    expect(view.blockedCount).toBe(1)
    const blocked = view.steps.find((s) => s.agentId === 'risk_scan')
    expect(blocked?.status).toBe('blocked')
    expect(blocked?.missing).toEqual(['fmp_metrics', 'mandate:L1'])
  })

  it('appends result-only agents that were not in the plan as done', () => {
    const view = deriveWorkflowSteps(
      run({
        plan: { run_id: 'r1', assignments: [{ agent_id: 'market_context', reason: 'x' }], notices: [] },
      }),
    )
    expect(view.steps.map((s) => s.agentId)).toEqual(['market_context', 'risk_scan'])
    expect(view.steps[1]).toMatchObject({ status: 'done', reason: '运行时补充产出' })
  })
})

describe('WorkflowProgress component', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('shows an indeterminate running indicator while the run is in flight', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const ai = useAiContextStore()
    ai.status = 'running'
    const wrapper = mount(WorkflowProgress, { global: { plugins: [pinia] } })
    await flushPromises()

    expect(wrapper.find('[data-test="workflow-running"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="workflow-steps"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('collapses to a summary on completion and expands to reveal steps', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const ai = useAiContextStore()
    ai.run = run()
    ai.status = 'done'
    const wrapper = mount(WorkflowProgress, { global: { plugins: [pinia] } })
    await flushPromises()

    const toggle = wrapper.get('[data-test="workflow-toggle"]')
    expect(toggle.text()).toContain('完成 2/2 步')
    // 完成默认折叠：步骤不可见
    expect(wrapper.find('[data-test="workflow-steps"]').exists()).toBe(false)

    await toggle.trigger('click')
    const steps = wrapper.get('[data-test="workflow-steps"]')
    expect(steps.findAll('.wf-step')).toHaveLength(2)
    wrapper.unmount()
  })
})
