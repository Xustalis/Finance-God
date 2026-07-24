<script setup lang="ts">
/**
 * 应用壳：常驻 AI 侧栏作为骨架的一部分渲染在交易类路由右侧（规范 §9.2）。
 * 侧栏不使用遮罩、不抢占模态焦点；主体按侧栏展开/收起宽度预留空间。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AiSidebar from '@/components/desk/AiSidebar.vue'
import DesktopWidthNotice from '@/components/DesktopWidthNotice.vue'
import { useAiContextStore, type AiScope } from '@/stores/aiContext'
import { useMarketStore } from '@/stores/market'

const MINIMUM_DESKTOP_WIDTH = 1024
const viewportWidth = ref(typeof window === 'undefined' ? MINIMUM_DESKTOP_WIDTH : window.innerWidth)
const route = useRoute()
const ai = useAiContextStore()
const market = useMarketStore()

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

const showSidebar = computed(() => route.meta.requiresAuth === true)

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
    <div v-if="showSidebar" class="desktop-app-shell">
      <div class="app-shell">
        <RouterView />
      </div>
      <div class="ai-dock" :class="{ collapsed: ai.collapsed }">
        <AiSidebar />
      </div>
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
.desktop-app-shell {
  min-height: 100vh;
  display: flex;
  align-items: stretch;
  background: var(--paper);
}
.app-shell {
  min-height: 100vh;
  min-width: 0;
  flex: 1 1 auto;
}
.ai-dock {
  position: sticky;
  top: 0;
  flex: 0 0 296px;
  width: 296px;
  height: 100vh;
  overflow: hidden;
}
.ai-dock.collapsed {
  flex-basis: 44px;
  width: 44px;
}
</style>
