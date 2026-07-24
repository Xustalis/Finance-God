import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import TradePlanView from '@/views/TradePlanView.vue'
import {
  confirmTradePlanAndGenerateDrafts,
  fetchTradePlan,
  saveTradePlanVersion,
} from '@/api/desk'
import type { TradePlanPageView } from '@/types/desk'

vi.mock('@/api/desk', () => ({
  fetchTradePlan: vi.fn(),
  saveTradePlanVersion: vi.fn(),
  confirmTradePlanAndGenerateDrafts: vi.fn(),
  newIdempotencyKey: vi.fn(() => 'trade-plan-confirm:test'),
}))

const pendingView: TradePlanPageView = {
  object: {
    plan_id: 'trade-plan-1',
    account_id: 'account-1',
    revision: 1,
    status: 'pending_review',
    purpose: '补充权益方向候选。',
    actions: [
      {
        action_id: 'action-1',
        instrument_id: '600519.SH',
        side: 'buy',
        order_type: 'market',
        quantity: null,
        limit_price: null,
        reference_price: 1500,
        time_in_force: 'day',
        included: true,
        rationale: '候选尚未被组合覆盖。',
      },
    ],
    estimated_fee_rmb: 0,
    portfolio_impact: '补全数量后计算。',
    disagreements: [],
    workflow_dependencies: [],
    expires_at: '2026-07-24T09:00:00+00:00',
    input_versions: [
      { object_type: 'market_quote', object_id: '600519.SH', version: 'v1' },
    ],
    invalidated_by_versions: [],
    audit_reference: {
      audit_id: 'audit-1',
      actor_id: 'owner-1',
      recorded_at: '2026-07-24T08:00:00+00:00',
    },
  },
  source_type: 'candidate',
  source_id: '600519.SH',
  version: '1',
  generated_at: '2026-07-24T08:00:00+00:00',
  data_status: {
    provider: 'PandaData',
    provider_time: '2026-07-24T08:00:00+00:00',
    frequency: 'snapshot',
    freshness: 'fresh',
    last_success_at: '2026-07-24T08:00:00+00:00',
  },
  capabilities: [
    { action: 'save_version', enabled: true, reason_code: null, reason: null },
    {
      action: 'confirm_and_generate',
      enabled: false,
      reason_code: 'PLAN_BLOCKED',
      reason: '请补全全部纳入动作的数量并保存新版本。',
    },
  ],
  warnings: [
    {
      code: 'ACTION_QUANTITY_REQUIRED',
      severity: 'blocking',
      message: '至少一个纳入动作尚未填写数量。',
      affected_fields: ['actions.quantity'],
    },
  ],
  draft_links: [],
  history: [
    {
      revision: 1,
      status: 'pending_review',
      recorded_at: '2026-07-24T08:00:00+00:00',
      actor_id: 'owner-1',
    },
  ],
}

describe('T04 trade plan page', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(fetchTradePlan).mockResolvedValue(structuredClone(pendingView))
  })

  it('saves a new version before confirming and renders generated draft links', async () => {
    const revised = structuredClone(pendingView)
    revised.object.revision = 2
    revised.object.actions[0].quantity = 10
    revised.object.estimated_fee_rmb = 4.5
    revised.object.portfolio_impact = '仿真现金变化约为 -15004.50 元。'
    revised.version = '2'
    revised.warnings = []
    revised.capabilities[1] = {
      action: 'confirm_and_generate',
      enabled: true,
      reason_code: null,
      reason: null,
    }
    vi.mocked(saveTradePlanVersion).mockResolvedValue(revised)

    const confirmed = structuredClone(revised)
    confirmed.object.revision = 3
    confirmed.object.status = 'confirmed'
    confirmed.version = '3'
    confirmed.draft_links = [
      { action_id: 'action-1', draft_id: 'draft-1', draft_revision: 1 },
    ]
    confirmed.capabilities[0] = {
      action: 'save_version',
      enabled: false,
      reason_code: 'PLAN_NOT_EDITABLE',
      reason: '当前计划版本不可编辑。',
    }
    confirmed.capabilities[1] = {
      action: 'confirm_and_generate',
      enabled: false,
      reason_code: 'PLAN_BLOCKED',
      reason: '当前已确认版本的订单草稿已经生成。',
    }
    vi.mocked(confirmTradePlanAndGenerateDrafts).mockResolvedValue(confirmed)

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/trade-plans/:planId', component: TradePlanView },
        { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
      ],
    })
    await router.push('/trade-plans/trade-plan-1')
    await router.isReady()
    const wrapper = mount(TradePlanView, {
      global: { plugins: [createPinia(), router] },
    })
    await flushPromises()

    expect(wrapper.get('[data-test="confirm-plan"]').attributes('disabled')).toBeDefined()
    await wrapper.get('input[aria-label="600519.SH 计划数量"]').setValue('10')
    expect(wrapper.get('[data-test="save-plan-version"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-test="save-plan-version"]').trigger('click')
    await flushPromises()

    expect(saveTradePlanVersion).toHaveBeenCalledWith(
      'trade-plan-1',
      1,
      [{ action_id: 'action-1', quantity: 10, included: true }],
    )
    expect(wrapper.text()).toContain('版本 v2')

    await wrapper.get('[data-test="confirm-plan"]').trigger('click')
    await flushPromises()

    expect(confirmTradePlanAndGenerateDrafts).toHaveBeenCalledWith(
      'trade-plan-1',
      2,
      'trade-plan-confirm:test',
    )
    expect(wrapper.text()).toContain('已生成 1 个订单草稿')
    expect(wrapper.text()).toContain('进入交易台')
  })
})
