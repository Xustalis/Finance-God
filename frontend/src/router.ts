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

const Placeholder = () => import('@/views/placeholder/PlaceholderView.vue')

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({ history, routes: [
    { path: '/', redirect: () => validStoredSession('finance-god-token', 'finance-god-user') ? '/app/exe' : '/login' },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/app/exe', name: 'onboarding', component: () => import('@/views/OnboardingView.vue'), meta: { requiresAuth: true } },
    { path: '/app/profile-report', name: 'report', component: () => import('@/views/ProfileReportView.vue'), meta: { requiresAuth: true } },

    // ─── 交易台路由 ─────────────────────────────
    { path: '/markets', name: 'markets', component: () => import('@/views/MarketsView.vue') },
    { path: '/desk', name: 'desk', component: () => import('@/views/DeskView.vue') },

    // ─── 占位路由 ───────────────────────────────
    {
      path: '/overview', name: 'overview', component: Placeholder,
      meta: { pageLabel: '总览', pageKicker: 'OVERVIEW', pageDesc: '投资组合总览与关键指标一览，整合行情、持仓与风险概览。' },
    },
    {
      path: '/portfolio', name: 'portfolio', component: Placeholder,
      meta: { pageLabel: '组合', pageKicker: 'PORTFOLIO', pageDesc: '持仓管理、资产分配与收益归因分析。' },
    },
    {
      path: '/orders', name: 'orders', component: Placeholder,
      meta: { pageLabel: '订单', pageKicker: 'ORDERS', pageDesc: '订单管理、历史成交与执行记录。' },
    },
    {
      path: '/reviews', name: 'reviews', component: Placeholder,
      meta: { pageLabel: '复盘', pageKicker: 'REVIEWS', pageDesc: '交易复盘、策略回顾与绩效分析。' },
    },
    {
      path: '/data', name: 'data', component: Placeholder,
      meta: { pageLabel: '数据目录', pageKicker: 'DATA CATALOG', pageDesc: 'PandaData 数据集目录、质量摘要与可用性状态。' },
    },
    {
      path: '/settings', name: 'settings', component: Placeholder,
      meta: { pageLabel: '设置', pageKicker: 'SETTINGS', pageDesc: '工作区偏好、通知设置与账户管理。' },
    },

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
