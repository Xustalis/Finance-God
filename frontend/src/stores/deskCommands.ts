/* ═══════════════════════════════════════════════════
   交易台 UI 动作注册表 — Pinia Store
   左侧视图在挂载时注册可被调用的动作（选标的、跳转、预填等），
   常驻 AI 侧栏据此在"右→左"方向驱动左侧界面。
   —— 写操作（下单提交、改授权）永远经既有确认流程，注册表不直接提交。
   —— 用户设置作用域不注册任何动作，确保"用户设置不被 agent 获取"。
   ═══════════════════════════════════════════════════ */

import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 可被右侧 agent / 快捷指令调用的左侧动作类型。 */
export type DeskActionType =
  | 'desk.selectSymbol'
  | 'desk.recommend'
  | 'watchlist.add'
  | 'order.prefill'
  | 'nav.goto'
  | 'plan.open'

export interface DeskAction {
  type: DeskActionType
  payload?: Record<string, unknown>
}

/** 动作处理器：由左侧视图提供，接收结构化载荷。 */
export type DeskActionHandler = (payload?: Record<string, unknown>) => void | Promise<void>

export const useDeskCommandsStore = defineStore('deskCommands', () => {
  /** 当前已注册的处理器（非响应式内容，仅用于分发）。 */
  const handlers = new Map<DeskActionType, DeskActionHandler>()
  /** 已注册动作类型的响应式镜像，供 UI 判断某动作当前是否可用。 */
  const available = ref<DeskActionType[]>([])

  function syncAvailable() {
    available.value = [...handlers.keys()]
  }

  /**
   * 注册一个左侧动作处理器；返回注销函数。
   * 注销函数仅在处理器仍是当前注册者时才移除，避免路由切换时
   * 旧视图 onUnmounted 误删新视图 onMounted 的注册。
   */
  function register(type: DeskActionType, handler: DeskActionHandler): () => void {
    handlers.set(type, handler)
    syncAvailable()
    return () => {
      if (handlers.get(type) === handler) {
        handlers.delete(type)
        syncAvailable()
      }
    }
  }

  /** 当前是否有视图能处理该动作。 */
  function can(type: DeskActionType): boolean {
    return handlers.has(type)
  }

  /**
   * 分发一个动作到当前注册的处理器。
   * 返回是否被处理；未注册时返回 false，由调用方决定降级（如导航）。
   */
  function dispatch(action: DeskAction): boolean {
    const handler = handlers.get(action.type)
    if (!handler) return false
    void handler(action.payload)
    return true
  }

  return { available, register, can, dispatch }
})
