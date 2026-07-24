<script setup lang="ts">
/**
 * AiSidebar — 常驻 AI 侧栏（规范 §9.2）
 * 所有 T00–T10 桌面页面共享同一个右侧栏，跟随当前对象。
 * 展示：当前对象、数据来源与时点、结论、证据/反方证据、未知项、追问输入。
 * 结论全部来自后端 Multi-Agent 运行时；不可用时显示显式失败，不生成默认建议。
 */
import { computed, ref } from 'vue'
import { MessageSquare } from 'lucide-vue-next'
import { useAiContextStore } from '@/stores/aiContext'
import { useDeskCommandsStore } from '@/stores/deskCommands'
import { quickCommandsForScope, type QuickCommand } from '@/services/quickCommands'
import EvidenceDrawer from '@/components/evidence/EvidenceDrawer.vue'
import WorkflowProgress from '@/components/desk/WorkflowProgress.vue'
import type { AgentClaim } from '@/types/desk'

const ai = useAiContextStore()
const deskCommands = useDeskCommandsStore()

/** 随当前对象上下文变化的固定 3 条快捷指令；settings 作用域为空。
 * 无持仓进入交易台时首条为个性化推荐。 */
const quickCommands = computed<QuickCommand[]>(() =>
  quickCommandsForScope(ai.scope, { noPositions: ai.hasPositions === false }),
)

function quickCommandDisabled(cmd: QuickCommand): boolean {
  if (ai.status === 'running') return true
  if (cmd.kind === 'action') return cmd.action ? !deskCommands.can(cmd.action.type) : true
  return !ai.canRun
}

function onQuickCommand(cmd: QuickCommand) {
  if (quickCommandDisabled(cmd)) return
  if (cmd.kind === 'action' && cmd.action) {
    deskCommands.dispatch(cmd.action)
    return
  }
  void ai.requestRun(cmd.taskType ?? 'research')
}

// 过程与证据抽屉：当前 AI 运行的结论已由后端按 (agent_run, run_id) 落库，
// 此处仅打开只读抽屉查看不可变证据，绝不在前端派生结论。
const evidenceOpen = ref(false)
const evidenceRunId = computed(() => ai.run?.run_id ?? null)
function openEvidence() {
  if (evidenceRunId.value) evidenceOpen.value = true
}

const primaryResult = computed(() => ai.run?.results?.[0] ?? null)
const allClaims = computed<AgentClaim[]>(() =>
  (ai.run?.results ?? []).flatMap((result) => result.claims),
)
const facts = computed(() => allClaims.value.filter((c) => c.kind === 'fact'))
const inferences = computed(() => allClaims.value.filter((c) => c.kind === 'inference'))
const unknowns = computed(() => [...new Set(allClaims.value.flatMap((c) => c.unknowns))])
const invalidations = computed(() =>
  [...new Set(allClaims.value.flatMap((c) => c.invalidation_conditions))],
)
const evidence = computed(() =>
  (ai.run?.results ?? []).flatMap((result) => result.evidence),
)

function onRun() {
  void ai.requestRun()
}
</script>

