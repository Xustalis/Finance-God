import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '@/App.vue'
import { createAppRouter } from '@/router'

const AUTHENTICATED_DESKTOP_PATHS = [
  '/app/exe',
  '/app/profile-report',
  '/overview',
  '/markets',
  '/watchlist',
  '/desk',
  '/portfolio',
  '/trade-plans/:planId',
  '/orders',
  '/reviews',
  '/data',
  '/data/evidence/:id',
  '/settings',
]

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    value: width,
  })
}

async function mountApp(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/login',
        name: 'login',
        component: { template: '<main data-test="login-page">登录</main>' },
      },
      {
        path: '/desk',
        name: 'desk',
        component: { template: '<main data-test="desk-page">交易台</main>' },
        meta: { requiresAuth: true },
      },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(App, {
    global: { plugins: [createPinia(), router] },
  })
  await flushPromises()
  return { router, wrapper }
}

describe('authenticated desktop AI shell', () => {
  beforeEach(() => {
    localStorage.clear()
    setViewport(1440)
  })

  it('mounts one shared sidebar only for authenticated desktop routes', async () => {
    const { router, wrapper } = await mountApp('/login')
    expect(wrapper.find('[data-test="ai-sidebar"]').exists()).toBe(false)

    await router.push('/desk')
    await flushPromises()
    expect(wrapper.findAll('[data-test="ai-sidebar"]')).toHaveLength(1)
    expect(wrapper.find('.desktop-app-shell').exists()).toBe(true)
    wrapper.unmount()
  })

  it('places every user desktop route in the authenticated shared shell', () => {
    const router = createAppRouter(createMemoryHistory())
    const authenticatedPaths = router.getRoutes()
      .filter((route) => route.meta.requiresAuth === true)
      .map((route) => route.path)

    expect(authenticatedPaths).toEqual(expect.arrayContaining(AUTHENTICATED_DESKTOP_PATHS))
    expect(authenticatedPaths).toHaveLength(AUTHENTICATED_DESKTOP_PATHS.length)
  })

  it('keeps the 1024 desktop route and replaces it with a notice below 1024', async () => {
    setViewport(1024)
    const { wrapper } = await mountApp('/desk')
    expect(wrapper.get('[data-test="ai-sidebar"]').classes()).toContain('ai-rail')
    expect(wrapper.find('[data-testid="desktop-width-notice"]').exists()).toBe(false)

    setViewport(900)
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    expect(wrapper.find('[data-test="ai-sidebar"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="desktop-width-notice"]').text()).toContain('最低支持 1024 px')
    wrapper.unmount()
  })
})
