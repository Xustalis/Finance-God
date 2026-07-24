<script setup lang="ts">
/**
 * Masthead—报头：品牌、栏目导航、状态、日期、用户菜单
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMarketStore } from '@/stores/market'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const market = useMarketStore()
const auth = useAuthStore()

const NAV_ITEMS = [
  { label: '总览', path: '/overview' },
  { label: '行情', path: '/markets' },
  { label: '自选', path: '/watchlist' },
  { label: '交易台', path: '/desk' },
  { label: '资产', path: '/portfolio' },
  { label: '订单', path: '/orders' },
  { label: '复盘', path: '/reviews' },
  { label: '数据', path: '/data' },
  { label: '设置', path: '/settings' },
]

const today = computed(() => {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
})

const healthStatus = computed(() => {
  if (market.healthError) return '离线'
  if (!market.health) return '检测中'
  return market.health.readiness === 'ready' ? '就绪' : '未就绪'
})

const healthClass = computed(() => {
  if (market.healthError || market.health?.readiness === 'not_ready') return 'status-down'
  if (!market.health) return 'status-pending'
  return 'status-ok'
})

/* 行情刷新频率（设计 §8.2：可选 1/3/5/15/60 秒与暂停） */
const REFRESH_OPTIONS = [
  { label: '1 秒', value: '1000' },
  { label: '3 秒', value: '3000' },
  { label: '5 秒', value: '5000' },
  { label: '15 秒', value: '15000' },
  { label: '60 秒', value: '60000' },
  { label: '暂停', value: 'pause' },
]
const refreshRate = computed<string>({
  get: () => (market.isPaused ? 'pause' : String(market.pollIntervalMs)),
  set: (v) => market.setPollInterval(v === 'pause' ? 0 : Number(v)),
})

function isActive(path: string) {
  if (path === '/portfolio' && route.name === 'trade-plan') return true
  return route.path.startsWith(path)
}

/* 用户菜单 */
const showUserMenu = ref(false)
const menuRef = ref<HTMLElement | null>(null)

function toggleMenu() {
  showUserMenu.value = !showUserMenu.value
}

function closeMenu(e: MouseEvent) {
  if (menuRef.value && !menuRef.value.contains(e.target as Node)) {
    showUserMenu.value = false
  }
}

function logout() {
  showUserMenu.value = false
  auth.logout()
  router.replace('/login')
}

const displayName = computed(() => auth.user?.display_name || auth.user?.email || '用户')

onMounted(() => {
  document.addEventListener('click', closeMenu, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', closeMenu, true)
})
</script>

<template>
  <header class="masthead">
    <div class="masthead-left">
      <router-link to="/" class="brand">
        <span class="brand-mark">FG</span>
        <strong class="brand-name">FINANCE GOD</strong>
      </router-link>
      <nav class="nav" aria-label="栏目导航">
        <router-link
          v-for="item in NAV_ITEMS"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          {{ item.label }}
        </router-link>
      </nav>
    </div>
    <div class="masthead-right">
      <div class="edition-meta">
        <span>MARKET TERMINAL · EST. MMXXV</span>
        <span>{{ today }}</span>
      </div>
      <div class="status-indicator" :class="healthClass" :title="`后端状态: ${healthStatus}`">
        <span class="status-dot" />
        <span class="status-text">{{ healthStatus }}</span>
      </div>
      <label class="refresh-control" title="行情刷新频率">
        <span class="refresh-label">刷新</span>
        <select v-model="refreshRate" class="refresh-select" aria-label="行情刷新频率">
          <option v-for="o in REFRESH_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </label>
      <!-- 用户菜单 -->
      <div ref="menuRef" class="user-menu">
        <button class="user-trigger" :aria-expanded="showUserMenu" aria-label="用户菜单" @click.stop="toggleMenu">
          <span class="user-avatar">{{ displayName.charAt(0).toUpperCase() }}</span>
          <span class="user-label">{{ displayName }}</span>
        </button>
        <div v-if="showUserMenu" class="user-dropdown" role="menu">
          <router-link to="/settings" class="dropdown-item" role="menuitem" @click="showUserMenu = false">
            设置
          </router-link>
          <button class="dropdown-item" role="menuitem" @click="logout">
            退出登录
          </button>
        </div>
      </div>
    </div>
  </header>
</template>

<style scoped>
.masthead {
  grid-area: masthead;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px 0 0;
  border-bottom: 4px double var(--rule);
  position: relative;
}
.masthead::after {
  content: "";
  position: absolute;
  left: 0; right: 0; bottom: -2px;
  height: 1px;
  background: var(--risk);
  opacity: 0.76;
}

.masthead-left {
  display: flex;
  align-items: center;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
}
.masthead-left::-webkit-scrollbar { display: none; }

.brand {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  flex-shrink: 0;
  padding: 0 18px 0 20px;
}
.brand-mark {
  display: grid;
  place-items: center;
  width: 30px; height: 30px;
  border: 1px solid var(--ink);
  background: transparent;
  color: var(--ink);
  font-family: var(--font-numeric);
  font-size: 15px;
  font-weight: 700;
}
.brand-name {
  font-family: var(--font-numeric);
  font-size: 23px;
  font-weight: 900;
  letter-spacing: 0.06em;
  white-space: nowrap;
}

.nav {
  display: flex;
  align-items: center;
  gap: 0;
  white-space: nowrap;
}
.nav-item {
  padding: 0 10px;
  line-height: 72px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--muted-ink);
  transition: color 0.18s;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
}
.nav-item:hover {
  color: var(--ink);
}
.nav-item.active {
  color: var(--risk);
  font-weight: 900;
  border-bottom-color: var(--risk);
}

