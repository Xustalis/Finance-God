import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const styles = readFileSync('src/styles.css', 'utf8')

describe('trading desk scroll layout', () => {
  it('keeps the wide desktop columns inside one viewport with independent scrolling', () => {
    expect(styles).toMatch(/@media \(min-width: 1024px\)[\s\S]*?\.desk-page \{[\s\S]*?height: 100svh;[\s\S]*?overflow: hidden;/)
    expect(styles).toMatch(/@media \(min-width: 1024px\)[\s\S]*?\.desk-page \.desk-spread \{[\s\S]*?height: calc\(100svh - 70px\);[\s\S]*?overflow: hidden;/)
    expect(styles).toMatch(/@media \(min-width: 1024px\)[\s\S]*?\.desk-page \.desk-left \{[\s\S]*?display: flex;[\s\S]*?overflow: hidden;/)
    expect(styles).toMatch(/@media \(min-width: 1024px\)[\s\S]*?\.desk-page \.desk-left-content \{[\s\S]*?overflow-y: auto;/)
    expect(styles).toMatch(/\.desk-page \.desk-agent \{[\s\S]*?height: calc\(100svh - 70px\);[\s\S]*?overflow: hidden;/)
    expect(styles).toMatch(/\.agent-thread \{[\s\S]*?overflow-y: auto;/)
  })

  it('returns the stacked layout to natural document scrolling below 1024px', () => {
    expect(styles).toMatch(/@media \(max-width: 1023px\)[\s\S]*?\.desk-page \.desk-spread \{[\s\S]*?height: auto;[\s\S]*?overflow: visible;/)
    expect(styles).toMatch(/@media \(max-width: 1023px\)[\s\S]*?\.desk-page \.desk-left-content \{[\s\S]*?overflow: visible;/)
    expect(styles).toMatch(/@media \(max-width: 1023px\)[\s\S]*?\.desk-page \.desk-agent \{[\s\S]*?height: auto;[\s\S]*?max-height: none;/)
  })
})
