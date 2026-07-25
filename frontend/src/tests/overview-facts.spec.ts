import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import OverviewWorkspace from '@/components/desk/OverviewWorkspace.vue'

function baseProps() {
  return {
    quotes: [],
    bars: [],
    selectedSymbol: '000001.SZ',
    loading: false,
    marketError: null,
    barsError: null,
    marketLoadedAt: null,
    marketNews: null,
    marketNewsError: null,
    marketNewsNotice: null,
    onSelectSymbol: vi.fn(),
    onRefresh: vi.fn(),
  }
}

describe('OverviewWorkspace market facts', () => {
  it('renders the selected real quote with upstream time, frequency, and freshness', () => {
    const wrapper = mount(OverviewWorkspace, {
      props: {
        ...baseProps(),
        quotes: [{
          symbol: '000001.SZ',
          name: '平安银行',
          last: 12.34,
          change: 0.12,
          change_percent: 0.98,
          provider_time: '2026-07-25T01:00:00Z',
          frequency: '1m',
          freshness: 'current',
          market_status: 'in_session',
        }],
      },
    })

    expect(wrapper.text()).toContain('平安银行')
    expect(wrapper.text()).toContain('12.34')
    expect(wrapper.text()).toContain('1m')
    expect(wrapper.text()).toContain('current')
    expect(wrapper.text()).toContain('2026/07/25 09:00:00')
  })

  it('shows a real market failure without inventing a last price', () => {
    const wrapper = mount(OverviewWorkspace, {
      props: {
        ...baseProps(),
        marketError: 'PandaData 暂时不可用',
      },
    })

    expect(wrapper.get('[role="alert"]').text()).toContain('PandaData 暂时不可用')
    expect(wrapper.find('.chart-last').exists()).toBe(false)
  })

  it('renders only HTTP crawler links as external navigation', () => {
    const wrapper = mount(OverviewWorkspace, {
      props: {
        ...baseProps(),
        marketNews: {
          provider: 'Finance-God Public News Crawler',
          data_mode: 'real',
          trade_eligible: false,
          requested_at: '2026-07-25T07:00:00Z',
          fetched_at: '2026-07-25T07:00:00Z',
          freshness: { status: 'fresh', age_seconds: 0, ttl_seconds: 300, cached: false },
          warnings: [],
          items: [
            {
              id: 'safe',
              title: '安全链接',
              summary: '',
              source: '公开来源',
              url: 'https://example.com/news',
              publish_time: '2026-07-25T06:00:00Z',
              sector: null,
              tags: [],
            },
            {
              id: 'unsafe',
              title: '不安全链接',
              summary: '',
              source: '未知来源',
              url: 'javascript:alert(1)',
              publish_time: null,
              sector: null,
              tags: [],
            },
          ],
        },
      },
    })

    expect(wrapper.findAll('.news-item')).toHaveLength(2)
    expect(wrapper.findAll('.news-item a')).toHaveLength(1)
    expect(wrapper.get('.news-item a').attributes('href')).toBe('https://example.com/news')
  })
})
