<script setup lang="ts">
/**
 * DeskLayout — 报纸式布局壳
 * 报头 + 左栏 / 主栏 / 右栏 + 底栏
 * 1440px 标准分栏：~20% / ~58% / ~22%
 */
import Masthead from './Masthead.vue'
import BottomRail from './BottomRail.vue'

defineSlots<{
  left(): unknown
  main(): unknown
  right(): unknown
}>()
</script>

<template>
  <div class="desk-page">
    <Masthead />
    <aside class="desk-left" aria-label="选择与比较">
      <slot name="left" />
    </aside>
    <main class="desk-main">
      <slot name="main" />
    </main>
    <aside class="desk-right" aria-label="摘要与证据">
      <slot name="right" />
    </aside>
    <BottomRail />
  </div>
</template>

<style scoped>
.desk-page {
  display: grid;
  min-height: 100vh;
  grid-template:
    "masthead masthead masthead" 64px
    "left     main     right"    minmax(520px, calc(100vh - 214px))
    "bottom   bottom   bottom"   150px
    / 282px minmax(0, 1fr) 290px;
  border-top: 10px solid var(--ink);
  background-color: var(--paper);
  background-image:
    radial-gradient(circle at 52% 38%, rgb(255 249 232 / 38%), transparent 58%),
    url("/textures/newsprint-paper.webp");
  background-blend-mode: normal, multiply;
  background-repeat: no-repeat, repeat;
  background-size: cover, 1200px 1200px;
  font-variant-numeric: tabular-nums lining-nums;
  isolation: isolate;
}

.desk-left {
  grid-area: left;
  min-width: 0;
  border-right: 1px solid var(--rule);
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: thin;
  scrollbar-color: var(--faint-rule) transparent;
}

.desk-main {
  grid-area: main;
  min-width: 0;
  padding: 22px 20px 32px;
  overflow-y: auto;
}

.desk-right {
  grid-area: right;
  min-width: 0;
  border-left: 1px solid var(--rule);
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: thin;
  scrollbar-color: var(--faint-rule) transparent;
}

@media (max-width: 1100px) {
  .desk-page {
    grid-template:
      "masthead masthead" 64px
      "left     main"     minmax(420px, calc(100vh - 214px))
      "bottom   bottom"   150px
      / 240px minmax(0, 1fr);
  }
  .desk-right { display: none; }
}
</style>
