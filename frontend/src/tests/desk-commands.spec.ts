import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AiSidebar from '@/components/desk/AiSidebar.vue'
import { useAiContextStore } from '@/stores/aiContext'
import { useDeskCommandsStore } from '@/stores/deskCommands'
import { quickCommandsForScope } from '@/services/quickCommands'

const runAgentResearch = vi.fn()

vi.mock('@/api/desk', () => ({
  runAgentResearch: (...args: unknown[]) => runAgentResearch(...args),
  isDeskApiError: vi.fn().mockReturnValue(false),
  DeskApiError: class DeskApiError extends Error {},
}))

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
}

describe('deskCommands registry', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('registers, reports availability, dispatches, and unregisters safely', () => {
    const store = useDeskCommandsStore()
    expect(store.can('desk.selectSymbol')).toBe(false)
    expect(store.dispatch({ type: 'desk.selectSymbol', payload: { symbol: 'X' } })).toBe(false)

    const seen: string[] = []
    const off = store.register('desk.selectSymbol', (p) => { seen.push(String(p?.symbol)) })
    expect(store.can('desk.selectSymbol')).toBe(true)
    expect(store.available).toContain('desk.selectSymbol')

    expect(store.dispatch({ type: 'desk.selectSymbol', payload: { symbol: '600519.SH' } })).toBe(true)
    expect(seen).toEqual(['600519.SH'])

    off()
    expect(store.can('desk.selectSymbol')).toBe(false)
  })

  it('a stale unregister does not remove a newer registration of the same type', () => {
    const store = useDeskCommandsStore()
    const offA = store.register('nav.goto', () => {})
    store.register('nav.goto', () => {})
    offA() // 旧视图注销不得删除新视图的注册
    expect(store.can('nav.goto')).toBe(true)
  })
})

describe('quick commands by scope', () => {
  it('returns three commands for known scopes and none for settings', () => {
    expect(quickCommandsForScope('market')).toHaveLength(3)
    expect(quickCommandsForScope('portfolio')).toHaveLength(3)
    expect(quickCommandsForScope('settings')).toHaveLength(0)
    expect(quickCommandsForScope(null)).toHaveLength(0)
  })
})

describe('AiSidebar quick command area', () => {
  beforeEach(() => {
    localStorage.clear()
    setViewport(1440)
    runAgentResearch.mockReset()
    runAgentResearch.mockResolvedValue({ run_id: 'r1', plan: { run_id: 'r1', assignments: [], notices: [] }, results: [] })
  })

  it('renders scope-driven commands and running one triggers a research run', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(AiSidebar, { global: { plugins: [pinia] } })
    const ai = useAiContextStore()
    ai.setContext({ scope: 'market', subject: 'A股市场', label: '市场总览' })
    await flushPromises()

    const area = wrapper.get('[data-test="ai-quick-commands"]')
    expect(area.findAll('button')).toHaveLength(3)

    await wrapper.get('[data-test="quick-command-market.analyze"]').trigger('click')
    await flushPromises()
    expect(runAgentResearch).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('shows no quick command area in the settings scope', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(AiSidebar, { global: { plugins: [pinia] } })
    const ai = useAiContextStore()
    ai.setContext({ scope: 'settings', subject: '账户与工作区设置', label: '设置' })
    await flushPromises()
    expect(wrapper.find('[data-test="ai-quick-commands"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
