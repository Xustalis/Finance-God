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
    sentimentError: null,
    informationError: null,
    marketNews: null,
    onSelectSymbol: vi.fn(),
    onRefresh: vi.fn(),
  }
}

describe('OverviewWorkspace PandaData facts', () => {
  it('renders only labeled margin business metrics', () => {
    const wrapper = mount(OverviewWorkspace, {
      props: {
        ...baseProps(),
        sentimentFacts: {
          provider: 'PandaData',
          fact_kind: 'margin_balance' as const,
          symbol: '000001.SZ',
          requested_at: '2026-06-25T08:00:00Z',
          facts: [{
            fields: [
              { name: 'date', value: '20260625' },
              { name: 'margin_type', value: 'stock' },
              { name: 'short_balance', value: 17770268 },
              { name: 'symbol', value: '000001.SZ' },
            ],
          }],
        },
        informationFacts: null,
      },
    })

    const strip = wrapper.get('.sentiment-detail-strip')
    expect(strip.text()).toContain('融券余额')
    expect(strip.text()).toContain('17,770,268')
    expect(strip.text()).not.toContain('margin_type')
    expect(strip.text()).not.toContain('000001.SZ')
  })

  it('skips empty and structural disclosure fields before summarizing', () => {
    const wrapper = mount(OverviewWorkspace, {
      props: {
        ...baseProps(),
        sentimentFacts: null,
        informationFacts: {
          provider: 'PandaData',
          fact_kind: 'company_disclosure' as const,
          symbol: '000001.SZ',
          requested_at: '2026-04-25T08:00:00Z',
          facts: [{
            source: {
              data_time: '2026-04-25T08:00:00Z',
              evidence_ref: 'fact-1',
            },
            fields: [
              { name: 'bs_acc_exp', value: null },
              { name: 'bs_accounts_pay', value: null },
              { name: 'date', value: '20260425' },
              { name: 'revenue', value: 1234567 },
              { name: 'symbol', value: '000001.SZ' },
            ],
          }],
        },
      },
    })

    const title = wrapper.get('.news-title')
    expect(title.text()).toBe('revenue：1,234,567')
    expect(title.text()).not.toContain('bs_acc_exp')
    expect(title.text()).not.toContain('symbol')
  })

  it('shows an explicit empty state when a disclosure has no usable metric', () => {
    const wrapper = mount(OverviewWorkspace, {
      props: {
        ...baseProps(),
        sentimentFacts: null,
        informationFacts: {
          provider: 'PandaData',
          fact_kind: 'company_disclosure' as const,
          symbol: '000001.SZ',
          requested_at: '2026-04-25T08:00:00Z',
          facts: [{
            fields: [
              { name: 'bs_acc_exp', value: null },
              { name: 'symbol', value: '000001.SZ' },
            ],
          }],
        },
      },
    })

    expect(wrapper.get('.news-title').text()).toBe('本次披露未返回可用财务指标')
  })
})
