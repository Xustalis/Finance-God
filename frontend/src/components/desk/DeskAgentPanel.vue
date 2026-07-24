<script setup lang="ts">
import { computed, ref } from 'vue'
import { useTradingDeskStore } from '@/stores/tradingDesk'

defineProps<{
  collapsed: boolean
}>()

defineEmits<{
  toggle: []
  'reset-layout': []
}>()

const desk = useTradingDeskStore()
const prompt = ref('')
const workflowExpanded = ref(true)
const sectionTitle = computed(() => ({ information: '总览', portfolio: '持仓', watchlist: '自选', trading: '交易' }[desk.section]))

function send(text = prompt.value) {
  const intent = text.trim()
  if (!intent) return
  prompt.value = ''
  workflowExpanded.value = true
  void desk.runWorkflow(intent)
}

function syncWorkflowExpanded(event: Event) {
  workflowExpanded.value = (event.currentTarget as HTMLDetailsElement).open
}
</script>

<template>
  <aside class="desk-agent" :class="{ 'is-collapsed': collapsed }" aria-label="交易 Agent">
    <button
      v-if="collapsed"
      class="agent-rail"
      type="button"
      aria-label="展开交易 Agent"
      @click="$emit('toggle')"
    >
      <span>AI AGENT</span>
      <small>{{ sectionTitle }} · {{ desk.symbol }}</small>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>
    </button>
    <div v-else class="agent-expanded">
      <header class="agent-heading">
        <div><h2>AI AGENT</h2><p>上下文 · {{ sectionTitle }} · {{ desk.symbol }} · v{{ desk.contextVersion }}</p></div>
        <div class="agent-layout-actions">
          <button type="button" @click="$emit('reset-layout')">重置布局</button>
          <button type="button" aria-label="收起交易 Agent" @click="$emit('toggle')">收起</button>
        </div>
      </header>
      <section class="agent-thread" aria-live="polite">
      <p class="agent-ready">输入问题后将创建可审计的后端工作流。只呈现服务端工作流回执与真实错误，不生成本地结论。</p>
      <details v-if="desk.activeWorkflow || desk.workflowError" class="workflow-detail" :open="workflowExpanded" @toggle="syncWorkflowExpanded">
        <summary><span>后端工作流</span><small>{{ desk.workflowError || desk.activeWorkflow?.status }}</small></summary>
        <p v-if="desk.activeWorkflow">{{ desk.activeWorkflow.workflow_key }} · {{ desk.activeWorkflow.run_id }}</p>
        <p v-if="desk.activeWorkflow?.status === 'queued'">后端已接受任务，等待执行器开始处理。</p>
        <p v-if="desk.workflowError" class="data-error">{{ desk.workflowError }}</p>
        <button v-if="desk.activeWorkflow" class="refresh-button" type="button" @click="desk.refreshWorkflow">查询状态</button>
      </details>
      </section>
      <form class="agent-composer" @submit.prevent="send()">
        <div class="quick-commands"><button v-for="command in desk.quickCommands" :key="command" type="button" @click="send(command)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.5a7.5 7.5 0 0 1-8 7.48 8.2 8.2 0 0 1-3.2-.72L4 20l1.3-4.1A7.5 7.5 0 1 1 20 11.5Z"/></svg>{{ command }}</button></div>
        <div class="agent-input"><textarea v-model="prompt" aria-label="向交易 Agent 输入指令" placeholder="例如：分析当前市场，或帮我筛选机会"></textarea><button type="submit" aria-label="调用后端工作流"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m21 3-7 18-4-8-8-4Z"/><path d="m10 13 4-4"/></svg></button></div>
      </form>
    </div>
  </aside>
</template>
