import { describe, expect, it } from 'vitest'
import {
  CAPABILITY_GAPS,
  JOURNEY_SCENARIOS,
  PHASE_PLANS,
  SAFE_ACTIONS,
  gapSummary,
  normalizeSymbol,
  phaseForGap,
  quickCommandsFor,
  resolveCommand,
} from './model'

describe('journey desk interaction contract', () => {
  it('returns exactly three context commands for every workspace', () => {
    for (const section of ['information', 'portfolio', 'watchlist', 'trading'] as const) {
      expect(quickCommandsFor(section)).toHaveLength(3)
    }
    expect(quickCommandsFor('information')).not.toEqual(quickCommandsFor('portfolio'))
  })

  it('allows navigation and draft-only filling', () => {
    expect(resolveCommand('打开交易并准备草稿')).toMatchObject({
      kind: 'action',
      actionId: 'navigate_trading',
    })
    expect(resolveCommand('把数量填写成 200 股')).toMatchObject({
      kind: 'action',
      actionId: 'fill_order_quantity',
      value: 200,
    })
  })

  it('routes market and profile-candidate intents to different workflows', () => {
    expect(resolveCommand('分析当前标的行情')).toMatchObject({
      kind: 'workflow',
      workflowKey: 'market_context',
    })
    expect(resolveCommand('结合画像生成可研究候选')).toMatchObject({
      kind: 'workflow',
      workflowKey: 'company_research',
    })
  })

  it('refuses settings and execution authority', () => {
    expect(resolveCommand('打开用户设置')).toMatchObject({ kind: 'refused' })
    expect(resolveCommand('帮我直接下单')).toMatchObject({ kind: 'refused' })
    expect(resolveCommand('撤单')).toMatchObject({ kind: 'refused' })
    expect(resolveCommand('资金划转 1000 元')).toMatchObject({ kind: 'refused' })
  })

  it('never publishes sensitive or final execution actions', () => {
    const actionIds = SAFE_ACTIONS.map((action) => action.id)
    expect(actionIds).not.toContain('open_settings')
    expect(actionIds).not.toContain('submit_order')
    expect(actionIds).not.toContain('cancel_order')
    expect(actionIds).not.toContain('transfer_funds')
    expect(SAFE_ACTIONS.every((action) => (
      action.mutation !== 'draft_only' || action.object === 'order_draft'
    ))).toBe(true)
  })

  it('normalizes supported A-share symbols without guessing invalid input', () => {
    expect(normalizeSymbol('600519')).toBe('600519.SH')
    expect(normalizeSymbol('000001')).toBe('000001.SZ')
    expect(normalizeSymbol('AAPL')).toBe('AAPL')
  })
})

describe('backend gap matrix and phase board', () => {
  it('covers the required closed loops without claiming false completion', () => {
    const summary = gapSummary()
    expect(summary.partial + summary.missing).toBeGreaterThan(0)
    expect(summary.done + summary.partial + summary.missing).toBe(CAPABILITY_GAPS.length)
    expect(CAPABILITY_GAPS.some((item) => item.id === 'workflow-worker')).toBe(true)
    expect(CAPABILITY_GAPS.some((item) => item.id === 'desk-bootstrap')).toBe(true)
    expect(CAPABILITY_GAPS.some((item) => item.id === 'ui-action-bridge')).toBe(true)
    expect(
      CAPABILITY_GAPS.find((item) => item.id === 'settings-exclusion')?.status,
    ).toBe('done')
    expect(CAPABILITY_GAPS.every((item) => item.phase && item.evidence)).toBe(true)
  })

  it('defines ordered runnable phases with gates and observables', () => {
    expect(PHASE_PLANS.map((item) => item.id)).toEqual([
      'P0', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8',
    ])
    expect(PHASE_PLANS.every((item) => (
      item.runnable && item.gate && item.observables.length > 0 && item.deliverables.length > 0
    ))).toBe(true)
    expect(phaseForGap('market-worker')?.id).toBe('P2')
  })

  it('ships four user journeys used by the isolation prototype', () => {
    expect(JOURNEY_SCENARIOS).toHaveLength(4)
    expect(new Set(JOURNEY_SCENARIOS.map((item) => item.id)).size).toBe(4)
    expect(JOURNEY_SCENARIOS.every((item) => item.intro.includes('原型') || item.intro.length > 20)).toBe(true)
  })
})
