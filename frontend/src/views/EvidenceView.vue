<script setup lang="ts">
/**
 * EvidenceView — 过程与证据高级页（规范 T10）
 * 3/9 布局：左栏对象 / 版本 / Agent 节点导航，右栏单一详情。
 * 含 Agent 工作流图、错误 Trace（仅内部权限可见）、版本比较、证据包导出。
 * 所有内容来自后端不可变证据（按 object_type/object_id/version 检索），
 * 绝不在浏览器端派生或伪造；缺失 / 失败 / 权限不足 / 对象不存在均显式呈现。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Masthead from '@/components/desk/Masthead.vue'
import {
  compareEvidenceVersions,
  exportEvidence,
  fetchEvidence,
  fetchEvidenceLineage,
  isDeskApiError,
  type DeskApiError,
} from '@/api/desk'
import type {
  EvidenceCompareView,
  EvidenceExportView,
  EvidenceLineageView,
  EvidenceView,
} from '@/types/desk'

const route = useRoute()
const router = useRouter()

const objectId = computed(() => String(route.params.id || ''))
const objectType = computed(() => String(route.query.type || 'agent_run'))
const queryVersion = computed(() =>
  route.query.version ? String(route.query.version) : null,
)

const selectedVersion = ref<string | null>(null)

const status = ref<'idle' | 'loading' | 'done' | 'error' | 'not-found'>('idle')
const errorMessage = ref<string | null>(null)
const errorCode = ref<string | null>(null)

const detail = ref<EvidenceView | null>(null)
const lineage = ref<EvidenceLineageView | null>(null)
const catalog = ref<EvidenceExportView | null>(null)

// 版本比较
const compareA = ref<string | null>(null)
const compareB = ref<string | null>(null)
const compareResult = ref<EvidenceCompareView | null>(null)
const compareStatus = ref<'idle' | 'loading' | 'done' | 'error'>('idle')
const compareError = ref<string | null>(null)

// 证据包导出
const exportStatus = ref<'idle' | 'working' | 'done' | 'error'>('idle')
const exportError = ref<string | null>(null)

const versions = computed(() => catalog.value?.versions ?? [])
const canCompare = computed(() => versions.value.length >= 2)

function applyDeskError(error: unknown) {
  if (isDeskApiError(error, 404)) {
    status.value = 'not-found'
    return
  }
  status.value = 'error'
  const deskError = error as DeskApiError
  errorCode.value = deskError.code ?? null
  errorMessage.value = deskError.message ?? String(error)
}

async function load() {
  if (!objectId.value) {
    status.value = 'error'
    errorMessage.value = '缺少证据对象标识，无法加载。'
    return
  }
  status.value = 'loading'
  errorMessage.value = null
  errorCode.value = null
  detail.value = null
  lineage.value = null
  try {
    const version = selectedVersion.value ?? undefined
    const [evidence, lineageView, exportView] = await Promise.all([
      fetchEvidence(objectType.value, objectId.value, { version, tier: 'advanced' }),
      fetchEvidenceLineage(objectType.value, objectId.value, version),
      exportEvidence(objectType.value, objectId.value, { tier: 'advanced' }),
    ])
    detail.value = evidence
    lineage.value = lineageView
    catalog.value = exportView
    if (!selectedVersion.value) selectedVersion.value = evidence.version
    initCompareDefaults()
    status.value = 'done'
  } catch (error) {
    applyDeskError(error)
  }
}

function initCompareDefaults() {
  if (versions.value.length < 2) {
    compareA.value = null
    compareB.value = null
    return
  }
  if (!compareA.value) compareA.value = versions.value[0].version
  if (!compareB.value) compareB.value = versions.value[versions.value.length - 1].version
}

function selectVersion(version: string) {
  if (version === selectedVersion.value) return
  selectedVersion.value = version
  void load()
}

async function runCompare() {
  if (!compareA.value || !compareB.value) return
  compareStatus.value = 'loading'
  compareError.value = null
  compareResult.value = null
  try {
    compareResult.value = await compareEvidenceVersions(
      objectType.value,
      objectId.value,
      compareA.value,
      compareB.value,
    )
    compareStatus.value = 'done'
  } catch (error) {
    compareStatus.value = 'error'
    compareError.value = (error as DeskApiError).message ?? String(error)
  }
}

async function downloadBundle() {
  exportStatus.value = 'working'
  exportError.value = null
  try {
    const bundle = await exportEvidence(objectType.value, objectId.value, {
      version: selectedVersion.value ?? undefined,
      tier: 'advanced',
    })
    const blob = new Blob([JSON.stringify(bundle, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `evidence_${bundle.object_type}_${bundle.object_id}.json`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    exportStatus.value = 'done'
  } catch (error) {
    exportStatus.value = 'error'
    exportError.value = (error as DeskApiError).message ?? String(error)
  }
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime())
    ? iso
    : parsed.toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
  selectedVersion.value = queryVersion.value
  void load()
})

watch(objectId, () => {
  selectedVersion.value = queryVersion.value
  compareResult.value = null
  compareA.value = null
  compareB.value = null
  void load()
})
</script>

<template>
  <div class="evidence-page" data-test="evidence-view">
    <Masthead />

    <main class="evidence-canvas" :aria-busy="status === 'loading'">
      <div v-if="status === 'loading'" class="page-state" role="status">
        正在读取不可变证据…
      </div>

      <div
        v-else-if="status === 'not-found'"
        class="page-state empty-state"
        data-test="evidence-view-empty"
      >
        <strong>暂无证据</strong>
        <span>对象 {{ objectType }} · {{ objectId }} 尚未产生结构化证据，或该版本不存在。</span>
        <button type="button" class="secondary-action" @click="router.back()">返回</button>
      </div>

      <div
        v-else-if="status === 'error'"
        class="page-state error-state"
        role="alert"
        data-test="evidence-view-error"
      >
        <strong>证据加载失败</strong>
        <span>{{ errorMessage }}</span>
        <span v-if="errorCode" class="state-code">错误码：{{ errorCode }}</span>
        <button type="button" class="secondary-action" @click="load">重新加载</button>
      </div>

      <div v-else-if="status === 'done' && detail" class="evidence-grid">
        <!-- 左：对象 / 版本 / 节点导航（3 列） -->
        <aside class="nav-rail" aria-label="对象与版本导航">
          <section class="rail-block">
            <span class="block-label">对象</span>
            <p class="object-id">{{ detail.object_type }}</p>
            <p class="object-sub">{{ detail.object_id }}</p>
            <p class="object-subject">{{ detail.subject }}</p>
          </section>

          <section class="rail-block">
            <span class="block-label">版本历史</span>
            <ul v-if="versions.length" class="version-list" data-test="evidence-version-list">
              <li v-for="ver in versions" :key="ver.version">
                <button
                  type="button"
                  class="version-item"
                  :class="{ active: ver.version === selectedVersion }"
                  @click="selectVersion(ver.version)"
                >
                  <strong>v{{ ver.version }}</strong>
                  <span>{{ formatTime(ver.generated_at) }}</span>
                </button>
              </li>
            </ul>
            <p v-else class="rail-empty">仅单一版本。</p>
          </section>

          <section class="rail-block">
            <span class="block-label">Agent 节点</span>
            <ul v-if="detail.agent_nodes.length" class="node-list">
              <li v-for="node in detail.agent_nodes" :key="node.agent_id">
                <code>{{ node.agent_id }}</code>
                <span v-if="node.reason">{{ node.reason }}</span>
              </li>
            </ul>
            <p v-else class="rail-empty">未记录参与 Agent 节点。</p>
          </section>
        </aside>

        <!-- 右：单一详情（9 列） -->
        <section class="detail-region" aria-label="证据详情">
          <header class="detail-header">
            <div>
              <p class="kicker">过程与证据 · T10（高级）</p>
              <h1 tabindex="-1">分析依据 v{{ detail.version }}</h1>
              <p class="identity-line">
                <strong>{{ detail.tier === 'advanced' ? '高级视图' : detail.tier }}</strong>
                <span>{{ detail.provider }}</span>
                <span>{{ formatTime(detail.generated_at) }}</span>
              </p>
            </div>
          </header>

          <section class="detail-block">
            <h2>结论</h2>
            <p class="conclusion">{{ detail.conclusion ?? '（本次运行未产出总结性结论）' }}</p>
          </section>

          <div class="two-col">
            <section class="detail-block">
              <h2>事实</h2>
              <ul v-if="detail.facts.length" class="claim-list">
                <li v-for="(fact, i) in detail.facts" :key="`f-${i}`">{{ fact.statement }}</li>
              </ul>
              <p v-else class="rail-empty">无记录事实。</p>
            </section>
            <section class="detail-block">
              <h2>推断</h2>
              <ul v-if="detail.inferences.length" class="claim-list inference">
                <li v-for="(inf, i) in detail.inferences" :key="`i-${i}`">{{ inf.statement }}</li>
              </ul>
              <p v-else class="rail-empty">无记录推断。</p>
            </section>
          </div>

          <div class="two-col">
            <section class="detail-block">
              <h2>反方 / 分歧</h2>
              <ul v-if="detail.counterpoints.length" class="claim-list inference">
                <li v-for="(cp, i) in detail.counterpoints" :key="`c-${i}`">{{ cp }}</li>
              </ul>
              <p v-else class="rail-empty">无记录分歧。</p>
            </section>
            <section class="detail-block">
              <h2>未知项</h2>
              <ul v-if="detail.unknowns.length" class="claim-list muted">
                <li v-for="(u, i) in detail.unknowns" :key="`u-${i}`">{{ u }}</li>
              </ul>
              <p v-else class="rail-empty">无记录未知项。</p>
            </section>
          </div>

          <section class="detail-block">
            <h2>失效条件 / 规则影响</h2>
            <ul v-if="detail.invalidation_conditions.length" class="claim-list muted">
              <li v-for="(v, i) in detail.invalidation_conditions" :key="`v-${i}`">{{ v }}</li>
            </ul>
            <p v-else class="rail-empty">无记录失效条件。</p>
          </section>

          <!-- 数据血缘 -->
          <section class="detail-block">
            <h2>数据血缘</h2>
            <div class="lineage">
              <div>
                <h3>输入对象</h3>
                <ul v-if="lineage && lineage.inputs.length" class="lineage-list">
                  <li v-for="(input, i) in lineage.inputs" :key="`li-${i}`">
                    <RouterLink
                      class="inline-link"
                      :to="{
                        name: 'evidence',
                        params: { id: input.object_id },
                        query: { type: input.object_type, version: input.version },
                      }"
                    >
                      {{ input.object_type }} · {{ input.object_id }} v{{ input.version }}
                    </RouterLink>
                  </li>
                </ul>
                <p v-else class="rail-empty">未记录上游输入对象。</p>
              </div>
              <div>
                <h3>来源 · 时点</h3>
                <ul v-if="lineage && lineage.sources.length" class="source-list">
                  <li v-for="(src, i) in lineage.sources" :key="`ls-${i}`">
                    <strong>{{ src.source }}</strong>
                    <span v-if="src.excerpt">{{ src.excerpt }}</span>
                  </li>
                </ul>
                <p v-else class="rail-empty">未记录来源。</p>
              </div>
            </div>
          </section>

          <!-- Agent 工作流图 -->
          <section class="detail-block">
            <h2>Agent 工作流</h2>
            <ol v-if="detail.agent_nodes.length" class="workflow" data-test="evidence-workflow">
              <li v-for="node in detail.agent_nodes" :key="node.agent_id">
                <code>{{ node.agent_id }}</code>
                <span v-if="node.reason" class="workflow-reason">{{ node.reason }}</span>
              </li>
            </ol>
            <p v-else class="rail-empty">未记录 Agent 工作流节点。</p>
            <div v-if="detail.notices.length" class="notice-list">
              <h3>路由提示</h3>
              <p v-for="(notice, i) in detail.notices" :key="`n-${i}`">
                <code>{{ notice.agent_id }}</code>
                <span>{{ notice.reason }}</span>
                <span v-if="notice.missing_resources.length" class="missing">
                  缺失资源：{{ notice.missing_resources.join('、') }}
                </span>
                <span v-if="notice.missing_authorizations.length" class="missing">
                  缺失授权：{{ notice.missing_authorizations.join('、') }}
                </span>
              </p>
            </div>
          </section>

          <!-- 错误 Trace（仅内部权限） -->
          <section class="detail-block">
            <h2>错误 Trace</h2>
            <pre v-if="detail.error_trace" class="error-trace" data-test="evidence-error-trace">{{ detail.error_trace }}</pre>
            <p v-else class="rail-empty">
              无错误 Trace，或错误栈仅限内部权限查看（不在普通 / 高级视图呈现）。
            </p>
          </section>

          <!-- 版本比较 -->
          <section class="detail-block">
            <h2>版本比较</h2>
            <div v-if="canCompare" class="compare-controls">
              <label>
                版本 A
                <select v-model="compareA" data-test="compare-a">
                  <option v-for="ver in versions" :key="`a-${ver.version}`" :value="ver.version">
                    v{{ ver.version }}
                  </option>
                </select>
              </label>
              <label>
                版本 B
                <select v-model="compareB" data-test="compare-b">
                  <option v-for="ver in versions" :key="`b-${ver.version}`" :value="ver.version">
                    v{{ ver.version }}
                  </option>
                </select>
              </label>
              <button
                type="button"
                class="secondary-action"
                data-test="run-compare"
                :disabled="compareStatus === 'loading'"
                @click="runCompare"
              >
                {{ compareStatus === 'loading' ? '比较中…' : '比较版本' }}
              </button>
            </div>
            <p v-else class="rail-empty">仅单一版本，无可比较历史。</p>

            <p v-if="compareStatus === 'error'" class="inline-error" role="alert">
              {{ compareError }}
            </p>
            <div v-else-if="compareStatus === 'done' && compareResult" class="compare-result" data-test="compare-result">
              <p class="compare-heading">
                v{{ compareResult.base.version }} → v{{ compareResult.other.version }}
              </p>
              <p v-if="!compareResult.diffs.length" class="rail-empty">两版本无差异。</p>
              <div v-for="diff in compareResult.diffs" :key="diff.field" class="diff-block">
                <h3>{{ diff.field }}</h3>
                <ul v-if="diff.added.length" class="diff-list added">
                  <li v-for="(item, i) in diff.added" :key="`add-${i}`">+ {{ item }}</li>
                </ul>
                <ul v-if="diff.removed.length" class="diff-list removed">
                  <li v-for="(item, i) in diff.removed" :key="`rem-${i}`">− {{ item }}</li>
                </ul>
              </div>
            </div>
          </section>

          <!-- 证据包导出 -->
          <footer class="export-bar">
            <button
              type="button"
              class="primary-action"
              data-test="export-bundle"
              :disabled="exportStatus === 'working'"
              @click="downloadBundle"
            >
              {{ exportStatus === 'working' ? '打包中…' : '导出证据包（JSON）' }}
            </button>
            <span v-if="exportStatus === 'done'" class="export-note" role="status">
              已生成证据包（含对象版本与生成时间）。
            </span>
            <span v-else-if="exportStatus === 'error'" class="export-note error" role="alert">
              {{ exportError }}
            </span>
          </footer>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.evidence-page {
  min-height: 100vh;
  border-top: 6px solid var(--ink);
  background: var(--paper);
  color: var(--ink);
  font-variant-numeric: tabular-nums lining-nums;
}
.evidence-canvas { min-height: calc(100vh - 82px); padding: 12px 18px 40px; }
.page-state { display: grid; min-height: 55vh; place-content: center; gap: 10px; text-align: center; }
.empty-state strong, .error-state strong { font-size: 18px; }
.error-state { color: var(--risk); }
.state-code { font-size: 12px; color: var(--muted-ink); }
.secondary-action {
  justify-self: center; font: inherit; font-size: 13px; cursor: pointer;
  background: transparent; color: var(--ink); border: 1px solid var(--ink); padding: 5px 14px;
}
.primary-action {
  font: inherit; font-size: 13px; font-weight: 700; cursor: pointer;
  background: var(--ink); color: var(--paper); border: 1px solid var(--ink); padding: 7px 16px;
}
.primary-action:disabled, .secondary-action:disabled { opacity: 0.45; cursor: not-allowed; }

.evidence-grid {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 9fr);
  gap: 0;
  border-top: 3px double var(--rule);
}
.nav-rail {
  min-width: 0;
  border-right: 1px solid var(--rule);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.rail-block { display: flex; flex-direction: column; gap: 5px; }
.block-label {
  font-size: 0.68rem; font-weight: 800; letter-spacing: 0.08em;
  color: var(--muted-ink); border-bottom: 1px solid var(--faint-rule); padding-bottom: 3px;
}
.object-id { margin: 4px 0 0; font-weight: 800; font-size: 0.9rem; }
.object-sub { margin: 0; font-size: 0.78rem; color: var(--muted-ink); word-break: break-all; }
.object-subject { margin: 3px 0 0; font-size: 0.82rem; line-height: 1.5; }
.rail-empty { margin: 2px 0 0; font-size: 0.8rem; color: var(--muted-ink); line-height: 1.5; }
.version-list, .node-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
.version-item {
  width: 100%; text-align: left; font: inherit; cursor: pointer;
  display: flex; flex-direction: column; gap: 1px;
  background: transparent; border: 1px solid var(--faint-rule); padding: 5px 8px;
}
.version-item.active { border-color: var(--ink); background: var(--paper-2, #fbf6e9); }
.version-item strong { font-size: 0.82rem; }
.version-item span { font-size: 0.72rem; color: var(--muted-ink); }
.node-list li { display: flex; flex-direction: column; gap: 1px; font-size: 0.8rem; }
.node-list code { font-weight: 700; }
.node-list span { color: var(--muted-ink); font-size: 0.76rem; }

.detail-region { min-width: 0; padding: 12px 18px 20px; }
.detail-header { padding: 0 0 10px; border-bottom: 3px double var(--rule); }
.kicker { margin: 0 0 4px; color: var(--risk); font-size: 11px; font-weight: 900; letter-spacing: .12em; }
.detail-header h1 { margin: 0; font-size: clamp(20px, 2.4vw, 30px); letter-spacing: -.02em; }
.identity-line { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 8px 0 0; color: var(--muted-ink); font-size: 12px; }
.identity-line strong { color: var(--ink); }
.detail-block { padding: 12px 0; border-bottom: 1px solid var(--faint-rule); }
.detail-block h2 { margin: 0 0 6px; font-size: 13px; letter-spacing: .04em; }
.detail-block h3 { margin: 0 0 5px; font-size: 12px; color: var(--muted-ink); }
.conclusion { margin: 0; font-size: 0.9rem; line-height: 1.6; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; border-bottom: 1px solid var(--faint-rule); }
.two-col .detail-block { border-bottom: 0; }
.claim-list, .source-list, .lineage-list, .diff-list {
  margin: 0; padding-left: 16px; display: flex; flex-direction: column; gap: 4px;
  font-size: 0.83rem; line-height: 1.5;
}
.claim-list.inference li { color: var(--risk, #9a2c2c); }
.claim-list.muted li { color: var(--muted-ink, #6b5f47); }
.source-list, .lineage-list { list-style: none; padding-left: 0; }
.source-list span { display: block; color: var(--muted-ink); font-size: 0.76rem; }
.lineage { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.inline-link { border-bottom: 1px solid var(--ink); font-weight: 700; text-decoration: none; color: var(--ink); }
.inline-link:hover { color: var(--risk); border-color: var(--risk); }
.workflow {
  margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 0.83rem;
}
.workflow code { font-weight: 700; }
.workflow-reason { display: block; color: var(--muted-ink); font-size: 0.76rem; }
.notice-list { margin-top: 10px; }
.notice-list p { margin: 4px 0 0; font-size: 0.8rem; display: flex; flex-wrap: wrap; gap: 4px 10px; }
.notice-list code { font-weight: 700; }
.missing { color: var(--risk); }
.error-trace {
  margin: 0; padding: 10px; background: rgb(154 44 44 / 8%); border: 1px solid var(--risk);
  font-size: 0.76rem; white-space: pre-wrap; word-break: break-word; overflow-x: auto;
}
.compare-controls { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin-bottom: 10px; }
.compare-controls label { display: flex; flex-direction: column; gap: 3px; font-size: 0.76rem; color: var(--muted-ink); }
.compare-controls select { font: inherit; padding: 4px 8px; border: 1px solid var(--rule); background: var(--paper-2, #fbf6e9); }
.compare-heading { margin: 0 0 8px; font-weight: 800; font-size: 0.85rem; }
.diff-block { margin-bottom: 10px; }
.diff-list.added li { color: var(--gain, #2f7d32); }
.diff-list.removed li { color: var(--risk, #9a2c2c); }
.inline-error { margin: 6px 0 0; font-size: 0.8rem; color: var(--risk); }
.export-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding-top: 14px; }
.export-note { font-size: 0.8rem; color: var(--muted-ink); }
.export-note.error { color: var(--risk); }

@media (max-width: 1279px) {
  .evidence-grid { grid-template-columns: minmax(0, 4fr) minmax(0, 8fr); }
  .two-col, .lineage { grid-template-columns: 1fr; }
}
</style>
