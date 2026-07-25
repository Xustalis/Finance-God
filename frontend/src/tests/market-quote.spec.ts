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
      change: null,
      change_percent: '1.25',
      provider: 'PandaData',
      provider_time: '2026-07-24T15:00:00+08:00',
      frequency: '1m',
      freshness: 'stale',
      market_status: 'released',
    })
    expect(quote.last).toBe(11.1)
    expect(quote.change).toBeNull()
    expect(quote.change_percent).toBe(1.25)
    expect(quote.freshness).toBe('stale')
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