.masthead-right {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  gap: 9px;
}

.edition-meta {
  display: grid;
  justify-items: end;
  gap: 2px;
  color: var(--muted-ink);
  font-family: var(--font-numeric);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.11em;
  line-height: 1.25;
  text-transform: uppercase;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid var(--rule);
  font-size: 11px;
  font-weight: 700;
}
.status-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--muted-ink);
}
.status-ok .status-dot { background: var(--positive); }
.status-ok .status-text { color: var(--positive); }
.status-down .status-dot { background: var(--risk); }
.status-down .status-text { color: var(--risk); }
.status-pending .status-text { color: var(--muted-ink); }

.refresh-control {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--muted-ink);
}
.refresh-label {
  letter-spacing: 0.04em;
}
.refresh-select {
  padding: 3px 6px;
  background: var(--paper-light);
  border: 1px solid var(--rule);
  color: var(--ink);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.refresh-select:focus-visible {
  outline: 2px solid var(--selection, #2563eb);
  outline-offset: 1px;
}

.user-menu {
  position: relative;
}
.user-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  background: transparent;
  border: 1px solid var(--rule);
  color: var(--ink);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.18s;
}
.user-trigger:hover {
  border-color: var(--ink);
}
.user-avatar {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  background: var(--ink);
  color: var(--paper-light);
  font-family: var(--font-numeric);
  font-size: 13px;
  font-weight: 700;
}
.user-label {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  min-width: 160px;
  background: var(--paper-light);
  border: 1px solid var(--rule);
  box-shadow: var(--shadow);
  z-index: 100;
  display: grid;
}
.dropdown-item {
  display: block;
  width: 100%;
  padding: 10px 16px;
  background: transparent;
  border: 0;
  color: var(--ink);
  font-size: 13px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  text-decoration: none;
  transition: background 0.15s;
}
.dropdown-item:hover {
  background: var(--faint-rule);
}
.dropdown-item + .dropdown-item {
  border-top: 1px solid var(--faint-rule);
}

@media (max-width: 1279px) {
  .brand {
    gap: 7px;
    padding-inline: 10px 8px;
  }
  .brand-mark { width: 26px; height: 26px; font-size: 12px; }
  .brand-name { font-size: 18px; }
  .nav-item { padding-inline: 6px; font-size: 12px; }
  .masthead-right { gap: 4px; }
  .edition-meta,
  .refresh-label,
  .user-label { display: none; }
  .status-indicator,
  .user-trigger { padding-inline: 6px; }
}
</style>
