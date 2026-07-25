import { describe, expect, it } from 'vitest'
import { parseInstrumentId, requireInstrumentId } from '@/domain/instrumentId'

describe('InstrumentId contract', () => {
  it('normalizes supported exchange suffixes without changing the market', () => {
    expect(parseInstrumentId(' 000001.sz ')).toBe('000001.SZ')
    expect(parseInstrumentId('000001.sh')).toBe('000001.SH')
    expect(parseInstrumentId('aapl.us')).toBe('AAPL.US')
  })

  it('rejects missing, unknown, and malformed exchange suffixes', () => {
    expect(parseInstrumentId('000001')).toBeNull()
    expect(parseInstrumentId('000001.XX')).toBeNull()
    expect(parseInstrumentId('AAPL.SH')).toBeNull()
    expect(() => requireInstrumentId('000001.XX')).toThrow('合法交易所后缀')
  })
})
