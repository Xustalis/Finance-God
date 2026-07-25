import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { createAppRouter } from './router'
import { useAuthStore } from './stores/auth'
import { useAdminAuthStore } from './stores/adminAuth'
import { bootstrapApplication } from './bootstrap'
import './styles.css'

const app = createApp(App)
const pinia = createPinia()
const router = createAppRouter()
app.use(pinia)
const auth = useAuthStore(pinia)
const adminAuth = useAdminAuthStore(pinia)

void bootstrapApplication({
  sessions: [
    { hasToken: Boolean(auth.token), hydrate: () => auth.hydrate() },
    { hasToken: Boolean(adminAuth.token), hydrate: () => adminAuth.hydrate() },
  ],
  mount: () => {
    app.use(router)
    app.mount('#app')
  },
  afterHydrate: async () => {
    await router.isReady()
    const route = router.currentRoute.value
    if (route.meta.requiresAuth && !auth.authenticated) {
      await router.replace({ path: '/login', query: { redirect: route.fullPath } })
    } else if (route.meta.requiresAdmin && !adminAuth.authenticated) {
      await router.replace({ path: '/admin/login', query: { redirect: route.fullPath } })
    }
  },
})
