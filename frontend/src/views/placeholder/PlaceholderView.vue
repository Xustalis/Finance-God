<script setup lang="ts">
/**
 * PlaceholderView — 通用占位页面
 * 通过路由 meta 传入标题信息
 */
import { useRoute } from 'vue-router'
import DeskLayout from '@/components/desk/DeskLayout.vue'
import UnavailablePanel from '@/components/desk/UnavailablePanel.vue'
import { useMarketStore } from '@/stores/market'
import { onMounted, onUnmounted } from 'vue'

const route = useRoute()
const market = useMarketStore()

onMounted(() => {
  market.startPolling()
  market.checkHealth()
})
onUnmounted(() => {
  market.stopPolling()
})
</script>

<template>
  <DeskLayout>
    <template #left>
      <section class="rail-section">
        <h2 class="section-title">
          <span>{{ (route.meta.pageLabel as string) || '页面' }}</span>
          <small>{{ (route.meta.pageKicker as string) || 'PAGE' }}</small>
        </h2>
        <div class="rail-empty">
          <span>此栏目正在建设</span>
        </div>
      </section>
    </template>

    <template #main>
      <UnavailablePanel
        :title="(route.meta.pageLabel as string) || '页面'"
        :subtitle="(route.meta.pageDesc as string) || '该功能正在开发中，敬请期待。'"
        :kicker="(route.meta.pageKicker as string) || 'COMING SOON'"
      />
    </template>

    <template #right>
      <section class="rail-section">
        <h2 class="section-title">
          <span>系统状态</span>
          <small>SYSTEM</small>
        </h2>
        <div class="rail-empty">
          <span>暂无可用信息</span>
        </div>
      </section>
    </template>
  </DeskLayout>
</template>

<style scoped>
.rail-section { padding: 0; }
.section-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 18px 18px 7px;
  border-bottom: 1px solid var(--rule);
  font-size: 15px;
  font-weight: 900;
  letter-spacing: 0.04em;
  margin: 0;
}
.section-title small {
  color: var(--muted-ink);
  font-family: var(--font-numeric);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.1em;
  white-space: nowrap;
}
.rail-empty {
  padding: 28px 18px;
  color: var(--muted-ink);
  font-size: 13px;
  text-align: center;
}
</style>
