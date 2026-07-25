<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { Mic, MicOff, Phone, PhoneOff } from 'lucide-vue-next'
import { useTradingDeskStore } from '@/stores/tradingDesk'
import { isDeskCapabilityEnabled } from '@/services/tradingDesk'
import { useRealtimeVoice } from '@/composables/useRealtimeVoice'

const desk = useTradingDeskStore()
const voiceSession = reactive(useRealtimeVoice())
const prompt = ref('')
const historyOpen = ref(false)
const historyStatus = ref('')
const thread = ref<HTMLElement | null>(null)
const statusLabel = computed(() => {
  const status = desk.activeWorkflow?.status
  if (!status) return '等待指令'
  return {
    queued: '排队中',
    running: '执行中',
    completed: '已完成',
    attention_required: '需要关注',
    failed: '失败',
    timed_out: '超时',
    blocked: '已阻断',
    cancel_requested: '请求取消',
    cancelling: '取消中',
    cancelled: '已取消',
    expired: '已过期',
  }[status]
})
const progressLabel = computed(() => {
  const progress = desk.activeWorkflowProgress
  if (!progress) return null
  return `${progress.completed_node_artifact_count} / ${progress.total_node_count} 个节点产物`
})
const workflowNodes = computed(() => desk.activeWorkflowProgress?.nodes ?? [])
const visibleWorkflowNodes = computed(() => workflowNodes.value.filter((node) => (
  node.node_id !== 'planner' && node.node_id !== 'artifact_finalize'
)))
const workflowCreateReady = computed(() => isDeskCapabilityEnabled(desk.deskCapabilities, 'workflow_create'))
const workflowWorkerReady = computed(() => isDeskCapabilityEnabled(desk.deskCapabilities, 'workflow_worker'))
const agentAnswerReady = computed(() => isDeskCapabilityEnabled(desk.deskCapabilities, 'agent_answer'))
const canSubmit = computed(() => (
  desk.bootstrapStatus === 'ready'
  && Boolean(desk.serverContextVersion)
  && (
    agentAnswerReady.value
    || (workflowCreateReady.value && workflowWorkerReady.value)
  )
))
const capabilityBlockedReason = computed(() => {
  if (desk.bootstrapStatus === 'error') return desk.bootstrapError ?? '交易台上下文同步失败。'
  if (!workflowCreateReady.value && !agentAnswerReady.value) return '服务端未确认 Agent 或 workflow runtime 可用，暂不能执行任务。'
  if (!workflowWorkerReady.value && !agentAnswerReady.value) return '服务端未确认 Workflow Worker 正在运行，暂不能执行新任务。'
  return null
})
function send(text = prompt.value) {
  const intent = text.trim()
  if (!intent || !canSubmit.value) return
  prompt.value = ''
  void desk.submitAgentIntent(intent)
}

