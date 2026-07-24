import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { adminAuthApi } from '@/api'
import type { AuthData, User } from '@/types/api'

const TOKEN = 'finance-god-admin-token'
const USER = 'finance-god-admin-user'

function storedUser(): User | null {
  try { return JSON.parse(localStorage.getItem(USER) || 'null') as User | null }
  catch { return null }
}

export const useAdminAuthStore = defineStore('adminAuth', () => {
  const token = ref(localStorage.getItem(TOKEN))
  const user = ref<User | null>(storedUser())
  const loading = ref(false)
  let client = adminAuthApi
  const authenticated = computed(() => Boolean(token.value && user.value?.role === 'admin'))

  function configureApi(api: typeof adminAuthApi) { client = api }
  function persist(data: AuthData) {
    if (data.user.role !== 'admin') throw new Error('该账户没有管理员权限')
    token.value = data.access_token
    user.value = data.user
    localStorage.setItem(TOKEN, data.access_token)
    localStorage.setItem(USER, JSON.stringify(data.user))
  }
  async function login(email: string, password: string) {
    loading.value = true
    try { persist(await client.login(email, password)) }
    finally { loading.value = false }
  }
  async function hydrate() {
    if (!token.value) return
    try {
      const current = await client.me()
      if (current.role !== 'admin') throw new Error('该账户没有管理员权限')
      user.value = current
      localStorage.setItem(USER, JSON.stringify(current))
    } catch { logout() }
  }
  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem(TOKEN)
    localStorage.removeItem(USER)
  }
  return { token, user, loading, authenticated, configureApi, login, hydrate, logout }
})
