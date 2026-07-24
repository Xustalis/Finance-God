import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

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