<template>
  <!-- 折叠为 44px 可见轨道 -->
  <aside
    v-if="ai.collapsed"
    class="ai-rail"
    aria-label="AI 侧栏（已收起）"
    data-test="ai-sidebar"
  >
    <button
      class="rail-toggle"
      type="button"
      title="展开 AI 侧栏"
      aria-label="展开 AI 侧栏"
      data-test="ai-sidebar-toggle"
      @click="ai.toggle()"
    >
      <span class="rail-glyph">AI</span>
    </button>
    <span
      class="rail-status"
      :data-status="ai.status"
      :title="ai.status"
    />
  </aside>

  <!-- 展开态 -->
  <aside
    v-else
    class="ai-sidebar"
    aria-label="AI 研究侧栏"
    data-test="ai-sidebar"
  >
    <div class="ai-sidebar-inner">
    <header class="ai-head">
      <div class="ai-head-titles">
        <small class="ai-kicker">CURRENT OBJECT RESEARCH</small>
        <h2 class="ai-title">AI 研究</h2>
      </div>
      <button
        class="head-toggle"
        type="button"
        title="收起 AI 侧栏"
        aria-label="收起 AI 侧栏"
        data-test="ai-sidebar-toggle"
        @click="ai.toggle()"
      >
        收起
      </button>
    </header>

    <!-- 当前对象 -->
    <section class="ai-block">
      <span class="block-label">当前对象</span>
      <p v-if="ai.subject" class="object-line">
        <strong data-test="ai-current-object">{{ ai.label ?? ai.subject }}</strong>
        <span class="object-scope">{{ ai.scope }}</span>
      </p>
      <p v-else class="empty-note">当前页面未选择可研究的对象。</p>
    </section>

    <!-- 主操作 -->
    <button
      class="run-button"
      type="button"
      :disabled="!ai.canRun"
      @click="onRun"
    >
      {{ ai.status === 'running' ? '分析中…' : ai.run ? '重新分析当前对象' : '分析当前对象' }}
    </button>

    <!-- 工作流进度（类 Codex 折叠）：运行中与完成均由此面板展示 -->
    <WorkflowProgress />

    <!-- 显式失败：不生成默认建议 -->
    <section v-if="ai.status === 'error'" class="ai-state error" role="alert">
      <span class="state-label">AI 不可用</span>
      <p class="state-message">{{ ai.errorMessage }}</p>
      <p v-if="ai.errorCode" class="state-code">错误码：{{ ai.errorCode }}</p>
    </section>

    <!-- 结论与证据 -->
    <template v-if="ai.status === 'done' && primaryResult">
      <section class="ai-block">
        <span class="block-label">结论</span>
        <p class="conclusion">{{ primaryResult.summary }}</p>
        <button
          v-if="evidenceRunId"
          class="evidence-entry"
          type="button"
          data-test="ai-evidence-entry"
          @click="openEvidence"
        >
          查看过程 / 分析依据 →
        </button>
      </section>

      <section v-if="facts.length" class="ai-block">
        <span class="block-label">支持证据（事实）</span>
        <ul class="claim-list">
          <li v-for="c in facts" :key="c.claim_id">{{ c.statement }}</li>
        </ul>
      </section>

      <section v-if="inferences.length" class="ai-block">
        <span class="block-label">推断 / 反方证据</span>
        <ul class="claim-list inference">
          <li v-for="c in inferences" :key="c.claim_id">{{ c.statement }}</li>
        </ul>
      </section>

      <section v-if="unknowns.length" class="ai-block">
        <span class="block-label">未知项</span>
        <ul class="claim-list muted">
          <li v-for="(u, i) in unknowns" :key="i">{{ u }}</li>
        </ul>
      </section>

      <section v-if="invalidations.length" class="ai-block">
        <span class="block-label">失效条件</span>
        <ul class="claim-list muted">
          <li v-for="(v, i) in invalidations" :key="i">{{ v }}</li>
        </ul>
      </section>

      <section v-if="evidence.length" class="ai-block">
        <span class="block-label">引用来源</span>
        <ul class="evidence-list">
          <li v-for="(e, i) in evidence" :key="i">
            <strong>{{ e.source }}</strong>
            <span class="evidence-excerpt">{{ e.excerpt }}</span>
          </li>
        </ul>
      </section>
    </template>

    <!-- 空闲提示 -->
    <section v-else class="ai-block idle-note">
      <p class="empty-note">
        点击「分析当前对象」，由 Multi-Agent 运行时基于真实行情与证据生成结论。
        结论不会在浏览器端派生或伪造。
      </p>
    </section>

    <!-- 快捷指令：随当前对象上下文变化，贴在输入框上方，无边框/无卡片 -->
    <section
      v-if="quickCommands.length"
      class="ai-quick-commands"
      aria-label="快捷指令"
      data-test="ai-quick-commands"
    >
      <button
        v-for="cmd in quickCommands"
        :key="cmd.id"
        type="button"
        class="quick-command"
        :data-test="`quick-command-${cmd.id}`"
        :disabled="quickCommandDisabled(cmd)"
        @click="onQuickCommand(cmd)"
      >
        <MessageSquare class="quick-icon" :size="15" aria-hidden="true" />
        <span class="quick-label">{{ cmd.label }}</span>
      </button>
    </section>

    <!-- 追问 -->
    <section class="ai-followup">
      <label class="block-label" for="ai-followup-input">继续追问</label>
      <textarea
        id="ai-followup-input"
        v-model="ai.followUp"
        class="followup-input"
        data-test="ai-followup"
        rows="2"
        placeholder="补充你想让 AI 重点分析的问题或证据…"
      />
    </section>

    </div>
    <!-- 过程与证据只读抽屉（禁嵌套：高级分析跳转独立页） -->
    <EvidenceDrawer
      v-if="evidenceRunId"
      :open="evidenceOpen"
      object-type="agent_run"
      :object-id="evidenceRunId"
      version="1"
      tier="normal"
      @close="evidenceOpen = false"
    />
  </aside>
</template>

