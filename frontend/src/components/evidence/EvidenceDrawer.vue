<script setup lang="ts">
/**
 * EvidenceDrawer — 过程与证据只读抽屉（规范 T10）
 * 480px 右侧只读抽屉，固定呈现顺序：
 *   结论版本 → 事实 / 推断 → 反方 / 未知 → 来源时点 → 规则影响（失效条件）。
 * 内容全部来自后端不可变证据（按 object_type/object_id/version 检索），
 * 不在浏览器端派生或伪造；缺失 / 失败 / 权限不足均显式呈现。
 * 禁止在抽屉内再嵌套抽屉：高级分析请跳转独立页。
 */
import { ref, watch } from 'vue'
import { fetchEvidence, isDeskApiError, type DeskApiError } from '@/api/desk'
import type { EvidenceTier, EvidenceView } from '@/types/desk'

const props = withDefaults(
  defineProps<{
    open: boolean
    objectType: string
    objectId: string
    version?: string | null
    tier?: EvidenceTier
  }>(),
  { version: null, tier: 'normal' },
)

const emit = defineEmits<{ (event: 'close'): void }>()

const status = ref<'idle' | 'loading' | 'done' | 'error' | 'not-found'>('idle')
const evidence = ref<EvidenceView | null>(null)
const errorMessage = ref<string | null>(null)
const errorCode = ref<string | null>(null)

async function load() {
  if (!props.objectType || !props.objectId) {
    status.value = 'error'
    errorMessage.value = '缺少证据对象标识，无法加载。'
    return
  }
  status.value = 'loading'
  evidence.value = null
  errorMessage.value = null
  errorCode.value = null
  try {
    evidence.value = await fetchEvidence(props.objectType, props.objectId, {
      version: props.version ?? undefined,
      tier: props.tier,
    })
    status.value = 'done'
  } catch (error) {
    if (isDeskApiError(error, 404)) {
      status.value = 'not-found'
      return
    }
    status.value = 'error'
    const deskError = error as DeskApiError
    errorCode.value = deskError.code ?? null
    errorMessage.value = deskError.message
  }
}

