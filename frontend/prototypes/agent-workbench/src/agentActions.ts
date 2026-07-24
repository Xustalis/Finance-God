export type WorkspaceSection =
  | 'information'
  | 'portfolio'
  | 'watchlist'
  | 'history'
  | 'wallet'

export type InformationMode = 'market' | 'trade' | 'strategy'

export type WorkflowKey =
  | 'market_context'
  | 'company_research'
  | 'portfolio_stress'
  | 'trade_plan_generation'
  | 'order_review'
  | 'strategy_validation'
  | 'event_impact'

export type AgentActionId =
  | 'navigate_information'
  | 'navigate_portfolio'
  | 'navigate_watchlist'
  | 'navigate_history'
  | 'navigate_wallet'
  | 'show_market'
  | 'refresh_market'
  | 'show_trade'
  | 'show_strategy'
  | 'select_symbol'
  | 'fill_order_quantity'
  | 'fill_limit_price'
  | 'set_order_side_buy'
  | 'set_order_side_sell'

export interface AgentActionDefinition {
  id: AgentActionId
  description: string
  object: 'workspace' | 'symbol' | 'order_draft'
  mutation: 'ui_only' | 'draft_only'
}

export const AGENT_ACTIONS: readonly AgentActionDefinition[] = [
  {
    id: 'navigate_information',
    description: '打开信息工作区',
    object: 'workspace',
    mutation: 'ui_only',
  },
  {
    id: 'navigate_portfolio',
    description: '打开仿真持仓工作区',
    object: 'workspace',
    mutation: 'ui_only',
  },
  {
    id: 'navigate_watchlist',
    description: '打开自选工作区',
    object: 'workspace',
    mutation: 'ui_only',
  },
  {
    id: 'navigate_history',
    description: '打开仿真交易记录工作区',
    object: 'workspace',
    mutation: 'ui_only',
  },
  {
    id: 'navigate_wallet',
    description: '打开仿真钱包工作区',
    object: 'workspace',
    mutation: 'ui_only',
  },
  {
    id: 'show_market',
    description: '切换到行情栏目',
    object: 'workspace',
    mutation: 'ui_only',
  },
  {
    id: 'refresh_market',
    description: '刷新当前 PandaData 行情',
    object: 'workspace',
    mutation: 'ui_only',
  },
  {
    id: 'show_trade',
    description: '切换到交易草稿栏目',
    object: 'workspace',
    mutation: 'ui_only',
  },
  {
    id: 'show_strategy',
    description: '切换到策略栏目',
    object: 'workspace',
    mutation: 'ui_only',
  },
  {
    id: 'select_symbol',
    description: '选择当前标的',
    object: 'symbol',
    mutation: 'ui_only',
  },
  {
    id: 'fill_order_quantity',
    description: '填充未提交订单草稿数量',
    object: 'order_draft',
    mutation: 'draft_only',
  },
  {
    id: 'fill_limit_price',
    description: '填充未提交订单草稿限价',
    object: 'order_draft',
    mutation: 'draft_only',
  },
  {
    id: 'set_order_side_buy',
    description: '将未提交订单草稿方向设为买入',
    object: 'order_draft',
    mutation: 'draft_only',
  },
  {
    id: 'set_order_side_sell',
    description: '将未提交订单草稿方向设为卖出',
    object: 'order_draft',
    mutation: 'draft_only',
  },
] as const

export type ResolvedAgentCommand =
  | {
      kind: 'ui_action'
      actionId: AgentActionId
      value?: string | number
      response: string
    }
  | {
      kind: 'workflow'
      workflowKey: WorkflowKey
      title: string
    }
  | {
      kind: 'refused'
      response: string
    }
  | {
      kind: 'unknown'
      response: string
    }

const SECTION_ACTIONS: ReadonlyArray<{
  keywords: readonly string[]
  actionId: AgentActionId
  response: string
}> = [
  {
    keywords: ['持仓', '组合'],
    actionId: 'navigate_portfolio',
    response: '已打开仿真持仓工作区。',
  },
  {
    keywords: ['自选'],
    actionId: 'navigate_watchlist',
    response: '已打开自选工作区。',
  },
  {
    keywords: ['交易记录', '成交记录', '订单记录'],
    actionId: 'navigate_history',
    response: '已打开仿真交易记录工作区。',
  },
  {
    keywords: ['钱包', '资金'],
    actionId: 'navigate_wallet',
    response: '已打开仿真钱包工作区。',
  },
  {
    keywords: ['信息'],
    actionId: 'navigate_information',
    response: '已打开信息工作区。',
  },
]

function includesAny(text: string, keywords: readonly string[]): boolean {
  return keywords.some((keyword) => text.includes(keyword))
}

function numericValue(text: string, pattern: RegExp): number | null {
  const match = text.match(pattern)
  if (!match?.[1]) return null
  const value = Number(match[1])
  return Number.isFinite(value) && value > 0 ? value : null
}

