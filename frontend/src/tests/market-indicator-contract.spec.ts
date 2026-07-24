import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const marketStoreSource = readFileSync(
  resolve(process.cwd(), 'src/stores/market.ts'),
  'utf8',
)
const overviewSource = readFileSync(
  resolve(process.cwd(), 'src/views/OverviewView.vue'),
  'utf8',
)

describe('market indicator ownership', () => {
  it('keeps market classifications and indicator formulas out of the browser', () => {
    expect(marketStoreSource).not.toContain('marketSignal')
    expect(marketStoreSource).not.toContain('marketVolatility')
    expect(marketStoreSource).not.toContain('marketBreadth')
    expect(marketStoreSource).not.toContain('Math.sqrt')
    expect(overviewSource).not.toContain('trendScore')
    expect(overviewSource).not.toContain('volScore')
    expect(overviewSource).not.toContain('volumeScore')
    expect(overviewSource).not.toContain('Math.sqrt')
  })

  it('renders backend algorithm, data version, freshness, frequency, and definitions', () => {
    expect(overviewSource).toContain('signal?.definition')
    expect(overviewSource).toContain('indicator.definition')
    expect(overviewSource).toContain('market.overview?.algorithm_version')
    expect(overviewSource).toContain('market.overview?.version')
    expect(overviewSource).toContain('market.overview?.data_status.frequency')
    expect(overviewSource).toContain('market.overview?.data_status.freshness')
  })
})
