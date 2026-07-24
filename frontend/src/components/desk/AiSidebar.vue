<script setup lang="ts">
/**
 * AiSidebar — 常驻 AI 侧栏（规范 §9.2）
 * 所有 T00–T10 桌面页面共享同一个右侧栏，跟随当前对象。
 * 展示：当前对象、数据来源与时点、结论、证据/反方证据、未知项、追问输入。
 * 结论全部来自后端 Multi-Agent 运行时；不可用时显示显式失败，不生成默认建议。
 */
import { computed } from 'vue'
import { useAiContextStore } from '@/stores/aiContext'
import type { AgentClaim } from '@/types/desk'

const ai = useAiContextStore()

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
const assignments = computed(() => ai.run?.plan?.assignments ?? [])

const lastRunLabel = computed(() => {
  if (!ai.lastRunAt) return null
  return new Date(ai.lastRunAt).toLocaleString('zh-CN', { hour12: false })
})

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
    <header class="ai-head">
      <div class="ai-head-titles">
        <small class="ai-kicker">AI RESEARCH · 编辑注释</small>
        <h2 class="ai-title">AI 侧栏</h2>
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

    <!-- 运行中 -->
    <section v-if="ai.status === 'running'" class="ai-state running">
      <span class="state-dot" />
      <span>Multi-Agent 运行中，正在调用模型与数据源…</span>
    </section>

    <!-- 显式失败：不生成默认建议 -->
    <section v-else-if="ai.status === 'error'" class="ai-state error" role="alert">
      <span class="state-label">AI 不可用</span>
      <p class="state-message">{{ ai.errorMessage }}</p>
      <p v-if="ai.errorCode" class="state-code">错误码：{{ ai.errorCode }}</p>
    </section>

    <!-- 结论与证据 -->
    <template v-else-if="ai.status === 'done' && primaryResult">
      <section class="ai-block">
        <span class="block-label">结论</span>
        <p class="conclusion">{{ primaryResult.summary }}</p>
      </section>

      <section v-if="assignments.length" class="ai-block">
        <span class="block-label">数据来源 / 参与 Agent</span>
        <ul class="agent-list">
          <li v-for="a in assignments" :key="a.agent_id">
            <code>{{ a.agent_id }}</code>
            <span class="agent-reason">{{ a.reason }}</span>
          </li>
        </ul>
        <p v-if="lastRunLabel" class="timestamp">运行时点：{{ lastRunLabel }}</p>
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
  </aside>
</template>

<style scoped>
.ai-sidebar {
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 100%;
  padding: 16px 14px 22px;
  overflow-y: auto;
  background: var(--paper, #f3ecda);
  border-left: 1px solid var(--rule, #cbbfa0);
  scrollbar-width: thin;
}
.ai-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  border-bottom: 2px solid var(--ink, #241d12);
  padding-bottom: 8px;
}
.ai-kicker {
  color: var(--risk, #9a2c2c);
  font-size: 0.66rem;
  font-weight: 900;
  letter-spacing: 0.12em;
}
.ai-title {
  margin: 2px 0 0;
  font-size: 1.15rem;
  font-weight: 700;
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
  border-radius: 2px;
}
.head-toggle {
  font-size: 0.75rem;
  padding: 3px 8px;
}
.run-button {
  width: 100%;
  padding: 9px;
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
  text-transform: uppercase;
  color: var(--muted-ink, #6b5f47);
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
  font-size: 0.9rem;
  line-height: 1.5;
  color: var(--ink, #241d12);
}
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
.ai-followup {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: auto;
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
