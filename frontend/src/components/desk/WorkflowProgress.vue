<script setup lang="ts">
/**
 * 工作流进度面板（类 Codex 折叠）。
 * 右侧 agent 的“工作状态”即 Multi-Agent 运行的逐 agent 步骤：
 * - 运行中：显示进行中的指示（单次阻塞调用期间为不确定态，不伪造分步）。
 * - 完成：折叠为“完成 N/总 步”摘要，可展开查看每步结论与建议；
 *   步骤状态严格由运行事实派生（done / blocked），不生成默认结论。
 */
import { computed, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, Check, AlertTriangle, ArrowRight } from 'lucide-vue-next'
import { useAiContextStore } from '@/stores/aiContext'
import { useDeskCommandsStore } from '@/stores/deskCommands'
import { deriveWorkflowSteps } from '@/services/workflowSteps'
import { parseProposedActions } from '@/services/proposedActions'
import type { DeskAction } from '@/stores/deskCommands'

const ai = useAiContextStore()
const deskCommands = useDeskCommandsStore()

const progress = computed(() => deriveWorkflowSteps(ai.run))

/** 某条建议动作当前是否可在左侧执行（有对应注册处理器）。 */
function canRun(action: DeskAction | null): boolean {
  return action ? deskCommands.can(action.type) : false
}

/** 派发建议动作到左侧（仅安全非写入类；写操作永远经既有确认流程）。 */
function runAction(action: DeskAction | null): void {
  if (action) deskCommands.dispatch(action)
}
const isRunning = computed(() => ai.status === 'running')
const isDone = computed(() => ai.status === 'done' && progress.value.total > 0)

/** 完成即折叠为摘要；用户可展开。运行状态切换时复位为折叠。 */
const expanded = ref(false)
watch(
  () => ai.status,
  (status) => {
    if (status !== 'done') expanded.value = false
  },
)
</script>

<template>
  <section
    v-if="isRunning || isDone"
    class="wf-progress"
    aria-label="工作流进度"
    data-test="workflow-progress"
  >
    <!-- 运行中：单次阻塞调用期间为不确定态 -->
    <div v-if="isRunning" class="wf-running" data-test="workflow-running">
      <span class="wf-dot" />
      <span>工作流进行中 · Multi-Agent 正在编排…</span>
    </div>

    <!-- 完成：折叠摘要 + 可展开 -->
    <template v-else>
      <button
        type="button"
        class="wf-summary"
        :aria-expanded="expanded"
        data-test="workflow-toggle"
        @click="expanded = !expanded"
      >
        <ChevronDown v-if="expanded" :size="14" aria-hidden="true" />
        <ChevronRight v-else :size="14" aria-hidden="true" />
        <span class="wf-summary-label">工作流进度</span>
        <span class="wf-summary-count">
          完成 {{ progress.doneCount }}/{{ progress.total }} 步
          <template v-if="progress.blockedCount > 0"> · {{ progress.blockedCount }} 步受阻</template>
        </span>
      </button>

      <ol v-if="expanded" class="wf-steps" data-test="workflow-steps">
        <li
          v-for="step in progress.steps"
          :key="step.agentId"
          class="wf-step"
          :class="step.status"
        >
          <div class="wf-step-head">
            <Check v-if="step.status === 'done'" :size="13" class="wf-icon done" aria-hidden="true" />
            <AlertTriangle v-else :size="13" class="wf-icon blocked" aria-hidden="true" />
            <code class="wf-agent">{{ step.agentId }}</code>
            <span class="wf-status-text">{{ step.status === 'done' ? '已完成' : '受阻' }}</span>
          </div>
          <p class="wf-reason">{{ step.reason }}</p>
          <p v-if="step.summary" class="wf-step-summary">{{ step.summary }}</p>
          <p v-if="step.missing.length" class="wf-missing">
            缺少：{{ step.missing.join('、') }}
          </p>
          <ul v-if="step.proposedActions.length" class="wf-actions">
            <li
              v-for="(link, i) in parseProposedActions(step.proposedActions)"
              :key="i"
              class="wf-action"
            >
              <span class="wf-action-text">{{ link.text }}</span>
              <button
                v-if="link.action && canRun(link.action)"
                type="button"
                class="wf-action-run"
                :data-test="`wf-action-run-${i}`"
                @click="runAction(link.action)"
              >
                <ArrowRight :size="12" aria-hidden="true" />
                {{ link.actionLabel }}
              </button>
            </li>
          </ul>
        </li>
      </ol>
    </template>
  </section>
</template>

<style scoped>
.wf-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.wf-running {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  font-size: 0.82rem;
  color: var(--muted-ink, #6b5f47);
  border: 1px dashed var(--rule, #cbbfa0);
  border-radius: 3px;
}
.wf-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted-ink, #6b5f47);
  animation: wf-pulse 1.1s ease-in-out infinite;
}
@keyframes wf-pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .wf-dot { animation: none; }
}
.wf-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 8px;
  font: inherit;
  font-size: 0.8rem;
  text-align: left;
  cursor: pointer;
  color: var(--ink, #241d12);
  background: var(--paper-2, #fbf6e9);
  border: 1px solid var(--rule, #cbbfa0);
  border-radius: 3px;
}
.wf-summary-label { font-weight: 700; }
.wf-summary-count {
  margin-left: auto;
  color: var(--muted-ink, #6b5f47);
  font-variant-numeric: tabular-nums;
}
.wf-steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.wf-step {
  padding: 6px 8px;
  border-left: 2px solid var(--rule, #cbbfa0);
}
.wf-step.done { border-left-color: var(--gain, #2f7d32); }
.wf-step.blocked { border-left-color: var(--risk, #9a2c2c); }
.wf-step-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.wf-icon.done { color: var(--gain, #2f7d32); }
.wf-icon.blocked { color: var(--risk, #9a2c2c); }
.wf-agent { font-size: 0.74rem; font-weight: 700; color: var(--ink, #241d12); }
.wf-status-text {
  margin-left: auto;
  font-size: 0.7rem;
  color: var(--muted-ink, #6b5f47);
}
.wf-reason,
.wf-step-summary,
.wf-missing {
  margin: 3px 0 0;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--muted-ink, #6b5f47);
}
.wf-step-summary { color: var(--ink, #241d12); }
.wf-missing { color: var(--risk, #9a2c2c); }
.wf-actions {
  margin: 4px 0 0;
  padding-left: 16px;
  font-size: 0.78rem;
  color: var(--ink, #241d12);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.wf-action {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.wf-action-text { min-width: 0; }
.wf-action-run {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font: inherit;
  font-size: 0.74rem;
  font-weight: 700;
  cursor: pointer;
  color: var(--ink, #241d12);
  background: transparent;
  border: 1px solid var(--ink, #241d12);
  border-radius: 2px;
  padding: 1px 6px;
}
.wf-action-run:hover { color: var(--risk, #9a2c2c); border-color: var(--risk, #9a2c2c); }
.wf-action-run:focus-visible { outline: 2px solid var(--risk, #9a2c2c); outline-offset: 1px; }
</style>
