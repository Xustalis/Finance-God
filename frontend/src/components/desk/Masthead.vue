<script setup lang="ts">
/**
 * Masthead—报头：品牌、栏目导航、状态、日期、用户菜单
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell } from 'lucide-vue-next'
import { useMarketStore } from '@/stores/market'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import { formatPercent } from '@/types/desk'

const route = useRoute()
const router = useRouter()
const market = useMarketStore()
const auth = useAuthStore()
const notifications = useNotificationsStore()

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

/* 提醒中心（行情异动历史，可翻看与标记已读） */
const showAlertCenter = ref(false)
const alertCenterRef = ref<HTMLElement | null>(null)

function toggleAlertCenter() {
  showAlertCenter.value = !showAlertCenter.value
}

function closeAlertCenter(e: MouseEvent) {
  if (alertCenterRef.value && !alertCenterRef.value.contains(e.target as Node)) {
    showAlertCenter.value = false
  }
}

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
  document.addEventListener('click', closeAlertCenter, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', closeMenu, true)
  document.removeEventListener('click', closeAlertCenter, true)
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
      <!-- 提醒中心 -->
      <div ref="alertCenterRef" class="alert-center">
        <button
          class="alert-trigger"
          :aria-expanded="showAlertCenter"
          :aria-label="`提醒中心，${notifications.unreadCount} 条未读行情异动`"
          @click.stop="toggleAlertCenter"
        >
          <Bell :size="16" aria-hidden="true" />
          <span
            v-if="notifications.unreadCount > 0"
            class="alert-badge"
            aria-hidden="true"
          >{{ notifications.unreadCount > 99 ? '99+' : notifications.unreadCount }}</span>
        </button>
        <div v-if="showAlertCenter" class="alert-dropdown" role="dialog" aria-label="提醒中心">
          <header class="alert-dropdown-head">
            <strong>行情异动提醒</strong>
            <button
              v-if="notifications.alerts.length > 0"
              type="button"
              class="alert-mark-all"
              @click="notifications.acknowledgeAll()"
            >全部已读</button>
          </header>
          <p v-if="notifications.alerts.length === 0" class="alert-empty">
            暂无行情异动。服务端按间隔轮询检测，异动将在此汇总。
          </p>
          <ul v-else class="alert-list">
            <li
              v-for="alert in notifications.alerts"
              :key="alert.alert_id"
              class="alert-item"
              :class="{ unread: !notifications.isAcknowledged(alert.alert_id) }"
            >
              <div class="alert-item-head">
                <span class="alert-item-name">{{ alert.name }}</span>
                <span class="alert-item-move" :class="alert.kind">
                  {{ formatPercent(alert.change_percent) }}
                </span>
              </div>
              <p class="alert-item-message">{{ alert.message }}</p>
              <div class="alert-item-foot">
                <span class="alert-item-time">数据时点 {{ alert.provider_time }}</span>
                <button
                  v-if="!notifications.isAcknowledged(alert.alert_id)"
                  type="button"
                  class="alert-item-read"
                  @click="notifications.acknowledge(alert.alert_id)"
                >标记已读</button>
              </div>
            </li>
          </ul>
        </div>
      </div>
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
.alert-center {
  position: relative;
}
.alert-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 30px;
  background: transparent;
  border: 1px solid var(--rule);
  color: var(--ink);
  cursor: pointer;
}
.alert-trigger:focus-visible {
  outline: 2px solid var(--risk, #2d7dd2);
  outline-offset: 1px;
}
.alert-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--risk, #c0392b);
  color: #fff;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.alert-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  width: 320px;
  max-height: 60vh;
  overflow-y: auto;
  background: var(--paper, #fff);
  border: 1px solid var(--rule);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.14);
  z-index: 50;
}
.alert-dropdown-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line, #eee);
  font-size: 13px;
}
.alert-mark-all {
  background: transparent;
  border: none;
  color: var(--risk, #2d7dd2);
  font-size: 12px;
  cursor: pointer;
}
.alert-empty {
  margin: 0;
  padding: 16px 12px;
  font-size: 12px;
  color: var(--ink-soft, #999);
  line-height: 1.5;
}
.alert-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.alert-item {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line, #f0f0f0);
}
.alert-item.unread {
  background: var(--hover, rgba(45, 125, 210, 0.06));
}
.alert-item-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
}
.alert-item-name {
  font-size: 13px;
  font-weight: 600;
}
.alert-item-move {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  font-size: 12px;
}
.alert-item-move.surge {
  color: #c0392b;
}
.alert-item-move.plunge {
  color: #1f8a4c;
}
.alert-item-message {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink, #333);
}
.alert-item-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-top: 4px;
}
.alert-item-time {
  font-size: 11px;
  color: var(--ink-soft, #999);
}
.alert-item-read {
  background: transparent;
  border: none;
  color: var(--risk, #2d7dd2);
  font-size: 11px;
  cursor: pointer;
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
