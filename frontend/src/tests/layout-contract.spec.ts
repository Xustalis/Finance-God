import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const overviewSource = readFileSync(
  resolve(process.cwd(), 'src/views/OverviewView.vue'),
  'utf8',
)

describe('desktop shell layout contract', () => {
  it('declares every named grid area used by the overview shell', () => {
    expect(overviewSource).toContain('"masthead" 64px')
    expect(overviewSource).toContain('"tabs" auto')
    expect(overviewSource).toContain('"body" minmax(0, 1fr)')
    expect(overviewSource).toMatch(/\.section-tabs\s*\{\s*grid-area:\s*tabs;/)
    expect(overviewSource).toMatch(/\.headline-body\s*\{\s*grid-area:\s*body;/)
  })
})
