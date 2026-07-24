import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WorkflowProgress from '@/components/desk/WorkflowProgress.vue'
import { useAiContextStore } from '@/stores/aiContext'
import { useDeskCommandsStore } from '@/stores/deskCommands'
import { parseProposedAction, parseProposedActions } from '@/services/proposedActions'
import { quickCommandsForScope } from '@/services/quickCommands'
import type { AgentRun } from '@/types/desk'

describe('parseProposedAction', () => {
  it('maps an action mentioning an A-share symbol to desk.selectSymbol', () => {
    const link = parseProposedAction('建议关注 600519.SH 的回调机会')
    expect(link.action).toEqual({ type: 'desk.selectSymbol', payload: { symbol: '600519.SH' } })
    expect(link.actionLabel).toBe('切换到 600519.SH')
  })

  it('leaves free-text advice without a symbol as a non-executable suggestion', () => {
    const link = parseProposedAction('保持关注宏观流动性变化')
    expect(link.action).toBeNull()
    expect(link.actionLabel).toBeNull()
  })

  it('never emits a write action (no order/mandate) from free text', () => {
    const links = parseProposedActions([
      '买入 000001.SZ 100 股',
      '提交下单并确认',
      '将 600036.SH 加入自选',
    ])
    for (const link of links) {
      // 仅安全非写入类：唯一可能的动作是 desk.selectSymbol。
      if (link.action) expect(link.action.type).toBe('desk.selectSymbol')
    }
  })
})

function runWith(proposedActions: string[]): AgentRun {
  return {
    run_id: 'r1',
    plan: { run_id: 'r1', assignments: [{ agent_id: 'market_context', reason: '解读' }], notices: [] },
    results: [
      {
        agent_id: 'market_context',
        summary: '偏强',
        claims: [],
        evidence: [],
        proposed_actions: proposedActions,
        metadata: {},
      },
    ],
  }
}

describe('WorkflowProgress right→left action dispatch', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('dispatches a parsed symbol action to the registered left-side handler', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const ai = useAiContextStore()
    const deskCommands = useDeskCommandsStore()
    const selected: string[] = []
    deskCommands.register('desk.selectSymbol', (p) => { selected.push(String(p?.symbol)) })

    ai.run = runWith(['关注 600519.SH'])
    ai.status = 'done'
    const wrapper = mount(WorkflowProgress, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.get('[data-test="workflow-toggle"]').trigger('click')

    const button = wrapper.get('[data-test="wf-action-run-0"]')
    expect(button.text()).toContain('切换到 600519.SH')
    await button.trigger('click')
    expect(selected).toEqual(['600519.SH'])
    wrapper.unmount()
  })

  it('does not render an executable button when no left handler is registered', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const ai = useAiContextStore()
    ai.run = runWith(['关注 600519.SH'])
    ai.status = 'done'
    const wrapper = mount(WorkflowProgress, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.get('[data-test="workflow-toggle"]').trigger('click')

    expect(wrapper.find('[data-test="wf-action-run-0"]').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('first-run personalized recommendation', () => {
  it('prepends the buyable recommendation on the desk when there are no positions', () => {
    const withoutPositions = quickCommandsForScope('symbol', { noPositions: true })
    expect(withoutPositions).toHaveLength(3)
    expect(withoutPositions[0]).toMatchObject({
      id: 'desk.recommend',
      kind: 'action',
      action: { type: 'desk.recommend' },
    })
  })

  it('keeps the default symbol commands when positions exist', () => {
    const withPositions = quickCommandsForScope('symbol', { noPositions: false })
    expect(withPositions[0].id).toBe('symbol.analyze')
    expect(withPositions.some((c) => c.id === 'desk.recommend')).toBe(false)
  })

  it('never recommends in the settings scope (user settings are off-limits to the agent)', () => {
    expect(quickCommandsForScope('settings', { noPositions: true })).toHaveLength(0)
  })
})
