import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AiSidebar from '@/components/desk/AiSidebar.vue'
import {
  AI_SIDEBAR_COLLAPSE_KEY,
  useAiContextStore,
} from '@/stores/aiContext'

vi.mock('@/api/desk', () => ({
  runAgentResearch: vi.fn(),
  isDeskApiError: vi.fn().mockReturnValue(false),
  DeskApiError: class DeskApiError extends Error {},
}))

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    value: width,
  })
}

function mountSidebar() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(AiSidebar, { global: { plugins: [pinia] } })
  return { pinia, wrapper }
}

describe('shared AI sidebar', () => {
  beforeEach(() => {
    localStorage.clear()
    setViewport(1440)
  })

  it('defaults expanded at 1440 and renders only a real synchronized context', async () => {
    const { wrapper } = mountSidebar()
    const ai = useAiContextStore()
    ai.setContext({ scope: 'symbol', subject: '000001.SZ', label: '平安银行 · 000001.SZ' })
    await flushPromises()

    expect(wrapper.get('[data-test="ai-sidebar"]').classes()).toContain('ai-sidebar')
    expect(wrapper.get('[data-test="ai-current-object"]').text()).toContain('000001.SZ')
    expect(wrapper.text()).toContain('结论不会在浏览器端派生或伪造')
    expect(wrapper.find('.conclusion').exists()).toBe(false)
    wrapper.unmount()
  })

  it('defaults to a visible rail at 1024 and persists an explicit expansion', async () => {
    setViewport(1024)
    const first = mountSidebar()

    expect(first.wrapper.get('[data-test="ai-sidebar"]').classes()).toContain('ai-rail')
    expect(first.wrapper.get('[data-test="ai-sidebar-toggle"]').attributes('aria-label'))
      .toBe('展开 AI 侧栏')

    await first.wrapper.get('[data-test="ai-sidebar-toggle"]').trigger('click')
    expect(localStorage.getItem(AI_SIDEBAR_COLLAPSE_KEY)).toBe('false')
    first.wrapper.unmount()

    const second = mountSidebar()
    expect(second.wrapper.get('[data-test="ai-sidebar"]').classes()).toContain('ai-sidebar')
    second.wrapper.unmount()
  })

  it('follows the viewport default until the user chooses a state', async () => {
    const { wrapper } = mountSidebar()
    const ai = useAiContextStore()
    expect(ai.collapsed).toBe(false)

    ai.syncViewportDefault(1024)
    await flushPromises()
    expect(wrapper.get('[data-test="ai-sidebar"]').classes()).toContain('ai-rail')

    await wrapper.get('[data-test="ai-sidebar-toggle"]').trigger('click')
    ai.syncViewportDefault(1024)
    expect(ai.collapsed).toBe(false)
    wrapper.unmount()
  })

  it('keeps the prompt draft while collapsed and when the route context changes', async () => {
    const { wrapper } = mountSidebar()
    const ai = useAiContextStore()
    ai.setContext({ scope: 'symbol', subject: '000001.SZ' })
    await wrapper.get('[data-test="ai-followup"]').setValue('解释当前对象的数据边界')

    await wrapper.get('[data-test="ai-sidebar-toggle"]').trigger('click')
    expect(ai.followUp).toBe('解释当前对象的数据边界')

    ai.setContext({ scope: 'orders', subject: '仿真订单执行', label: '订单执行' })
    await wrapper.get('[data-test="ai-sidebar-toggle"]').trigger('click')
    expect((wrapper.get('[data-test="ai-followup"]').element as HTMLTextAreaElement).value)
      .toBe('解释当前对象的数据边界')
    expect(wrapper.get('[data-test="ai-current-object"]').text()).toBe('订单执行')
    wrapper.unmount()
  })
})
