import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '@/App.vue'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import { DESK_LAYOUT_STORAGE_KEY } from '@/composables/useDeskLayoutPreference'

function setViewportWidth(width: number) {
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    writable: true,
    value: width,
  })
}

describe('desktop width gate', () => {
  afterEach(() => setViewportWidth(1024))

  async function mountApp() {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/',
        component: { template: '<div data-testid="business-route">route</div>' },
      }],
    })
    await router.push('/')
    await router.isReady()
    return mount(App, {
      global: {
        plugins: [createPinia(), router],
        stubs: { AiSidebar: true },
      },
    })
  }

  it('does not mount business routes below 1024px', async () => {
    setViewportWidth(900)
    const wrapper = await mountApp()

    expect(wrapper.get('[data-testid="desktop-width-notice"]').text()).toContain('最低支持 1024 px')
    expect(wrapper.text()).toContain('不提供移动交易布局')
    expect(wrapper.find('[data-testid="business-route"]').exists()).toBe(false)
  })

  it('mounts business routes at the minimum supported width', async () => {
    setViewportWidth(1024)
    const wrapper = await mountApp()

    expect(wrapper.get('[data-testid="business-route"]').text()).toBe('route')
    expect(wrapper.find('[data-testid="desktop-width-notice"]').exists()).toBe(false)
  })
})

describe('desk workspace preferences', () => {
  function mountLayout() {
    return mount(DeskLayout, {
      slots: {
        left: '<div>left content</div>',
        main: '<div>main content</div>',
        right: '<div>right content</div>',
      },
      global: {
        stubs: {
          Masthead: { template: '<header data-testid="masthead" />' },
          BottomRail: { template: '<section data-testid="bottom-panel">bottom</section>' },
        },
      },
    })
  }

  it('saves hidden panels and restores them after remount', async () => {
    const wrapper = mountLayout()
    await wrapper.get('[data-testid="toggle-right-panel"]').trigger('click')

    expect(wrapper.get('.desk-page').classes()).toContain('right-hidden')
    expect(wrapper.get('.desk-right').attributes('style')).toContain('display: none')
    expect(JSON.parse(localStorage.getItem(DESK_LAYOUT_STORAGE_KEY) ?? '{}')).toMatchObject({
      right: false,
    })

    wrapper.unmount()
    const restored = mountLayout()
    expect(restored.get('.desk-page').classes()).toContain('right-hidden')
    expect(restored.get('.desk-right').attributes('style')).toContain('display: none')
  })

  it('resets every panel and clears the saved preference', async () => {
    const wrapper = mountLayout()
    await wrapper.get('[data-testid="toggle-left-panel"]').trigger('click')
    await wrapper.get('[data-testid="toggle-bottom-panel"]').trigger('click')
    await wrapper.get('[data-testid="reset-layout"]').trigger('click')

    expect(wrapper.get('.desk-left').isVisible()).toBe(true)
    expect(wrapper.get('[data-testid="bottom-panel"]').isVisible()).toBe(true)
    expect(localStorage.getItem(DESK_LAYOUT_STORAGE_KEY)).toBeNull()
    expect(wrapper.get('[role="status"]').text()).toBe('布局已重置。')
  })

  it('surfaces corrupt saved data and uses the default layout', () => {
    localStorage.setItem(DESK_LAYOUT_STORAGE_KEY, '{"right":"hidden"}')
    const wrapper = mountLayout()

    expect(wrapper.get('[role="alert"]').text()).toContain('已恢复默认布局')
    expect(wrapper.get('.desk-right').isVisible()).toBe(true)
  })
})
