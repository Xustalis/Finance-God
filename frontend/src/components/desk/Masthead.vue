<script setup lang="ts">
/**
 * Masthead — 报头：品牌、栏目导航、状态、日期
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useMarketStore } from '@/stores/market'

const route = useRoute()
const market = useMarketStore()

const NAV_ITEMS = [
  { label: '总览', path: '/overview' },
  { label: '行情', path: '/markets' },
  { label: '交易台', path: '/desk' },
  { label: '组合', path: '/portfolio' },
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

function isActive(path: string) {
  return route.path.startsWith(path)
}
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
    </div>
  </header>
</template>

<style scoped>
.masthead {
  grid-area: masthead;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 17px 0 0;
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
  gap: 0.6rem;
  flex-shrink: 0;
  padding: 0 18px 0 20px;
}
.brand-mark {
  display: grid;
  place-items: center;
  width: 36px; height: 36px;
  background: var(--ink);
  color: var(--paper-light);
  font-family: var(--font-numeric);
  font-size: 15px;
  font-weight: 700;
}
.brand-name {
  font-size: 18px;
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
  padding: 0 14px;
  line-height: 60px;
  font-size: 14px;
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
  gap: 16px;
}

.edition-meta {
  display: grid;
  justify-items: end;
  gap: 2px;
  color: var(--muted-ink);
  font-family: var(--font-numeric);
  font-size: 9px;
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
</style>
