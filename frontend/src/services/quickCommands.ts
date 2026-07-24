/* ═══════════════════════════════════════════════════
   快捷指令定义 — 随左侧上下文（AiScope）变化的推荐指令
   规范样式：输入框上方、无边框/无卡片、纵向列表、气泡图标前缀。
   每个作用域固定 3 条最贴合当前情况的指令。
   —— settings 作用域刻意返回空：用户设置不被 agent 获取。
   —— workflowKey 为 Phase 3（发起工作流）预留；Phase 0 仅用 research。
   ═══════════════════════════════════════════════════ */

import type { AiScope } from '@/stores/aiContext'
import type { DeskAction } from '@/stores/deskCommands'

export interface QuickCommand {
  id: string
  label: string
  /** research：发起一次 AI 研究；action：派发左侧动作。 */
  kind: 'research' | 'action'
  /** research 使用：传给 Agent 运行时的 task 类型。 */
  taskType?: string
  /** action 使用：要派发到左侧的结构化动作。 */
  action?: DeskAction
  /** Phase 3 预留：映射到的正式工作流 key。 */
  workflowKey?: string
}

const COMMANDS_BY_SCOPE: Record<AiScope, QuickCommand[]> = {
  market: [
    { id: 'market.analyze', label: '分析当前行情', kind: 'research', taskType: 'research', workflowKey: 'market_context' },
    { id: 'market.breadth', label: '解读涨跌与覆盖率', kind: 'research', taskType: 'research', workflowKey: 'market_context' },
    { id: 'market.movers', label: '今日异动标的说明', kind: 'research', taskType: 'research', workflowKey: 'market_context' },
  ],
  symbol: [
    { id: 'symbol.analyze', label: '分析当前标的', kind: 'research', taskType: 'research', workflowKey: 'company_research' },
    { id: 'symbol.risk', label: '该标的主要风险', kind: 'research', taskType: 'research', workflowKey: 'company_research' },
    { id: 'symbol.fit', label: '是否契合我的画像', kind: 'research', taskType: 'research', workflowKey: 'company_research' },
  ],
  portfolio: [
    { id: 'portfolio.analyze', label: '持仓分析', kind: 'research', taskType: 'research', workflowKey: 'portfolio_stress' },
    { id: 'portfolio.concentration', label: '集中度与风险', kind: 'research', taskType: 'research', workflowKey: 'portfolio_stress' },
    { id: 'portfolio.rebalance', label: '生成再平衡方案', kind: 'research', taskType: 'research', workflowKey: 'trade_plan_generation' },
  ],
  orders: [
    { id: 'orders.review', label: '订单执行复盘', kind: 'research', taskType: 'research', workflowKey: 'post_trade_review' },
    { id: 'orders.pending', label: '待处理决策说明', kind: 'research', taskType: 'research', workflowKey: 'order_review' },
    { id: 'orders.exception', label: '异常订单解读', kind: 'research', taskType: 'research', workflowKey: 'order_review' },
  ],
  reviews: [
    { id: 'reviews.summary', label: '本轮交易复盘', kind: 'research', taskType: 'research', workflowKey: 'post_trade_review' },
    { id: 'reviews.quality', label: '执行质量分析', kind: 'research', taskType: 'research', workflowKey: 'post_trade_review' },
    { id: 'reviews.next', label: '下一步建议', kind: 'research', taskType: 'research', workflowKey: 'post_trade_review' },
  ],
  data: [
    { id: 'data.quality', label: '数据质量诊断', kind: 'research', taskType: 'research', workflowKey: 'data_quality_review' },
    { id: 'data.coverage', label: '覆盖范围与频率', kind: 'research', taskType: 'research', workflowKey: 'data_quality_review' },
    { id: 'data.freshness', label: '数据新鲜度说明', kind: 'research', taskType: 'research', workflowKey: 'data_quality_review' },
  ],
  profile: [
    { id: 'profile.explain', label: '解读我的投资画像', kind: 'research', taskType: 'research' },
    { id: 'profile.directions', label: '推荐方向说明', kind: 'research', taskType: 'research' },
    { id: 'profile.risk', label: '风险区间含义', kind: 'research', taskType: 'research' },
  ],
  // 用户设置不被 agent 获取：不提供任何快捷指令。
  settings: [],
}

/** 首次引导：无持仓进入交易台时首条推荐可买入标的（调用候选服务）。 */
const RECOMMEND_COMMAND: QuickCommand = {
  id: 'desk.recommend',
  label: '推荐可买入标的',
  kind: 'action',
  action: { type: 'desk.recommend' },
}

export interface QuickCommandContext {
  /** 无仿真持仓（首次引导）：在交易台首条提供个性化推荐。 */
  noPositions?: boolean
}

/**
 * 返回当前作用域的固定 3 条快捷指令；未知作用域返回空。
 * 若处于交易台（symbol 作用域）且无持仓，首条替换为“推荐可买入标的”。
 */
export function quickCommandsForScope(
  scope: AiScope | null,
  context: QuickCommandContext = {},
): QuickCommand[] {
  if (!scope) return []
  const base = COMMANDS_BY_SCOPE[scope] ?? []
  if (scope === 'symbol' && context.noPositions) {
    // 首条为个性化推荐，保持固定 3 条。
    return [RECOMMEND_COMMAND, ...base].slice(0, 3)
  }
  return base
}
