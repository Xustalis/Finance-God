/* ═══════════════════════════════════════════════════
   建议动作解析 — 将 agent 结论中的 proposed_actions（自由文本）
   保守地映射为可在左侧执行的结构化动作，实现“右→左联动闭环”。
   —— 只映射确定、安全、非写入的动作（切换标的、导航）。
   —— 绝不从文本推断下单/改授权等写操作：写操作永远经既有
      confirm+mandate 人工确认流程，注册表不直接提交。
   ═══════════════════════════════════════════════════ */

import type { DeskAction } from '@/stores/deskCommands'

export interface ProposedActionLink {
  /** 原始建议文本。 */
  text: string
  /** 可派发的结构化动作；无法确定安全映射时为 null（仅作文本展示）。 */
  action: DeskAction | null
  /** 动作按钮的可读标签。 */
  actionLabel: string | null
}

/** A 股标的代码：6 位数字 + 交易所后缀。 */
const SYMBOL_PATTERN = /\b(\d{6}\.(?:SH|SZ))\b/i

/** 从一条建议文本解析出可执行的左侧动作（保守，仅安全非写入类）。 */
export function parseProposedAction(text: string): ProposedActionLink {
  const trimmed = text.trim()
  const match = trimmed.match(SYMBOL_PATTERN)
  if (match) {
    const symbol = match[1].toUpperCase()
    return {
      text: trimmed,
      action: { type: 'desk.selectSymbol', payload: { symbol } },
      actionLabel: `切换到 ${symbol}`,
    }
  }
  return { text: trimmed, action: null, actionLabel: null }
}

/** 批量解析一组建议动作。 */
export function parseProposedActions(actions: readonly string[]): ProposedActionLink[] {
  return actions.map(parseProposedAction)
}
