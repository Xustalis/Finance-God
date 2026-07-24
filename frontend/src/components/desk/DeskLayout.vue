<script setup lang="ts">
/**
 * DeskLayout — 报纸式布局壳
 * 报头 + 左栏 / 主栏 / 右栏 + 底栏
 * 1440px 标准分栏：~20% / ~58% / ~22%
 */
import Masthead from './Masthead.vue'
import BottomRail from './BottomRail.vue'
import { useDeskLayoutPreference, type DeskPanel } from '@/composables/useDeskLayoutPreference'

defineSlots<{
  left(): unknown
  main(): unknown
  right(): unknown
}>()

const { panels, storageError, layoutStatus, togglePanel, resetLayout } = useDeskLayoutPreference()

const panelLabels: Record<DeskPanel, string> = {
  left: '标的栏',
  right: '摘要栏',
  bottom: '底部栏',
}

function toggleLabel(panel: DeskPanel) {
  return `${panels[panel] ? '隐藏' : '显示'}${panelLabels[panel]}`
}
</script>

<template>
  <div
    class="desk-page"
    :class="{
      'left-hidden': !panels.left,
      'right-hidden': !panels.right,
      'bottom-hidden': !panels.bottom,
    }"
  >
    <Masthead />
    <nav class="layout-toolbar" aria-label="交易台布局">
      <span class="layout-toolbar__label">工作区</span>
      <button
        v-for="panel in (['left', 'right', 'bottom'] as DeskPanel[])"
        :key="panel"
        type="button"
        class="layout-button"
        :aria-pressed="panels[panel]"
        :data-testid="`toggle-${panel}-panel`"
        @click="togglePanel(panel)"
      >
        {{ toggleLabel(panel) }}
      </button>
      <button type="button" class="layout-button reset-button" data-testid="reset-layout" @click="resetLayout">
        重置布局
      </button>
      <span v-if="storageError" class="layout-message layout-message--error" role="alert">{{ storageError }}</span>
      <span v-else-if="layoutStatus" class="layout-message" role="status">{{ layoutStatus }}</span>
    </nav>
    <aside v-show="panels.left" class="desk-left" aria-label="选择与比较">
      <slot name="left" />
    </aside>
    <main class="desk-main">
      <slot name="main" />
    </main>
    <aside v-show="panels.right" class="desk-right" aria-label="摘要与证据">
      <slot name="right" />
    </aside>
    <BottomRail v-show="panels.bottom" />
  </div>
</template>

<style scoped>
.desk-page {
  --desk-left-width: 248px;
  --desk-right-width: 244px;
  --desk-bottom-height: 136px;

  display: grid;
  width: 100%;
  min-height: 100vh;
  overflow: hidden;
  grid-template:
    "masthead masthead masthead" 76px
    "toolbar  toolbar  toolbar"  34px
    "left     main     right"    minmax(510px, calc(100vh - 246px))
    "bottom   bottom   bottom"   var(--desk-bottom-height)
    / var(--desk-left-width) minmax(0, 1fr) var(--desk-right-width);
  border-top: 6px solid var(--ink);
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

.desk-page.left-hidden { --desk-left-width: 0px; }
.desk-page.right-hidden { --desk-right-width: 0px; }
.desk-page.bottom-hidden { --desk-bottom-height: 0px; }

.layout-toolbar {
  grid-area: toolbar;
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  overflow-x: auto;
  border-bottom: 1px solid var(--rule);
  background: var(--paper-light);
  white-space: nowrap;
}

.layout-toolbar__label {
  margin-right: 4px;
  font-size: 0.72rem;
  font-weight: 900;
  letter-spacing: 0.1em;
}

.layout-button {
  min-height: 28px;
  padding: 2px 9px;
  border: 1px solid var(--rule);
  color: var(--ink);
  background: transparent;
  font-size: 0.75rem;
  font-weight: 750;
}

.layout-button:hover {
  background: rgb(33 26 18 / 7%);
}

.reset-button {
  border-color: transparent;
  border-bottom-color: var(--ink);
}

.layout-message {
  margin-left: auto;
  overflow: hidden;
  color: var(--muted-ink);
  font-size: 0.72rem;
  text-overflow: ellipsis;
}

.layout-message--error {
  color: var(--risk);
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
  padding: 10px 12px 18px;
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

@media (max-width: 1279px) {
  .desk-page {
    --desk-left-width: 208px;
    --desk-right-width: 232px;
  }

  .desk-page.left-hidden {
    --desk-left-width: 0px;
  }

  .desk-page.right-hidden {
    --desk-right-width: 0px;
  }

  .desk-main {
    padding-inline: 10px;
  }
}
</style>
