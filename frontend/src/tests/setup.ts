import { Storage } from 'happy-dom'
import { afterEach, beforeEach, vi } from 'vitest'

const testStorage = new Storage()

// happy-dom 缺少 lightweight-charts 需要的 canvas/ResizeObserver 与颜色解析能力，
// 在单元测试中将图表库 stub 成空实现，避免图表初始化异常打断交易台组件挂载。
vi.mock('lightweight-charts', () => {
  const noop = () => ({})
  const stubSeries = { setData: noop, applyOptions: noop }
  return {
    createChart: () => ({
      addSeries: () => stubSeries,
      priceScale: () => ({ applyOptions: noop }),
      timeScale: () => ({ applyOptions: noop, fitContent: noop }),
      applyOptions: noop,
      remove: noop,
    }),
    ColorType: { Solid: 'solid' },
    CrosshairMode: { Normal: 0 },
    CandlestickSeries: 'candlestick',
    HistogramSeries: 'histogram',
    LineSeries: 'line',
  }
})

beforeEach(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: testStorage,
  })
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: testStorage,
  })
})

afterEach(() => {
  document.body.innerHTML = ''
  testStorage.clear()
})
