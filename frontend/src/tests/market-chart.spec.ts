import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MarketChart, { type ChartPeriod } from '@/components/desk/MarketChart.vue'
import type { DeskBar } from '@/services/tradingDesk'

// setup.ts 已经将 lightweight-charts stub 成空实现，MarketChart 在 happy-dom 中可正常挂载。
// 这里只验证周期按钮的可见状态与点击切换，不验证图表渲染本身。

function makeBars(count = 10): DeskBar[] {
  const out: DeskBar[] = []
  const base = new Date('2026-07-01T00:00:00Z').getTime()
  for (let i = 0; i < count; i++) {
    const day = new Date(base + i * 86_400_000)
    const iso = day.toISOString()
    out.push({
      time: iso,
      open: 10 + i,
      high: 11 + i,
      low: 9 + i,
      close: 10.5 + i,
      volume: 1000 + i,
    })
  }
  return out
}

const PERIODS: Array<{ key: ChartPeriod; label: string }> = [
  { key: '1m', label: '分时' },
  { key: '5m', label: '5分' },
  { key: '15m', label: '15分' },
  { key: '60m', label: '1小时' },
  { key: 'daily', label: '日线' },
  { key: 'weekly', label: '周线' },
  { key: 'monthly', label: '月线' },
]

function mountChart() {
  return mount(MarketChart, {
    props: {
      quote: {
        symbol: '000001.SH',
        name: '上证指数',
        last: 3200.5,
        open: 3180,
        high: 3210,
        low: 3175,
        previous_close: 3175,
        change: 25.5,
        change_percent: 0.8,
        volume: 1e8,
        amount: 2e9,
        provider_time: '2026-07-25T10:00:00Z',
        freshness: 'in_session',
      },
      bars: makeBars(),
      loading: false,
      error: null,
      onPeriodChange: vi.fn(),
    },
  })
}

describe('MarketChart period tabs', () => {
  it('defaults to 日线 active and renders every period as a focusable button', () => {
    const wrapper = mountChart()
    const tabs = wrapper.findAll('[aria-label="K线周期"] .period-tab')
    expect(tabs).toHaveLength(PERIODS.length)

    const activeLabels = tabs.filter((tab) => tab.classes('active')).map((tab) => tab.text())
    expect(activeLabels).toEqual(['日线'])

    // 全部都是真正的 button，且 active 标记同步到 aria-pressed
    for (const tab of tabs) {
      expect(tab.element.tagName).toBe('BUTTON')
      expect(tab.attributes('type')).toBe('button')
      expect(tab.attributes('aria-pressed')).toBe(tab.classes('active') ? 'true' : 'false')
    }
  })

  it('moves the active state to the clicked period and clears 日线', async () => {
    const wrapper = mountChart()
    const daily = wrapper.findAll('.period-tab').find((tab) => tab.text() === '日线')!
    expect(daily.classes('active')).toBe(true)

    // 点击 5分 后，active 应离开日线、落在 5分
    const fiveMin = wrapper.findAll('.period-tab').find((tab) => tab.text() === '5分')!
    await fiveMin.trigger('click')

    expect(daily.classes('active')).toBe(false)
    expect(fiveMin.classes('active')).toBe(true)
    expect(daily.attributes('aria-pressed')).toBe('false')
    expect(fiveMin.attributes('aria-pressed')).toBe('true')
  })

  it('keeps exactly one active tab when cycling through every period', async () => {
    const wrapper = mountChart()
    for (const period of PERIODS) {
      const tab = wrapper.findAll('.period-tab').find((t) => t.text() === period.label)!
      await tab.trigger('click')
      const active = wrapper.findAll('.period-tab.active')
      expect(active).toHaveLength(1)
      expect(active[0].text()).toBe(period.label)
    }
  })

  it('notifies the parent of the requested server-side frequency', async () => {
    const onPeriodChange = vi.fn()
    const wrapper = mount(MarketChart, {
      props: {
        quote: null,
        bars: makeBars(),
        loading: false,
        error: null,
        onPeriodChange,
      },
    })

    const find = (label: string) => wrapper.findAll('.period-tab').find((t) => t.text() === label)!
    await find('5分').trigger('click')
    await find('分时').trigger('click')
    await find('日线').trigger('click')
    await find('周线').trigger('click')

    expect(onPeriodChange).toHaveBeenNthCalledWith(1, '1m')
    expect(onPeriodChange).toHaveBeenNthCalledWith(2, '1m')
    expect(onPeriodChange).toHaveBeenNthCalledWith(3, 'daily')
    expect(onPeriodChange).toHaveBeenNthCalledWith(4, 'daily')
  })
})