watch(
  () => [props.open, props.objectType, props.objectId, props.version, props.tier],
  () => {
    if (props.open) void load()
  },
  { immediate: true },
)

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime())
    ? iso
    : parsed.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="evidence-scrim"
      data-test="evidence-drawer"
      @click.self="emit('close')"
    >
      <aside class="evidence-drawer" aria-label="过程与证据" role="dialog">
        <header class="drawer-head">
          <div>
            <small class="drawer-kicker">分析依据 / 过程证据</small>
            <h2 class="drawer-title">查看过程</h2>
          </div>
          <button
            class="drawer-close"
            type="button"
            aria-label="关闭证据抽屉"
            data-test="evidence-close"
            @click="emit('close')"
          >
            关闭
          </button>
        </header>

        <!-- 加载中 -->
        <section v-if="status === 'loading'" class="drawer-state loading">
          正在读取不可变证据…
        </section>

        <!-- 对象不存在 -->
        <section
          v-else-if="status === 'not-found'"
          class="drawer-state empty"
          data-test="evidence-empty"
        >
          <span class="state-label">暂无证据</span>
          <p>该对象尚未产生结构化证据，或版本不存在。</p>
        </section>

        <!-- 显式失败 -->
        <section
          v-else-if="status === 'error'"
          class="drawer-state error"
          role="alert"
          data-test="evidence-error"
        >
          <span class="state-label">证据不可用</span>
          <p>{{ errorMessage }}</p>
          <p v-if="errorCode" class="state-code">错误码：{{ errorCode }}</p>
        </section>

        <!-- 证据内容：固定顺序 -->
        <template v-else-if="status === 'done' && evidence">
          <!-- 1. 结论版本 -->
          <section class="drawer-block">
            <span class="block-label">结论 · 版本</span>
            <p class="conclusion">{{ evidence.conclusion ?? '（本次运行未产出总结性结论）' }}</p>
            <dl class="meta-grid">
              <div><dt>对象</dt><dd>{{ evidence.object_type }} · {{ evidence.object_id }}</dd></div>
              <div><dt>版本</dt><dd data-test="evidence-version">v{{ evidence.version }}</dd></div>
              <div><dt>来源</dt><dd>{{ evidence.provider }}</dd></div>
              <div><dt>生成时间</dt><dd>{{ formatTime(evidence.generated_at) }}</dd></div>
            </dl>
          </section>

          <!-- 2. 事实 / 推断 -->
          <section v-if="evidence.facts.length" class="drawer-block">
            <span class="block-label">事实</span>
            <ul class="claim-list">
              <li v-for="(fact, i) in evidence.facts" :key="`f-${i}`">{{ fact.statement }}</li>
            </ul>
          </section>
          <section v-if="evidence.inferences.length" class="drawer-block">
            <span class="block-label">推断</span>
            <ul class="claim-list inference">
              <li v-for="(inf, i) in evidence.inferences" :key="`i-${i}`">{{ inf.statement }}</li>
            </ul>
          </section>

          <!-- 3. 反方 / 未知 -->
          <section v-if="evidence.counterpoints.length" class="drawer-block">
            <span class="block-label">反方 / 分歧</span>
            <ul class="claim-list inference">
              <li v-for="(cp, i) in evidence.counterpoints" :key="`c-${i}`">{{ cp }}</li>
            </ul>
          </section>
          <section v-if="evidence.unknowns.length" class="drawer-block">
            <span class="block-label">未知项</span>
            <ul class="claim-list muted">
              <li v-for="(u, i) in evidence.unknowns" :key="`u-${i}`">{{ u }}</li>
            </ul>
          </section>

          <!-- 4. 来源时点 -->
          <section v-if="evidence.sources.length" class="drawer-block">
            <span class="block-label">来源 · 时点</span>
            <ul class="source-list">
              <li v-for="(src, i) in evidence.sources" :key="`s-${i}`">
                <strong>{{ src.source }}</strong>
                <span v-if="src.excerpt" class="source-excerpt">{{ src.excerpt }}</span>
              </li>
            </ul>
          </section>

          <!-- 5. 规则影响（失效条件） -->
          <section v-if="evidence.invalidation_conditions.length" class="drawer-block">
            <span class="block-label">规则影响 / 失效条件</span>
            <ul class="claim-list muted">
              <li v-for="(v, i) in evidence.invalidation_conditions" :key="`v-${i}`">{{ v }}</li>
            </ul>
          </section>

          <footer class="drawer-foot">
            <RouterLink
              class="advanced-link"
              data-test="evidence-advanced-link"
              :to="{
                name: 'evidence',
                params: { id: evidence.object_id },
                query: { type: evidence.object_type, version: evidence.version },
              }"
            >
              打开高级证据页（血缘 / 版本比较 / 导出）→
            </RouterLink>
          </footer>
        </template>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.evidence-scrim {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  justify-content: flex-end;
  background: rgb(20 16 9 / 32%);
}
.evidence-drawer {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 480px;
  max-width: 92vw;
  height: 100%;
  padding: 16px 16px 20px;
  overflow-y: auto;
  background: var(--paper, #f3ecda);
  border-left: 1px solid var(--rule, #cbbfa0);
  box-shadow: -8px 0 24px rgb(20 16 9 / 18%);
  scrollbar-width: thin;
}
.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  border-bottom: 3px double var(--ink, #241d12);
  padding-bottom: 8px;
}
.drawer-kicker {
  color: var(--muted-ink, #6b5f47);
  font-size: 0.58rem;
  font-weight: 900;
  letter-spacing: 0.12em;
}
.drawer-title {
  margin: 1px 0 0;
  font-family: var(--font-serif);
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--ink, #241d12);
}
.drawer-close {
  font: inherit;
  font-size: 0.75rem;
  cursor: pointer;
  background: transparent;
  color: var(--ink, #241d12);
  border: 1px solid var(--ink, #241d12);
  padding: 3px 10px;
}
.drawer-block {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.block-label {
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--muted-ink, #6b5f47);
  border-bottom: 1px solid var(--faint-rule, #ddd0b0);
  padding-bottom: 3px;
}
.conclusion {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.6;
  color: var(--ink, #241d12);
}
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3px 12px;
  margin: 4px 0 0;
  font-size: 0.76rem;
}
.meta-grid div { display: flex; gap: 6px; }
.meta-grid dt { color: var(--muted-ink, #6b5f47); font-weight: 700; }
.meta-grid dd { margin: 0; color: var(--ink, #241d12); }
.claim-list,
.source-list {
  margin: 0;
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.83rem;
  line-height: 1.5;
}
.claim-list.inference li { color: var(--risk, #9a2c2c); }
.claim-list.muted li { color: var(--muted-ink, #6b5f47); }
.source-list { list-style: none; padding-left: 0; }
.source-excerpt {
  display: block;
  color: var(--muted-ink, #6b5f47);
  font-size: 0.76rem;
}
.drawer-state {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 12px;
  border-radius: 3px;
  font-size: 0.85rem;
  color: var(--muted-ink, #6b5f47);
}
.drawer-state.loading { border: 1px dashed var(--rule, #cbbfa0); }
.drawer-state.empty { border: 1px solid var(--rule, #cbbfa0); }
.drawer-state.error {
  border: 1px solid var(--risk, #9a2c2c);
  background: rgb(154 44 44 / 8%);
  color: var(--ink, #241d12);
}
.state-label { font-weight: 800; color: var(--ink, #241d12); }
.drawer-state.error .state-label { color: var(--risk, #9a2c2c); }
.state-code { font-size: 0.72rem; margin: 0; }
.drawer-foot {
  margin-top: auto;
  border-top: 1px solid var(--rule, #cbbfa0);
  padding-top: 10px;
}
.advanced-link {
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--ink, #241d12);
  text-decoration: none;
  border-bottom: 1px solid var(--ink, #241d12);
}
.advanced-link:hover { color: var(--risk, #9a2c2c); border-color: var(--risk, #9a2c2c); }
</style>
