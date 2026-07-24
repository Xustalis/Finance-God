/* ═══════════════════════════════════════════════════
   常驻 AI 侧栏状态 — Pinia Store
   规范 §9.2：跟随当前页/对象、可折叠为窄栏、折叠状态持久化。
   所有结论来自后端 Multi-Agent 运行时，不在前端派生或伪造。
   ═══════════════════════════════════════════════════ */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { runAgentResearch, isDeskApiError, DeskApiError } from '@/api/desk'
import type { AgentRun, AgentResearchRequest } from '@/types/desk'

export const AI_SIDEBAR_COLLAPSE_KEY = 'finance-god-ai-collapsed'

/** 页面上下文类型 → Agent 资产类型映射。 */
export type AiScope =
  | 'market'
  | 'symbol'
  | 'portfolio'
  | 'orders'
  | 'reviews'
  | 'data'
  | 'profile'
  | 'settings'

const SCOPE_ASSET_KIND: Record<AiScope, AgentResearchRequest['asset_kind']> = {
  market: 'market',
  symbol: 'equity',
  portfolio: 'portfolio',
  orders: 'equity',
  reviews: 'equity',
  data: 'market',
  profile: 'other',
  settings: 'other',
}

function storedCollapsePreference(): boolean | null {
  const stored = localStorage.getItem(AI_SIDEBAR_COLLAPSE_KEY)
  if (stored === 'true') return true
  if (stored === 'false') return false
  return null
}

export const useAiContextStore = defineStore('aiContext', () => {
  // ─── 折叠状态（持久化） ────────────────────────
  const initialPreference = storedCollapsePreference()
  const hasExplicitCollapsePreference = ref(initialPreference !== null)
  const collapsed = ref<boolean>(
    initialPreference ?? (typeof window !== 'undefined' && window.innerWidth < 1280),
  )

  function setCollapsed(value: boolean) {
    collapsed.value = value
    hasExplicitCollapsePreference.value = true
    localStorage.setItem(AI_SIDEBAR_COLLAPSE_KEY, value ? 'true' : 'false')
  }

  function toggle() {
    setCollapsed(!collapsed.value)
  }

  function syncViewportDefault(viewportWidth: number) {
    if (!hasExplicitCollapsePreference.value) {
      collapsed.value = viewportWidth < 1280
    }
  }

  // ─── 当前对象上下文（跟随页面/选择） ───────────
  const scope = ref<AiScope | null>(null)
  const subject = ref<string | null>(null)
  const label = ref<string | null>(null)

  /** 页面切换或选择变化时同步上下文。若对象改变则清空上一结论。 */
  function setContext(next: { scope: AiScope; subject: string | null; label?: string | null }) {
    const changed = scope.value !== next.scope || subject.value !== next.subject
    scope.value = next.scope
    subject.value = next.subject
    label.value = next.label ?? next.subject ?? null
    if (changed) {
      run.value = null
      status.value = 'idle'
      errorMessage.value = null
      errorCode.value = null
    }
  }

  // ─── 运行状态 ──────────────────────────────────
  const status = ref<'idle' | 'running' | 'done' | 'error'>('idle')
  const run = ref<AgentRun | null>(null)
  const errorMessage = ref<string | null>(null)
  const errorCode = ref<string | null>(null)
  const lastRunAt = ref<string | null>(null)
  /** 追问文本：跨路由和折叠保持；刷新页面后清除。 */
  const followUp = ref<string>('')

  const canRun = computed(() => Boolean(subject.value) && status.value !== 'running')

  const conclusion = computed(() => run.value?.results?.[0]?.summary ?? null)

  async function requestRun(taskType = 'research') {
    if (!subject.value || !scope.value) return
    status.value = 'running'
    errorMessage.value = null
    errorCode.value = null
    const payload: AgentResearchRequest = {
      subject: subject.value,
      task_type: taskType,
      asset_kind: SCOPE_ASSET_KIND[scope.value],
      scope: scope.value,
    }
    if (followUp.value.trim()) {
      payload.evidence = [
        {
          identifier: 'user-followup',
          source: '用户追问',
          excerpt: followUp.value.trim().slice(0, 4000),
        },
      ]
    }
    try {
      run.value = await runAgentResearch(payload)
      status.value = 'done'
      lastRunAt.value = new Date().toISOString()
    } catch (error) {
      status.value = 'error'
      run.value = null
      if (isDeskApiError(error)) {
        const deskError = error as DeskApiError
        errorCode.value = deskError.code ?? null
        errorMessage.value =
          deskError.code === 'AI_RUNTIME_UNAVAILABLE'
            ? 'AI 编排运行时未配置或不可用，无法生成结论。'
            : deskError.message
      } else {
        errorMessage.value = error instanceof Error ? error.message : String(error)
      }
    }
  }

  return {
    collapsed,
    hasExplicitCollapsePreference,
    setCollapsed,
    syncViewportDefault,
    toggle,
    scope,
    subject,
    label,
    setContext,
    status,
    run,
    errorMessage,
    errorCode,
    lastRunAt,
    followUp,
    canRun,
    conclusion,
    requestRun,
  }
})
