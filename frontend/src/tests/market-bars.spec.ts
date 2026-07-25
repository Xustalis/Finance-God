import { describe, expect, it } from 'vitest'
import { assertBarFrequency, DeskApiError, normalizeDeskBars } from '@/services/tradingDesk'

describe('normalizeDeskBars', () => {
  it('converts Decimal JSON strings, sorts timestamps, and keeps the latest duplicate', () => {
    const bars = normalizeDeskBars([
      {
        time: '2026-07-24T09:32:00+08:00',
        open: '11.0',
        high: '12.0',
        low: '10.0',
        close: '11.5',
        volume: '200',
      },
      {
        time: '2026-07-24T09:31:00+08:00',
        open: '10.0',
        high: '11.0',
        low: '9.0',
        close: '10.5',
        volume: '100',
      },
      {
        time: '2026-07-24T09:32:00+08:00',
        open: '11.1',
        high: '12.1',
        low: '10.1',
        close: '11.6',
        volume: '220',
      },
    ])

    expect(bars).toHaveLength(2)
    expect(bars.map((bar) => bar.time)).toEqual([
      '2026-07-24T01:31:00.000Z',
      '2026-07-24T01:32:00.000Z',
    ])
    expect(bars[1]).toMatchObject({
      open: 11.1,
      high: 12.1,
      low: 10.1,
      close: 11.6,
      volume: 220,
    })
  })

  it('fails explicitly when a required number is invalid', () => {
    expect(() => normalizeDeskBars([{
      time: '2026-07-24T09:31:00+08:00',
      open: 'not-a-number',
      high: '11',
      low: '9',
      close: '10',
      volume: '100',
    }])).toThrow(DeskApiError)
  })

  it('rejects a minute response for a daily request', () => {
    expect(() => assertBarFrequency('daily', '1分钟')).toThrow(
      'K线频率不匹配：请求 daily，服务端返回 1分钟',
    )
    expect(() => assertBarFrequency('daily', '日频')).not.toThrow()
    expect(() => assertBarFrequency('1m', '1分钟')).not.toThrow()
  })
})
