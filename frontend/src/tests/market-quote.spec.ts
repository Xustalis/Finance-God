import { describe, expect, it } from 'vitest'
import {
  canUseQuoteAsDraftReference,
  completedFinancialQuarterRange,
  draftReferenceBlockedReason,
  normalizeDeskQuote,
  parseMarketNumber,
} from '@/services/tradingDesk'

describe('financial fact quarter range', () => {
  it('requests only completed quarters during the third quarter', () => {
    expect(completedFinancialQuarterRange(new Date('2026-07-25T00:00:00Z'))).toEqual({
      startQuarter: '2026q1',
      endQuarter: '2026q2',
    })
  })

  it('rolls the completed range across a year boundary', () => {
    expect(completedFinancialQuarterRange(new Date('2026-01-15T00:00:00Z'))).toEqual({
      startQuarter: '2025q3',
      endQuarter: '2025q4',
    })
  })
})

describe('market quote normalization', () => {
  it('parses string and numeric prices', () => {
    expect(parseMarketNumber('11.1')).toBe(11.1)
    expect(parseMarketNumber(11.1)).toBe(11.1)
    expect(parseMarketNumber(null)).toBeNull()
    expect(parseMarketNumber('')).toBeNull()
    expect(parseMarketNumber('not-a-number')).toBeNull()
  })

  it('normalizes overview quote payloads from the backend', () => {
    const quote = normalizeDeskQuote({
      symbol: '000001.SZ',
      name: '000001.SZ',
      last: '11.1',
      open: '11.0',
      high: '11.3',
      low: '10.9',
      previous_close: '10.96',
      change: null,
      // 后端合同以比例传输涨跌幅；展示层归一化为百分数。
      change_percent: '0.0125',
      volume: '1000000',
      amount: '11100000',
      provider: 'PandaData',
      provider_time: '2026-07-24T15:00:00+08:00',
      frequency: '1m',
      freshness: 'stale',
      market_status: 'released',
      session_alignment: 'latest_released_session',
    })
    expect(quote.last).toBe(11.1)
    expect(quote.open).toBe(11)
    expect(quote.high).toBe(11.3)
    expect(quote.low).toBe(10.9)
    expect(quote.previous_close).toBe(10.96)
    expect(quote.volume).toBe(1000000)
    expect(quote.amount).toBe(11100000)
    expect(quote.change).toBeNull()
    expect(quote.change_percent).toBe(1.25)
    expect(quote.freshness).toBe('stale')
    expect(quote.session_alignment).toBe('latest_released_session')
  })
})

describe('draft reference gate', () => {
  it('allows released close with stale freshness when a last price exists', () => {
    expect(canUseQuoteAsDraftReference({
      last: 11.1,
      freshness: 'stale',
      market_status: 'released',
    })).toBe(true)
  })

  it('allows in-session current quotes', () => {
    expect(canUseQuoteAsDraftReference({
      last: 10,
      freshness: 'current',
      market_status: 'in_session',
    })).toBe(true)
  })

  it('rejects missing price or unusable market status', () => {
    expect(canUseQuoteAsDraftReference({
      last: null,
      freshness: 'stale',
      market_status: 'released',
    })).toBe(false)
    expect(canUseQuoteAsDraftReference({
      last: 11.1,
      freshness: 'stale',
      market_status: 'pre_open',
    })).toBe(false)
    expect(canUseQuoteAsDraftReference({
      last: 11.1,
      freshness: 'error',
      market_status: 'released',
    })).toBe(false)
  })

  it('explains blocked reasons without claiming live-only freshness', () => {
    expect(draftReferenceBlockedReason({
      last: 11.1,
      freshness: 'stale',
      market_status: 'pre_open',
    })).toContain('市场状态')
    expect(draftReferenceBlockedReason(null)).toContain('真实行情')
  })
})