<style scoped>
.ai-sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
  background: var(--paper, #f3ecda);
  scrollbar-width: thin;
}
.ai-sidebar-inner {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  max-width: 620px;
  min-height: 100%;
  margin: 0 auto;
  padding: 16px clamp(14px, 4%, 40px) 22px;
}
.ai-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  border-bottom: 3px double var(--ink, #241d12);
  padding-bottom: 7px;
}
.ai-kicker {
  color: var(--muted-ink, #6b5f47);
  font-size: 0.58rem;
  font-weight: 900;
  letter-spacing: 0.12em;
}
.ai-title {
  margin: 1px 0 0;
  font-family: var(--font-serif);
  font-size: 1.55rem;
  font-weight: 800;
  color: var(--ink, #241d12);
}
.head-toggle,
.run-button {
  font: inherit;
  cursor: pointer;
  background: transparent;
  color: var(--ink, #241d12);
  border: 1px solid var(--ink, #241d12);
  padding: 4px 10px;
  border-radius: 0;
}
.head-toggle {
  font-size: 0.75rem;
  padding: 3px 8px;
}
.run-button {
  width: 100%;
  padding: 8px;
  font-weight: 700;
  background: var(--ink, #241d12);
  color: var(--paper, #f3ecda);
}
.run-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.ai-block {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.block-label {
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--muted-ink, #6b5f47);
  border-bottom: 1px solid var(--faint-rule);
  padding-bottom: 3px;
}
.object-line {
  margin: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 0.95rem;
}
.object-scope {
  font-size: 0.7rem;
  color: var(--muted-ink, #6b5f47);
  border: 1px solid var(--rule, #cbbfa0);
  padding: 0 5px;
  border-radius: 2px;
}
.conclusion {
  margin: 0;
  font-size: 0.86rem;
  line-height: 1.62;
  color: var(--ink, #241d12);
}
.evidence-entry {
  align-self: flex-start;
  margin-top: 2px;
  font: inherit;
  font-size: 0.76rem;
  font-weight: 700;
  cursor: pointer;
  background: transparent;
  color: var(--ink, #241d12);
  border: none;
  border-bottom: 1px solid var(--ink, #241d12);
  padding: 0 0 1px;
}
.evidence-entry:hover { color: var(--risk, #9a2c2c); border-color: var(--risk, #9a2c2c); }
.claim-list,
.agent-list,
.evidence-list {
  margin: 0;
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.82rem;
  line-height: 1.45;
}
.claim-list.inference li { color: var(--risk, #9a2c2c); }
.claim-list.muted li { color: var(--muted-ink, #6b5f47); }
.agent-list { list-style: none; padding-left: 0; }
.agent-list code {
  font-size: 0.74rem;
  color: var(--ink, #241d12);
  font-weight: 700;
}
.agent-reason {
  display: block;
  color: var(--muted-ink, #6b5f47);
  font-size: 0.76rem;
}
.evidence-list { list-style: none; padding-left: 0; }
.evidence-excerpt {
  display: block;
  color: var(--muted-ink, #6b5f47);
  font-size: 0.76rem;
}
.timestamp,
.state-code {
  font-size: 0.72rem;
  color: var(--muted-ink, #6b5f47);
  margin: 2px 0 0;
}
.empty-note {
  margin: 0;
  font-size: 0.82rem;
  color: var(--muted-ink, #6b5f47);
  line-height: 1.5;
}
.ai-state {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border-radius: 3px;
  font-size: 0.84rem;
}
.ai-state.running {
  flex-direction: row;
  align-items: center;
  gap: 8px;
  color: var(--muted-ink, #6b5f47);
  border: 1px dashed var(--rule, #cbbfa0);
}
.ai-state.error {
  border: 1px solid var(--risk, #9a2c2c);
  background: rgb(154 44 44 / 8%);
}
.state-label {
  font-weight: 800;
  color: var(--risk, #9a2c2c);
}
.state-message { margin: 0; color: var(--ink, #241d12); }
.state-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted-ink, #6b5f47);
  animation: pulse 1.1s ease-in-out infinite;
}
@keyframes pulse { 0%,100% { opacity: 0.3; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .state-dot { animation: none; }
}
.ai-quick-commands {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: auto;
  padding-top: 6px;
}
.quick-command {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 4px 2px;
  font: inherit;
  font-size: 0.82rem;
  text-align: left;
  cursor: pointer;
  color: var(--ink, #241d12);
  background: transparent;
  border: none;
}
.quick-command:hover:not(:disabled) { color: var(--risk, #9a2c2c); }
.quick-command:disabled { opacity: 0.4; cursor: not-allowed; }
.quick-icon { flex: 0 0 auto; color: var(--muted-ink, #6b5f47); }
.quick-label { min-width: 0; }
.ai-followup {
  display: flex;
  flex-direction: column;
  gap: 5px;
  border-top: 1px solid var(--rule, #cbbfa0);
  padding-top: 10px;
}
.followup-input {
  font: inherit;
  font-size: 0.84rem;
  resize: vertical;
  padding: 6px 8px;
  border: 1px solid var(--rule, #cbbfa0);
  background: var(--paper-2, #fbf6e9);
  color: var(--ink, #241d12);
  border-radius: 2px;
}

/* 收起态窄栏 */
.ai-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  height: 100%;
  width: 44px;
  padding: 12px 0;
  background: var(--paper, #f3ecda);
  border-left: 1px solid var(--rule, #cbbfa0);
}
.rail-toggle {
  writing-mode: vertical-rl;
  cursor: pointer;
  background: transparent;
  border: none;
  color: var(--ink, #241d12);
  font-weight: 800;
  letter-spacing: 0.12em;
  padding: 6px 0;
}
.rail-glyph { font-size: 0.8rem; }
.rail-status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted-ink, #6b5f47);
}
.rail-status[data-status='running'] { background: var(--ink, #241d12); }
.rail-status[data-status='done'] { background: var(--gain, #2f7d32); }
.rail-status[data-status='error'] { background: var(--risk, #9a2c2c); }
</style>
