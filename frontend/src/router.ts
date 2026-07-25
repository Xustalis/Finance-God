import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

/* 路由 meta 类型扩展 */
declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    requiresAdmin?: boolean
    deskSection?: string
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

function profileCompleted(): boolean {
  return localStorage.getItem('finance-god-profile-completed') === 'true'
}

const deskView = () => import('@/views/TradingDeskView.vue')

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({ history, routes: [
    { path: '/', redirect: () => validStoredSession('finance-god-token', 'finance-god-user') ? (profileCompleted() ? '/desk' : '/app/exe') : '/login' },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/app/exe', name: 'onboarding', component: () => import('@/views/OnboardingView.vue'), meta: { requiresAuth: true } },
    { path: '/app/profile-report', name: 'report', component: () => import('@/views/ProfileReportView.vue'), meta: { requiresAuth: true } },

    // ─── 交易台：每个工作区独立路由 ───
    { path: '/desk', name: 'desk', component: deskView, meta: { requiresAuth: true, deskSection: 'information' } },
    { path: '/desk/portfolio', name: 'desk-portfolio', component: deskView, meta: { requiresAuth: true, deskSection: 'portfolio' } },
    { path: '/desk/watchlist', name: 'desk-watchlist', component: deskView, meta: { requiresAuth: true, deskSection: 'watchlist' } },
    { path: '/desk/trading', name: 'desk-trading', component: deskView, meta: { requiresAuth: true, deskSection: 'trading' } },
    { path: '/desk/review', name: 'desk-review', component: deskView, meta: { requiresAuth: true, deskSection: 'review' } },

    // ─── 遗留路径重定向 ───
    { path: '/rebuilding', redirect: '/desk' },
    { path: '/markets', redirect: '/desk' },
    { path: '/overview', redirect: '/desk' },
    { path: '/portfolio', redirect: '/desk/portfolio' },
    { path: '/watchlist', redirect: '/desk/watchlist' },
    { path: '/orders', redirect: '/desk/trading' },
    { path: '/trade-plans/:planId', redirect: '/desk/trading' },
    { path: '/reviews', redirect: '/desk/review' },
    { path: '/data', redirect: '/desk' },
    { path: '/data/evidence/:id', redirect: '/desk' },
    { path: '/settings', redirect: '/desk' },

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
    if (to.path === '/login' && userAuthenticated) return typeof to.query.redirect === 'string' ? to.query.redirect : (profileCompleted() ? '/desk' : '/app/exe')
    if (to.path === '/admin/login' && adminAuthenticated) return '/admin/ai-settings'
  })
  return router
}
