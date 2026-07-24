import { reactive, ref } from 'vue'
import type { DeskSection } from '@/stores/tradingDesk'

export const DESK_LAYOUT_STORAGE_KEY = 'finance-god:desk-layout:v2'
export const MIN_AGENT_WIDTH_PERCENT = 32
export const MAX_AGENT_WIDTH_PERCENT = 60

const DEFAULT_TAB_ORDER: DeskSection[] = ['information', 'portfolio', 'watchlist', 'trading']

export interface DeskLayoutPreference {
  agentCollapsed: boolean
  agentWidthPercent: number
  tabOrder: DeskSection[]
}

const DEFAULT_LAYOUT: DeskLayoutPreference = {
  agentCollapsed: false,
  agentWidthPercent: 50,
  tabOrder: [...DEFAULT_TAB_ORDER],
}

function isDeskSection(value: unknown): value is DeskSection {
  return value === 'information' || value === 'portfolio' || value === 'watchlist' || value === 'trading'
}

function isDeskLayoutPreference(value: unknown): value is DeskLayoutPreference {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<DeskLayoutPreference>
  if (typeof candidate.agentCollapsed !== 'boolean' || typeof candidate.agentWidthPercent !== 'number') return false
  if (candidate.agentWidthPercent < MIN_AGENT_WIDTH_PERCENT || candidate.agentWidthPercent > MAX_AGENT_WIDTH_PERCENT) return false
  if (!Array.isArray(candidate.tabOrder) || candidate.tabOrder.length !== DEFAULT_TAB_ORDER.length) return false
  if (!candidate.tabOrder.every(isDeskSection) || new Set(candidate.tabOrder).size !== DEFAULT_TAB_ORDER.length) return false
  return DEFAULT_TAB_ORDER.every((section) => candidate.tabOrder?.includes(section))
}

function clampAgentWidth(value: number): number {
  return Math.min(MAX_AGENT_WIDTH_PERCENT, Math.max(MIN_AGENT_WIDTH_PERCENT, Math.round(value)))
}

export function useDeskLayoutPreference() {
  const preference = reactive<DeskLayoutPreference>({ ...DEFAULT_LAYOUT, tabOrder: [...DEFAULT_TAB_ORDER] })
  const storageError = ref<string | null>(null)
  const layoutStatus = ref<string | null>(null)

  try {
    const stored = localStorage.getItem(DESK_LAYOUT_STORAGE_KEY)
    if (stored) {
      const parsed: unknown = JSON.parse(stored)
      if (!isDeskLayoutPreference(parsed)) throw new Error('invalid desk layout preference')
      Object.assign(preference, parsed, { tabOrder: [...parsed.tabOrder] })
    }
  } catch {
    storageError.value = '无法读取已保存的布局，已恢复默认布局。'
  }

  function persist(status: string | null = null) {
    storageError.value = null
    layoutStatus.value = status
    try {
      localStorage.setItem(DESK_LAYOUT_STORAGE_KEY, JSON.stringify(preference))
    } catch {
      storageError.value = '无法保存布局，请检查浏览器存储权限。'
    }
  }

  function setAgentCollapsed(collapsed: boolean) {
    preference.agentCollapsed = collapsed
    persist(collapsed ? 'Agent 已收起，rail 保持可见。' : 'Agent 已展开。')
  }

  function toggleAgent() {
    setAgentCollapsed(!preference.agentCollapsed)
  }

  function setAgentWidth(value: number, announce = false, shouldPersist = true) {
    preference.agentWidthPercent = clampAgentWidth(value)
    if (shouldPersist) persist(announce ? `Agent 宽度已调整为 ${preference.agentWidthPercent}%。` : null)
  }

  function moveTab(section: DeskSection, direction: -1 | 1) {
    const currentIndex = preference.tabOrder.indexOf(section)
    const targetIndex = currentIndex + direction
    if (currentIndex < 0 || targetIndex < 0 || targetIndex >= preference.tabOrder.length) return
    const nextOrder = [...preference.tabOrder]
    ;[nextOrder[currentIndex], nextOrder[targetIndex]] = [nextOrder[targetIndex], nextOrder[currentIndex]]
    preference.tabOrder = nextOrder
    persist('工作区标签顺序已保存。')
  }

  function resetLayout() {
    Object.assign(preference, DEFAULT_LAYOUT, { tabOrder: [...DEFAULT_TAB_ORDER] })
    storageError.value = null
    try {
      localStorage.removeItem(DESK_LAYOUT_STORAGE_KEY)
      layoutStatus.value = '布局已重置。'
    } catch {
      storageError.value = '布局已恢复默认，但无法清除浏览器中的保存记录。'
    }
  }

  return {
    preference,
    storageError,
    layoutStatus,
    setAgentCollapsed,
    toggleAgent,
    setAgentWidth,
    moveTab,
    resetLayout,
  }
}
