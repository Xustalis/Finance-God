import { describe, expect, it } from 'vitest'
import { financeApiBase, v1ApiBase } from '@/services/apiBase'

describe('API base routing', () => {
  it('keeps v1 and finance API families on their independent same-origin mounts', () => {
    expect(v1ApiBase({})).toBe('/api/v1')
    expect(financeApiBase({})).toBe('/api')
  })

  it('does not route finance requests through a configured v1 base', () => {
    const environment = { VITE_API_BASE_URL: 'https://example.test/api/v1/' }
    expect(v1ApiBase(environment)).toBe('https://example.test/api/v1')
    expect(financeApiBase(environment)).toBe('/api')
  })

  it('accepts an explicit finance API mount', () => {
    expect(financeApiBase({
      VITE_API_BASE_URL: '/custom/v1',
      VITE_FINANCE_API_BASE_URL: 'https://finance.example.test/api/finance/',
    })).toBe('https://finance.example.test/api/finance')
  })
})