export function resolveAgentCommand(rawText: string): ResolvedAgentCommand {
  const text = rawText.trim()
  if (!text) {
    return { kind: 'unknown', response: '请输入要查看、分析或填充的内容。' }
  }

  if (includesAny(text, ['设置', '修改用户信息', '凭据', '密码'])) {
    return {
      kind: 'refused',
      response: '用户设置不在 Agent 可控范围内，请使用顶部“用户设置”由你本人操作。',
    }
  }

  if (includesAny(text, ['订单复核', '检查草稿', '检查订单', '检查未提交订单草稿'])) {
    return { kind: 'workflow', workflowKey: 'order_review', title: '仿真订单草稿复核' }
  }

  if (includesAny(text, ['提交订单', '确认下单', '直接下单', '撤单', '自动买入', '自动卖出'])) {
    return {
      kind: 'refused',
      response: '我可以填写未提交草稿并运行复核，但不能提交、撤销或伪造成交。',
    }
  }

  const quantity = numericValue(text, /(?:数量|填成|填写)\D{0,8}(\d+(?:\.\d+)?)/)
  if (quantity !== null && includesAny(text, ['数量', '股', '份'])) {
    return {
      kind: 'ui_action',
      actionId: 'fill_order_quantity',
      value: quantity,
      response: `已把未提交草稿数量填为 ${quantity}，尚未进入最终复核。`,
    }
  }

  const limitPrice = numericValue(text, /(?:限价|价格)\D{0,8}(\d+(?:\.\d+)?)/)
  if (limitPrice !== null) {
    return {
      kind: 'ui_action',
      actionId: 'fill_limit_price',
      value: limitPrice,
      response: `已把未提交草稿限价填为 ${limitPrice}，需要后端重新计算后才能复核。`,
    }
  }

  const symbolMatch = text.toUpperCase().match(/\b(\d{6}(?:\.(?:SH|SZ))?)\b/)
  if (symbolMatch?.[1]) {
    return {
      kind: 'ui_action',
      actionId: 'select_symbol',
      value: symbolMatch[1],
      response: `已选择标的 ${symbolMatch[1]}，正在同步左侧上下文。`,
    }
  }

  if (includesAny(text, ['打开行情', '切换到行情', '查看行情栏目'])) {
    return {
      kind: 'ui_action',
      actionId: 'show_market',
      response: '已切换到行情栏目。',
    }
  }
  if (includesAny(text, ['刷新行情', '重新请求行情'])) {
    return {
      kind: 'ui_action',
      actionId: 'refresh_market',
      response: '已重新请求当前 PandaData 行情。',
    }
  }
  if (includesAny(text, ['打开交易', '切换到交易', '打开交易草稿'])) {
    return {
      kind: 'ui_action',
      actionId: 'show_trade',
      response: '已切换到交易草稿栏目。',
    }
  }
  if (includesAny(text, ['打开策略', '切换到策略'])) {
    return {
      kind: 'ui_action',
      actionId: 'show_strategy',
      response: '已切换到策略栏目。',
    }
  }

  if (includesAny(text, ['持仓分析', '分析持仓', '组合风险'])) {
    return { kind: 'workflow', workflowKey: 'portfolio_stress', title: '持仓与组合压力分析' }
  }
  if (includesAny(text, ['交易方案', '制定计划', '制定交易'])) {
    return { kind: 'workflow', workflowKey: 'trade_plan_generation', title: '交易方案生成' }
  }
  if (includesAny(text, ['策略', '验证策略'])) {
    return { kind: 'workflow', workflowKey: 'strategy_validation', title: '策略条件验证' }
  }
  if (includesAny(text, ['异动', '重大变动', '突发行情'])) {
    return { kind: 'workflow', workflowKey: 'event_impact', title: '重大行情事件影响分析' }
  }
  if (includesAny(text, ['公司', '股票信息', '研究标的'])) {
    return { kind: 'workflow', workflowKey: 'company_research', title: '当前标的公司研究' }
  }
  if (includesAny(text, ['分析行情', '市场环境', '行情'])) {
    return { kind: 'workflow', workflowKey: 'market_context', title: '当前行情与市场环境分析' }
  }

  if (includesAny(text, ['买入草稿', '买入方向'])) {
    return {
      kind: 'ui_action',
      actionId: 'set_order_side_buy',
      response: '已把未提交订单草稿切换为买入方向。',
    }
  }
  if (includesAny(text, ['卖出草稿', '卖出方向'])) {
    return {
      kind: 'ui_action',
      actionId: 'set_order_side_sell',
      response: '已把未提交订单草稿切换为卖出方向。',
    }
  }

  for (const item of SECTION_ACTIONS) {
    if (includesAny(text, item.keywords)) {
      return {
        kind: 'ui_action',
        actionId: item.actionId,
        response: item.response,
      }
    }
  }

  if (includesAny(text, ['交易', '草稿'])) {
    return {
      kind: 'ui_action',
      actionId: 'show_trade',
      response: '已切换到交易草稿栏目。',
    }
  }
  if (includesAny(text, ['行情'])) {
    return {
      kind: 'ui_action',
      actionId: 'show_market',
      response: '已切换到行情栏目。',
    }
  }

  return {
    kind: 'unknown',
    response: '当前原型没有匹配到安全动作。你可以让我查看持仓、分析行情或填写未提交草稿。',
  }
}

export function quickCommandsFor(
  section: WorkspaceSection,
  mode: InformationMode,
): readonly [string, string, string] {
  if (section === 'portfolio') {
    return ['分析持仓组合风险', '切换到交易草稿并保留当前标的', '查看当前标的重大行情提醒']
  }
  if (section === 'watchlist') {
    return ['分析当前标的行情', '查看我的自选', '研究标的公司信息']
  }
  if (section === 'history') {
    return ['查看我的交易记录', '分析当前标的行情', '检查未提交订单草稿']
  }
  if (section === 'wallet') {
    return ['查看仿真钱包', '分析组合风险', '切换到交易草稿']
  }
  if (mode === 'trade') {
    return ['帮我制定当前标的交易方案', '检查未提交订单草稿', '解释草稿与当前策略的偏离']
  }
  if (mode === 'strategy') {
    return ['验证当前策略的适用条件', '列出策略失效条件', '切换到交易草稿']
  }
  return ['分析当前标的行情', '结合用户画像研究标的公司', '查看当前标的重大行情提醒']
}
