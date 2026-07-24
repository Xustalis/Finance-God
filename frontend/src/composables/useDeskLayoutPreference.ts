import { reactive, ref } from 'vue'

export type DeskPanel = 'left' | 'right' | 'bottom'

export interface DeskLayoutPreference {
  left: boolean
  right: boolean
  bottom: boolean
}

export const DESK_LAYOUT_STORAGE_KEY = 'finance-god:desk-layout:v1'

const DEFAULT_LAYOUT: DeskLayoutPreference = {
  left: true,
  right: true,
  bottom: true,
}

function isDeskLayoutPreference(value: unknown): value is DeskLayoutPreference {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<DeskLayoutPreference>
  return (
    typeof candidate.left === 'boolean'
    && typeof candidate.right === 'boolean'
    && typeof candidate.bottom === 'boolean'
  )
}

export function useDeskLayoutPreference() {
  const storageError = ref('')
  const layoutStatus = ref('')
  const panels = reactive<DeskLayoutPreference>({ ...DEFAULT_LAYOUT })

  try {
    const stored = localStorage.getItem(DESK_LAYOUT_STORAGE_KEY)
    if (stored) {
      const parsed: unknown = JSON.parse(stored)
      if (!isDeskLayoutPreference(parsed)) throw new Error('invalid desk layout preference')
      Object.assign(panels, parsed)
    }
  } catch {
    storageError.value = '无法读取已保存的布局，已恢复默认布局。'
  }

  function persist() {
    storageError.value = ''
    layoutStatus.value = ''
    try {
      localStorage.setItem(DESK_LAYOUT_STORAGE_KEY, JSON.stringify(panels))
    } catch {
      storageError.value = '无法保存布局，请检查浏览器存储权限。'
    }
  }

  function togglePanel(panel: DeskPanel) {
    panels[panel] = !panels[panel]
    persist()
  }

  function resetLayout() {
    Object.assign(panels, DEFAULT_LAYOUT)
    storageError.value = ''
    try {
      localStorage.removeItem(DESK_LAYOUT_STORAGE_KEY)
      layoutStatus.value = '布局已重置。'
    } catch {
      storageError.value = '布局已恢复默认，但无法清除浏览器中的保存记录。'
    }
  }

  return { panels, storageError, layoutStatus, togglePanel, resetLayout }
}
