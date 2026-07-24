<script setup lang="ts">
/**
 * UnavailablePanel — 通用占位/不可用面板
 * 用于尚未实现的页面，保持视觉一致性
 */
defineProps<{
  title: string
  subtitle: string
  kicker: string
  detail?: string
}>()
</script>

<template>
  <div class="unavailable-panel">
    <span class="kicker">{{ kicker }}</span>
    <h1 class="title">{{ title }}</h1>
    <p class="subtitle">{{ subtitle }}</p>
    <p v-if="detail" class="detail">{{ detail }}</p>
    <div class="status-line">
      <span class="status-dot" />
      <span>功能开发中</span>
    </div>
  </div>
</template>

<style scoped>
.unavailable-panel {
  min-height: 55vh;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 0.75rem;
  text-align: center;
  padding: 2rem;
}
.kicker {
  color: var(--risk);
  font-size: 0.78rem;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.title {
  font-size: clamp(2rem, 4vw, 3rem);
  font-weight: 700;
  margin: 0;
}
.subtitle {
  color: var(--muted-ink);
  font-size: 1.1rem;
  max-width: 420px;
  margin: 0;
}
.detail {
  color: var(--muted-ink);
  font-size: 0.9rem;
  max-width: 520px;
  margin: 0;
  padding: 0.7rem 1rem;
  border-left: 3px solid var(--rule);
  text-align: left;
}
.status-line {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted-ink);
  font-size: 0.85rem;
  margin-top: 0.5rem;
}
.status-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--muted-ink);
}
</style>
