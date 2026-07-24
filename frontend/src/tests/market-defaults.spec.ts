import { describe, expect, it } from 'vitest'

import { symbolsForDirection } from '@/services/directionDesk'
import { DEFAULT_SYMBOLS } from '@/types/desk'

describe('market defaults', () => {
  it('requests only the verified default snapshot instruments', () => {
    expect(DEFAULT_SYMBOLS).toEqual([
      '000001.SZ',
      '000002.SZ',
      '600519.SH',
      '601318.SH',
      '600036.SH',
      '000858.SZ',
      '002594.SZ',
      '300750.SZ',
    ])
    expect(new Set(DEFAULT_SYMBOLS).size).toBe(DEFAULT_SYMBOLS.length)
  })

  it('uses the same verified defaults when no investment direction exists', () => {
    expect(symbolsForDirection(null)).toEqual(DEFAULT_SYMBOLS)
  })
})
