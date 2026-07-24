import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

/* 路由 meta 类型扩展 */
declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    requiresAdmin?: boolean
    pageLabel?: string
    pageKicker?: string
    pageDesc?: string
  }
}

function validStoredSession(tokenKey: string, userKey: string, role?: string) {
  const token = localStorage.getItem(tokenKey)
  try {
    const user = JSON.parse(localStorage.getItem(userKey) || 'null') as { role?: string } | null
    return Boolean(token && user && (!role || user.role === role))
  } catch { return false }
}

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({ history, routes: [
    { path: '/', redirect: () => validStoredSession('finance-god-token', 'finance-god-user') ? '/app/exe' : '/login' },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/app/exe', name: 'onboarding', component: () => import('@/views/OnboardingView.vue'), meta: { requiresAuth: true } },
    { path: '/app/profile-report', name: 'report', component: () => import('@/views/ProfileReportView.vue'), meta: { requiresAuth: true } },

    // ─── 交易台路由 ─────────────────────────────
    { path: '/markets', name: 'markets', component: () => import('@/views/MarketsView.vue'), meta: { requiresAuth: true } },
    { path: '/desk', name: 'desk', component: () => import('@/views/DeskView.vue'), meta: { requiresAuth: true } },

    // ─── 占位路由 ───────────────────────────────
    { path: '/overview', name: 'overview', component: () => import('@/views/OverviewView.vue'), meta: { requiresAuth: true } },
    { path: '/portfolio', name: 'portfolio', component: () => import('@/views/PortfolioView.vue'), meta: { requiresAuth: true } },
    { path: '/orders', name: 'orders', component: () => import('@/views/OrdersView.vue'), meta: { requiresAuth: true } },
    { path: '/reviews', name: 'reviews', component: () => import('@/views/ReviewsView.vue'), meta: { requiresAuth: true } },
    { path: '/data', name: 'data', component: () => import('@/views/DataView.vue'), meta: { requiresAuth: true } },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { requiresAuth: true } },

    // ─── 管理路由 ───────────────────────────────
    { path: '/admin/login', name: 'admin-login', component: () => import('@/views/AdminLoginView.vue') },
    { path: '/admin/ai-settings', name: 'admin-settings', component: () => import('@/views/AdminSettingsView.vue'), meta: { requiresAdmin: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ] })
  router.beforeEach((to) => {
    const userAuthenticated = validStoredSession('finance-god-token', 'finance-god-user')
    const adminAuthenticated = validStoredSession('finance-god-admin-token', 'finance-god-admin-user', 'admin')
    if (to.meta.requiresAuth && !userAuthenticated) return { path: '/login', query: { redirect: to.fullPath } }
    if (to.meta.requiresAdmin && !adminAuthenticated) return { path: '/admin/login', query: { redirect: to.fullPath } }
    if (to.path === '/login' && userAuthenticated) return '/app/exe'
    if (to.path === '/admin/login' && adminAuthenticated) return '/admin/ai-settings'
  })
  return router
}