function appendVoiceTranscript(role: 'user' | 'assistant', text: string) {
  const base = {
    id: `voice-${role}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    kind: 'text' as const,
    createdAt: new Date().toISOString(),
    text,
  }
  desk.appendAgentMessage(role === 'user'
    ? { ...base, role: 'user' }
    : { ...base, role: 'assistant', status: 'complete' })
}

async function startVoice() {
  if (!desk.serverContextVersion) return
  await voiceSession.start({
    surface: 'desk',
    contextVersion: desk.serverContextVersion,
    onFinalTranscript: appendVoiceTranscript,
  })
}

function nodeRole(agentIds: string[], serviceId: string | null) {
  if (agentIds.length) {
    const id = agentIds[0]
    if (id.startsWith('tradingagents:')) return '研究员'
    if (id.startsWith('finrobot:')) return '研究员'
    if (id.startsWith('quantskills:')) return '量化监测'
    if (id === 'financegod:planner') return '规划器'
    return 'Agent'
  }
  if (serviceId === 'market_context.snapshot') return '行情服务'
  if (serviceId === 'workflow.input_quality_gate') return '质量门'
  return '系统服务'
}

function nodeActor(agentIds: string[], serviceId: string | null) {
  const id = agentIds[0]
  return {
    'tradingagents:market_analyst': '行情研究员',
    'tradingagents:sentiment_analyst': '情绪研究员',
    'tradingagents:news_analyst': '新闻研究员',
    'finrobot:library:Market_Analyst': '市场研究员',
    'quantskills:agent-market-regime-monitor': '市场状态监测',
    'tradingagents:conservative_debator': '保守派审阅',
    'tradingagents:research_manager': '研究经理',
    'tradingagents:portfolio_manager': '组合经理',
  }[id] ?? (
    serviceId === 'market_context.snapshot'
      ? 'PandaData 行情服务'
      : serviceId === 'workflow.input_quality_gate'
        ? '输入质量门'
        : nodeRole(agentIds, serviceId)
  )
}

function nodeStatus(status: string) {
  return {
    queued: '排队中',
    pending: '等待',
    running: '执行中',
    completed: '已完成',
    attention_required: '需要关注',
    failed: '失败',
    timed_out: '超时',
    blocked: '已阻断',
    cancel_requested: '请求取消',
    cancelling: '取消中',
    cancelled: '已取消',
    expired: '已过期',
    reused: '已复用',
  }[status] ?? status
}

function workflowStatus(status: string) {
  return {
    queued: '排队',
    running: '执行中',
    completed: '完成',
    attention_required: '待关注',
    failed: '失败',
    timed_out: '超时',
    blocked: '阻断',
    cancel_requested: '待取消',
    cancelling: '取消中',
    cancelled: '已取消',
    expired: '已过期',
  }[status] ?? status
}

function workflowReceiptTitle(status: string) {
  if (status === 'queued') return '正式任务已受理'
  if (status === 'running') return '正式任务已开始执行'
  if (status === 'completed') return '正式任务已完成'
  if (status === 'cancel_requested' || status === 'cancelling') return '正式任务正在取消'
  if (status === 'cancelled') return '正式任务已取消'
  return '正式任务已终止'
}

function workflowError(error: string) {
  return {
    deterministic_quality_gate_failed: '确定性输入校验未通过，请检查失败节点后重试。',
  }[error] ?? error
}

function archiveDate(value?: string) {
  if (!value) return '时间未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function openHistory() {
  historyOpen.value = true
  desk.closeHistoricalWorkflow()
  void desk.loadWorkflowHistory(true, historyStatus.value as never)
}

function closeHistory() {
  historyOpen.value = false
  desk.closeHistoricalWorkflow()
}

function reloadHistory() {
  void desk.loadWorkflowHistory(true, historyStatus.value as never)
}

function loadMoreHistory() {
  void desk.loadWorkflowHistory(false, historyStatus.value as never)
}

async function refreshExpandedWorkflow(event: Event, runId: string) {
  if (!(event.currentTarget as HTMLDetailsElement).open) return
  if (desk.activeWorkflow?.run_id === runId) {
    void desk.refreshWorkflow()
    return
  }
  if (desk.selectedHistoricalWorkflow?.run_id === runId) return
  await desk.loadWorkflowHistory(true, historyStatus.value as never)
  const run = desk.workflowHistory.find((item) => item.run_id === runId)
  if (run) await desk.openHistoricalWorkflow(run)
}

watch(() => desk.agentMessages.length, async () => {
  await nextTick()
  thread.value?.lastElementChild?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
})

let previewTimer: ReturnType<typeof setTimeout> | null = null
watch(prompt, (value) => {
  if (previewTimer) clearTimeout(previewTimer)
  previewTimer = setTimeout(() => {
    void desk.previewAgentIntent(value)
  }, 300)
})
</script>

<template>
  <aside class="desk-agent" aria-label="交易 Agent">
    <div class="agent-expanded">
      <header class="agent-heading">
        <h2>AI AGENT</h2>
        <button type="button" class="agent-history-trigger" @click="historyOpen ? closeHistory() : openHistory()">
          {{ historyOpen ? '返回对话' : '任务历史' }}
        </button>
      </header>
      <section v-if="historyOpen" class="workflow-history" aria-label="研究任务历史">
        <template v-if="desk.selectedHistoricalWorkflow">
          <header class="workflow-history-toolbar">
            <button type="button" class="refresh-button" @click="desk.closeHistoricalWorkflow">返回任务列表</button>
            <strong :class="`is-${desk.selectedHistoricalWorkflow.status}`">{{ workflowStatus(desk.selectedHistoricalWorkflow.status) }}</strong>
          </header>
          <p class="history-edition">RESEARCH ARCHIVE · 研究任务档案</p>
          <h3 class="history-article-title">{{ desk.selectedHistoricalWorkflow.request_intent || desk.selectedHistoricalWorkflow.workflow_key }}</h3>
          <dl class="workflow-meta">
            <div><dt>工作流</dt><dd>{{ desk.selectedHistoricalWorkflow.workflow_key }}</dd></div>
            <div><dt>创建时间</dt><dd>{{ archiveDate(desk.selectedHistoricalWorkflow.requested_at) }}</dd></div>
            <div><dt>标的</dt><dd>{{ desk.selectedHistoricalWorkflow.scope?.symbol || '—' }}</dd></div>
            <div><dt>来源任务</dt><dd>{{ desk.selectedHistoricalWorkflow.parent_run_id || '原始任务' }}</dd></div>
          </dl>
          <ol v-if="desk.selectedHistoricalProgress?.nodes?.length" class="history-node-list">
            <li v-for="node in desk.selectedHistoricalProgress?.nodes ?? []" :key="node.node_id">
              <span>{{ node.title }}</span><strong>{{ nodeStatus(node.status) }}</strong>
            </li>
          </ol>
          <p v-if="desk.selectedHistoricalProgress?.errors.length" class="data-error">
            {{ desk.selectedHistoricalProgress.errors.map(workflowError).join('；') }}
          </p>
          <section v-if="desk.selectedHistoricalEvidence" class="history-report">
            <h4>研究报告</h4>
            <p>{{ desk.selectedHistoricalEvidence.conclusion || '报告未提供结论。' }}</p>
          </section>
          <div
            v-if="['failed', 'timed_out', 'attention_required'].includes(desk.selectedHistoricalWorkflow.status)"
            class="history-actions"
          >
            <button type="button" class="secondary-button" :disabled="desk.workflowSubmitting" @click="desk.retryHistoricalWorkflow('full')">按原输入重试</button>
            <button type="button" class="primary-button compact" :disabled="desk.workflowSubmitting" @click="desk.retryHistoricalWorkflow('resume_failed')">从失败节点继续</button>
          </div>
        </template>
        <template v-else>
          <header class="workflow-history-toolbar">
            <div>
              <span>RESEARCH ARCHIVE</span>
              <h3>研究任务档案</h3>
            </div>
            <button type="button" class="refresh-button" @click="reloadHistory">刷新</button>
          </header>
          <label class="history-filter">
            <span>状态</span>
            <select v-model="historyStatus" @change="reloadHistory">
              <option value="">全部</option>
              <option value="queued">排队中</option>
              <option value="running">执行中</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
              <option value="timed_out">超时</option>
              <option value="cancelled">已取消</option>
            </select>
          </label>
          <p v-if="desk.workflowHistoryError" class="data-error">{{ desk.workflowHistoryError }}</p>
          <p v-else-if="desk.workflowHistoryLoading && !desk.workflowHistory.length" class="workflow-note">正在读取任务历史…</p>
          <p v-else-if="!desk.workflowHistory.length" class="workflow-note">暂无研究任务。</p>
          <div v-else class="workflow-history-table-wrap">
            <table class="workflow-history-table">
              <caption>按服务端记录时间倒序 · 点击任务标题打开对应 Agent 上下文</caption>
              <thead>
                <tr><th>研究事项</th><th>标的</th><th>归档时间</th><th>状态</th></tr>
              </thead>
              <tbody>
                <tr v-for="run in desk.workflowHistory" :key="run.run_id">
                  <th scope="row">
                    <button type="button" @click="desk.openHistoricalWorkflow(run)">
                      {{ run.request_intent || run.workflow_key }}
                    </button>
                  </th>
                  <td>{{ run.scope?.symbol || '全局' }}</td>
                  <td class="history-date">{{ archiveDate(run.requested_at || run.created_at) }}</td>
                  <td><span class="history-status" :class="`is-${run.status}`">{{ workflowStatus(run.status) }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <button
            v-if="desk.workflowHistoryCursor"
            type="button"
            class="refresh-button history-more"
            :disabled="desk.workflowHistoryLoading"
            @click="loadMoreHistory"
          >加载更多</button>
        </template>
      </section>

      <section v-if="!historyOpen && voiceSession.active" class="live-call desk-live-call" aria-label="实时语音通话">
        <header>
          <span class="live-indicator" aria-hidden="true"/>
          <strong>{{ voiceSession.statusText }}</strong>
          <small>StepAudio 2.5 Realtime</small>
        </header>
        <div class="live-transcripts" aria-live="polite">
          <article><span>你</span><p>{{ voiceSession.userTranscript || '正在等待你说话…' }}</p></article>
          <article><span>AI AGENT</span><p>{{ voiceSession.assistantTranscript || '—' }}</p></article>
        </div>
        <p class="workflow-note">实时行情、账户、工作流与交易动作仍以服务端回执为准。</p>
        <div class="live-actions">
          <button type="button" class="secondary-button" @click="voiceSession.toggleMute">
            <Mic v-if="voiceSession.muted" :size="18"/><MicOff v-else :size="18"/>
            {{ voiceSession.muted ? '取消静音' : '静音' }}
          </button>
          <button type="button" class="primary-button compact" @click="voiceSession.stop()">
            <PhoneOff :size="18"/>挂断
          </button>
        </div>
      </section>
      <section v-else-if="!historyOpen" ref="thread" class="agent-thread" aria-live="polite">
        <p v-if="desk.lastUiActionReceipt" class="workflow-note">
          左侧动作 · {{ desk.lastUiActionReceipt.action_id }} · {{ desk.lastUiActionReceipt.receipt }}
          <template v-if="desk.lastUiActionReceipt.reason"> · {{ desk.lastUiActionReceipt.reason }}</template>
        </p>
        <p v-if="desk.bootstrapStatus === 'loading'" class="workflow-note" role="status">
          正在同步交易台上下文，完成后即可提交任务。
        </p>
        <div v-else-if="desk.bootstrapStatus === 'error'" class="agent-bootstrap-error" role="alert">
          <p class="data-error">{{ capabilityBlockedReason }}</p>
          <button class="refresh-button" type="button" @click="desk.refreshBootstrap">重新连接</button>
        </div>
        <p v-else-if="capabilityBlockedReason" class="data-error" role="alert">{{ capabilityBlockedReason }}</p>

        <section v-if="desk.agentMessages.length" class="agent-execution" aria-label="Agent 消息">
          <article
            v-for="message in desk.agentMessages"
            :key="message.id"
            class="agent-chat-message"
            :class="[`is-${message.role}`, `is-${message.kind}`]"
            :aria-label="message.role === 'user' ? '用户消息' : message.kind === 'text' ? 'Agent 回复' : undefined"
          >
            <span>{{ message.role === 'user' ? '你' : 'AI AGENT' }}</span>

            <p v-if="message.kind === 'text'">
              <template v-if="message.status === 'pending' && message.chunks?.length">
                <span
                  v-for="(chunk, chunkIndex) in message.chunks"
                  :key="chunkIndex"
                  class="agent-stream-chunk"
                >{{ chunk }}</span>
              </template>
              <template v-else>{{ message.text }}</template>
              <span v-if="message.status === 'pending'" class="agent-stream-caret" aria-hidden="true"></span>
            </p>
            <p v-else-if="message.kind === 'error'" class="data-error" role="alert">{{ message.text }}</p>

            <template v-else-if="message.kind === 'workflow'">
              <details
                class="workflow-message-detail"
                :open="['queued', 'running', 'cancel_requested', 'cancelling'].includes(message.status)"
                @toggle="refreshExpandedWorkflow($event, message.runId)"
              >
                <summary class="agent-task-heading workflow-message-receipt">
                  <div>
                    <span>{{ workflowReceiptTitle(message.status) }}</span>
                    <small>{{ message.intent }}</small>
                  </div>
                  <div class="workflow-message-actions">
                    <strong>{{ nodeStatus(message.status) }}</strong>
                    <small>运行信息</small>
                  </div>
                </summary>
                <div class="workflow-message-body">
                  <template v-if="desk.activeWorkflow?.run_id === message.runId">
                    <div class="workflow-monitor-progress">
                      <span>{{ progressLabel ?? '等待服务端进度' }}</span>
                      <button class="refresh-button" type="button" @click="desk.refreshWorkflow">刷新状态</button>
                    </div>
                    <div v-if="visibleWorkflowNodes.length" class="agent-task-list workflow-monitor-nodes">
                      <article
                        v-for="node in visibleWorkflowNodes"
                        :key="node.node_id"
                        class="agent-task-card"
                        :class="`is-${node.status}`"
                      >
                        <div class="agent-task-icon" aria-hidden="true">{{ nodeRole(node.agent_ids, node.service_id).slice(0, 1) }}</div>
                        <div class="agent-task-copy">
                          <p>{{ nodeRole(node.agent_ids, node.service_id) }} · {{ nodeActor(node.agent_ids, node.service_id) }}</p>
                          <h3>{{ node.title }}</h3>
                        </div>
                        <span class="agent-task-status">{{ nodeStatus(node.status) }}</span>
                      </article>
                    </div>
                    <p v-else-if="desk.activeWorkflow.status === 'queued'" class="workflow-note">后端已接受任务，等待 Worker 领取。</p>
                    <p v-else-if="desk.activeWorkflow.status === 'running'" class="workflow-note">Worker 正在执行，等待首个节点状态落库。</p>
                    <p
                      v-else-if="!['completed', 'cancelled'].includes(desk.activeWorkflow.status)"
                      class="data-error"
                      role="alert"
                    >
                      工作流终止：{{ statusLabel }}
                      <template v-if="desk.activeWorkflowProgress?.errors.length">
                        · {{ desk.activeWorkflowProgress.errors.map(workflowError).join('；') }}
                      </template>
                    </p>
                    <details class="workflow-detail workflow-inspector">
                      <summary><span>执行记录与技术信息</span><small>可审计</small></summary>
                      <div class="workflow-ledger">
                        <dl class="workflow-meta">
                          <div><dt>工作流</dt><dd>{{ desk.activeWorkflow.workflow_key }}</dd></div>
                          <div><dt>状态</dt><dd>{{ statusLabel }}</dd></div>
                          <div><dt>进度</dt><dd>{{ progressLabel ?? '等待服务端进度' }}</dd></div>
                          <div><dt>修订</dt><dd>{{ desk.activeWorkflowProgress?.revision ?? desk.activeWorkflow.revision }}</dd></div>
                        </dl>
                        <button
                          v-if="['queued', 'running'].includes(desk.activeWorkflow.status)"
                          class="refresh-button risk-action"
                          type="button"
                          :disabled="desk.workflowSubmitting"
                          @click="desk.cancelActiveWorkflow"
                        >取消任务</button>
                      </div>
                    </details>
                  </template>
                  <template v-else>
                    <p
                      v-if="desk.workflowHistoryLoading && desk.selectedHistoricalWorkflow?.run_id !== message.runId"
                      class="workflow-note"
                    >正在读取任务运行信息…</p>
                    <template v-else-if="desk.selectedHistoricalWorkflow?.run_id === message.runId">
                      <div class="workflow-monitor-progress">
                        <span>
                          {{ desk.selectedHistoricalProgress
                            ? `${desk.selectedHistoricalProgress.completed_node_artifact_count} / ${desk.selectedHistoricalProgress.total_node_count} 个节点产物`
                            : '等待服务端进度' }}
                        </span>
                        <strong>{{ workflowStatus(desk.selectedHistoricalWorkflow.status) }}</strong>
                      </div>
                      <ol v-if="desk.selectedHistoricalProgress?.nodes?.length" class="history-node-list">
                        <li v-for="node in desk.selectedHistoricalProgress?.nodes ?? []" :key="node.node_id">
                          <span>{{ node.title }}</span><strong>{{ nodeStatus(node.status) }}</strong>
                        </li>
                      </ol>
                      <p v-if="desk.selectedHistoricalProgress?.errors.length" class="data-error" role="alert">
                        {{ desk.selectedHistoricalProgress.errors.map(workflowError).join('；') }}
                      </p>
                      <details class="workflow-detail workflow-inspector">
                        <summary><span>执行记录与技术信息</span><small>可审计</small></summary>
                        <dl class="workflow-meta">
                          <div><dt>工作流</dt><dd>{{ desk.selectedHistoricalWorkflow.workflow_key }}</dd></div>
                          <div><dt>状态</dt><dd>{{ workflowStatus(desk.selectedHistoricalWorkflow.status) }}</dd></div>
                          <div><dt>创建时间</dt><dd>{{ archiveDate(desk.selectedHistoricalWorkflow.requested_at) }}</dd></div>
                          <div><dt>修订</dt><dd>{{ desk.selectedHistoricalProgress?.revision ?? desk.selectedHistoricalWorkflow.revision }}</dd></div>
                        </dl>
                      </details>
                    </template>
                    <p v-else class="data-error" role="alert">
                      {{ desk.workflowHistoryError || '未能读取该任务的运行信息。' }}
                    </p>
                  </template>
                </div>
              </details>
            </template>

            <section v-else-if="message.kind === 'research_report'" class="agent-result agent-answer" aria-label="工作流产物">
              <header>
                <h3>研究报告</h3>
                <small>{{ message.evidence.provider }} · {{ message.evidence.generated_at }}</small>
              </header>
              <p v-if="message.evidence.conclusion" class="agent-conclusion">{{ message.evidence.conclusion }}</p>
              <div v-if="message.evidence.facts.length" class="agent-evidence-group">
                <h4>事实</h4>
                <ol>
                  <li v-for="claim in message.evidence.facts" :key="`${claim.author_agent_id}-${claim.statement}`">
                    <p>{{ claim.statement }}</p>
                    <small>{{ claim.author_agent_id || '服务端' }} · 引用 {{ claim.evidence_ids.join('、') }}</small>
                  </li>
                </ol>
              </div>
              <div v-if="message.evidence.inferences.length" class="agent-evidence-group">
                <h4>推断</h4>
                <ol>
                  <li v-for="claim in message.evidence.inferences" :key="`${claim.author_agent_id}-${claim.statement}`"><p>{{ claim.statement }}</p></li>
                </ol>
              </div>
              <div v-if="message.evidence.counterpoints.length || message.evidence.unknowns.length" class="agent-evidence-group">
                <h4>风险与未知项</h4>
                <ul>
                  <li v-for="item in [...message.evidence.counterpoints, ...message.evidence.unknowns]" :key="item">{{ item }}</li>
                </ul>
              </div>
              <details v-if="message.evidence.sources.length" class="agent-sources">
                <summary>来源（{{ message.evidence.sources.length }}）</summary>
                <ul>
                  <li v-for="source in message.evidence.sources" :key="source.identifier">
                    <strong>{{ source.source }}</strong><small>{{ source.identifier }}</small>
                    <p v-if="source.excerpt">{{ source.excerpt }}</p>
                  </li>
                </ul>
              </details>
            </section>

            <section v-else-if="message.kind === 'order_draft'" class="agent-order-bubble" aria-label="模拟订单草稿气泡">
              <header><h3>模拟订单草稿</h3><strong>{{ message.draft.draft.status }}</strong></header>
              <dl>
                <div><dt>标的</dt><dd>{{ message.draft.draft.instrument_id }}</dd></div>
                <div><dt>方向</dt><dd>{{ message.draft.draft.side }}</dd></div>
                <div><dt>数量</dt><dd>{{ message.draft.draft.quantity ?? '—' }}</dd></div>
                <div><dt>价格</dt><dd>{{ message.draft.draft.limit_price ?? message.draft.reference_price ?? '—' }}</dd></div>
              </dl>
              <p>订单尚未提交，需在交易区完成风控复核与独立确认。</p>
              <button class="refresh-button" type="button" @click="desk.setSection('trading')">前往复核</button>
            </section>

            <section v-else-if="message.kind === 'order_receipt'" class="agent-order-bubble" aria-label="模拟订单回执气泡">
              <header><h3>模拟订单回执</h3><strong>{{ message.order.status }}</strong></header>
              <dl>
                <div><dt>订单号</dt><dd>{{ message.order.order_id }}</dd></div>
                <div><dt>标的</dt><dd>{{ message.order.instrument_id }}</dd></div>
                <div><dt>方向</dt><dd>{{ message.order.side }}</dd></div>
                <div><dt>数量</dt><dd>{{ message.order.quantity }}</dd></div>
              </dl>
            </section>
          </article>
        </section>

      </section>

      <details v-if="!historyOpen && desk.queuedWorkflowIntents.length" class="workflow-detail queued-workflows">
        <summary>
          <span>待执行正式任务</span>
          <small>{{ desk.queuedWorkflowIntents.length }} 项</small>
        </summary>
        <ol>
          <li v-for="item in desk.queuedWorkflowIntents" :key="item.id">
            <span>{{ item.intent }}</span>
            <button type="button" class="refresh-button" @click="desk.removeQueuedWorkflow(item.id)">移出队列</button>
          </li>
        </ol>
      </details>

      <form v-if="!historyOpen && !voiceSession.active" class="agent-composer" @submit.prevent="send()">
        <div class="quick-command-toolbar">
          <span>{{ desk.quickCommandsLoading ? '正在生成下一步建议…' : '快捷指令' }}</span>
          <button
            type="button"
            :disabled="desk.quickCommandsLoading || !desk.serverContextVersion"
            @click="desk.rerollQuickCommands"
          >
            换一组
          </button>
        </div>
        <p v-if="desk.quickCommandsError" class="quick-commands-error" role="status">
          {{ desk.quickCommandsError }}
        </p>
        <div v-if="desk.quickCommands.length" class="quick-commands" aria-label="动态快捷指令">
          <button
            v-for="command in desk.quickCommands"
            :key="command"
            type="button"
            :disabled="!canSubmit"
            @click="send(command)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.5a7.5 7.5 0 0 1-8 7.48 8.2 8.2 0 0 1-3.2-.72L4 20l1.3-4.1A7.5 7.5 0 1 1 20 11.5Z"/></svg>
            {{ command }}
          </button>
        </div>
        <div class="agent-input">
          <textarea
            v-model="prompt"
            aria-label="向交易 Agent 输入指令"
            :disabled="!canSubmit"
            :placeholder="desk.workflowActive ? '任务执行中，仍可提问或加入新任务' : '输入研究问题或任务'"
          />
          <button
            class="agent-voice-button"
            type="button"
            aria-label="开始语音通话"
            :title="voiceSession.unavailableReason || '开始语音通话'"
            :disabled="!desk.serverContextVersion || !voiceSession.canStart"
            @click="startVoice"
          >
            <Phone :size="19"/>
          </button>
          <button class="agent-send-button" type="submit" aria-label="发送给 Agent" :disabled="!canSubmit || !prompt.trim()">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m21 3-7 18-4-8-8-4Z"/><path d="m10 13 4-4"/></svg>
          </button>
        </div>
        <p v-if="voiceSession.unavailableReason" class="workflow-note" role="status">
          {{ voiceSession.unavailableReason }}
        </p>
        <p v-if="voiceSession.error" class="data-error" role="alert">{{ voiceSession.error }}</p>
      </form>
    </div>
  </aside>
</template>
