import { describe, expect, it } from 'vitest'
import {
  AGENT_ACTIONS,
  quickCommandsFor,
  resolveAgentCommand,
} from './agentActions'

describe('Agent UI action contract', () => {
  it('routes safe workspace navigation', () => {
    expect(resolveAgentCommand('查看我的持仓')).toMatchObject({
      kind: 'ui_action',
      actionId: 'navigate_portfolio',
    })
    expect(resolveAgentCommand('查看我的交易记录')).toMatchObject({
      kind: 'ui_action',
      actionId: 'navigate_history',
    })
  })

  it('fills a draft without creating a trade fact', () => {
    expect(resolveAgentCommand('把数量填写成 200 股')).toMatchObject({
      kind: 'ui_action',
      actionId: 'fill_order_quantity',
      value: 200,
    })
  })

  it('keeps settings outside Agent control', () => {
    expect(resolveAgentCommand('打开用户设置')).toMatchObject({
      kind: 'refused',
    })
  })

  it('refuses order submission and cancellation', () => {
    expect(resolveAgentCommand('帮我直接下单')).toMatchObject({
      kind: 'refused',
    })
    expect(resolveAgentCommand('提交订单')).toMatchObject({
      kind: 'refused',
    })
    expect(resolveAgentCommand('撤单')).toMatchObject({
      kind: 'refused',
    })
  })

  it('distinguishes draft review from order submission', () => {
    expect(resolveAgentCommand('检查未提交订单草稿')).toMatchObject({
      kind: 'workflow',
      workflowKey: 'order_review',
    })
  })

  it('prefers explicit workspace navigation over analysis', () => {
    expect(resolveAgentCommand('打开行情')).toMatchObject({
      kind: 'ui_action',
      actionId: 'show_market',
    })
    expect(resolveAgentCommand('刷新行情')).toMatchObject({
      kind: 'ui_action',
      actionId: 'refresh_market',
    })
  })

  it('never registers settings or execution actions', () => {
    const ids = AGENT_ACTIONS.map((action) => action.id)
    expect(ids).not.toContain('open_settings')
    expect(ids).not.toContain('submit_order')
    expect(ids).not.toContain('cancel_order')
    expect(AGENT_ACTIONS.every((action) => action.mutation !== 'draft_only'
      || action.object === 'order_draft')).toBe(true)
  })

  it('returns exactly three context-aware quick commands', () => {
    const market = quickCommandsFor('information', 'market')
    const portfolio = quickCommandsFor('portfolio', 'market')
    expect(market).toHaveLength(3)
    expect(portfolio).toHaveLength(3)
    expect(market).not.toEqual(portfolio)
  })

  it('keeps every recommended command executable', () => {
    const contexts = [
      ['information', 'market'],
      ['information', 'trade'],
      ['information', 'strategy'],
      ['portfolio', 'market'],
      ['watchlist', 'market'],
      ['history', 'market'],
      ['wallet', 'market'],
    ] as const

    for (const [section, mode] of contexts) {
      for (const command of quickCommandsFor(section, mode)) {
        expect(resolveAgentCommand(command).kind).not.toBe('unknown')
        expect(resolveAgentCommand(command).kind).not.toBe('refused')
      }
    }
  })
})
