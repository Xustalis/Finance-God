<script setup lang="ts">
/**
 * 应用壳：交易类路由采用左/右对半（50/50）分屏——左侧为交易台（随路由
 * 变化），右侧为常驻 AI Agent（规范 §9.2）。两栏严格区分、占比相等。
 * AI 栏可收起为窄栏作为次要选项；不使用遮罩、不抢占模态焦点。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AiSidebar from '@/components/desk/AiSidebar.vue'
import NotificationToast from '@/components/desk/NotificationToast.vue'
import DesktopWidthNotice from '@/components/DesktopWidthNotice.vue'
import { useAiContextStore, type AiScope } from '@/stores/aiContext'
import { useMarketStore } from '@/stores/market'
import { useNotificationsStore } from '@/stores/notifications'

const MINIMUM_DESKTOP_WIDTH = 1024
const viewportWidth = ref(typeof window === 'undefined' ? MINIMUM_DESKTOP_WIDTH : window.innerWidth)
const route = useRoute()
const ai = useAiContextStore()
const market = useMarketStore()
const notifications = useNotificationsStore()

/** 构建用户画像阶段（访谈与画像报告）不展示 AI 侧栏与行情提醒。 */
const PROFILE_BUILDING_ROUTES = new Set(['onboarding', 'report'])

/** 交易类路由的默认 AI 上下文；具体标的由页面进一步细化。 */
const ROUTE_CONTEXT: Record<string, { scope: AiScope; subject: string | null; label: string | null }> = {
  onboarding: { scope: 'profile', subject: '投资画像访谈', label: '当前访谈' },
  report: { scope: 'profile', subject: '投资画像报告', label: '最新投资画像' },
  overview: { scope: 'market', subject: 'A股市场', label: '市场总览' },
  markets: { scope: 'market', subject: 'A股市场', label: '行情总览' },
  desk: { scope: 'symbol', subject: null, label: null },
  portfolio: { scope: 'portfolio', subject: '仿真组合', label: '仿真组合' },
  'trade-plan': { scope: 'portfolio', subject: '交易计划', label: '正在加载交易计划' },
  orders: { scope: 'orders', subject: '仿真订单执行', label: '订单执行' },
  reviews: { scope: 'reviews', subject: '交易复盘', label: '交易复盘' },
  data: { scope: 'data', subject: 'PandaData 数据目录', label: '数据目录' },
  settings: { scope: 'settings', subject: '仿真账户与工作区设置', label: '账户与工作区设置' },
}

const showSidebar = computed(
  () => route.meta.requiresAuth === true && !PROFILE_BUILDING_ROUTES.has(String(route.name)),
)

// 登录（受保护路由）期间轮询行情异动通知；离开时停止。
watch(
  showSidebar,
  (authed, was) => {
    if (authed && !was) notifications.startPolling()
    else if (!authed && was) notifications.stopPolling()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (showSidebar.value) notifications.stopPolling()
})

function updateViewportWidth() {
  viewportWidth.value = window.innerWidth
  ai.syncViewportDefault(viewportWidth.value)
}

onMounted(() => {
  updateViewportWidth()
  window.addEventListener('resize', updateViewportWidth)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewportWidth)
})

watch(
  [() => route.name, () => market.contextSymbol],
  ([name, contextSymbol]) => {
    const key = typeof name === 'string' ? name : ''
    const ctx = ROUTE_CONTEXT[key]
    if (!ctx) return
    if ((key === 'markets' || key === 'desk') && contextSymbol) {
      ai.setContext({
        scope: 'symbol',
        subject: contextSymbol,
        label: `当前标的 · ${contextSymbol}`,
      })
      return
    }
    ai.setContext(ctx)
  },
  { immediate: true },
)
</script>

<template>
  <template v-if="viewportWidth >= MINIMUM_DESKTOP_WIDTH">
    <div v-if="showSidebar" class="desktop-app-shell" :class="{ 'ai-collapsed': ai.collapsed }">
      <div class="app-shell desk-pane">
        <RouterView />
      </div>
      <div class="ai-dock" :class="{ collapsed: ai.collapsed }">
        <AiSidebar />
      </div>
      <NotificationToast />
    </div>
    <div v-else class="app-shell">
      <RouterView />
    </div>
  </template>
  <DesktopWidthNotice
    v-else
    :current-width="viewportWidth"
    :minimum-width="MINIMUM_DESKTOP_WIDTH"
  />
</template>

<style scoped>
/* 交易类路由：左/右各占 50%。AI 栏收起时左侧占满、右侧退为窄栏。 */
.desktop-app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  align-items: stretch;
  background: var(--paper);
}
.desktop-app-shell.ai-collapsed {
  grid-template-columns: minmax(0, 1fr) 44px;
}
.app-shell {
  min-height: 100vh;
  min-width: 0;
}
.desk-pane {
  min-width: 0;
  border-right: 1px solid var(--rule, #d8cfbb);
}
.ai-dock {
  position: sticky;
  top: 0;
  min-width: 0;
  height: 100vh;
  overflow: hidden;
}
</style>
