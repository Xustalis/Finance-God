import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeskAgentPanel from '@/components/desk/DeskAgentPanel.vue'
import { useTradingDeskStore } from '@/stores/tradingDesk'

function mountAgent() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useTradingDeskStore()
  store.serverContextVersion = 'desk:user:information:600519.SH:1'
  store.bootstrapStatus = 'ready'
  store.deskCapabilities = { agent_answer: true, workflow_create: true, workflow_worker: true }
  const wrapper = mount(DeskAgentPanel, { props: { collapsed: false }, global: { plugins: [pinia] } })
  return { store, wrapper }
}

describe('DeskAgentPanel message bubbles', () => {
  it('keeps submission context implicit instead of rendering a summary block', async () => {
    const { store, wrapper } = mountAgent()
    store.agentPreview = {
      mode: 'workflow',
      workflow_key: 'company_research',
      workflow_title: '公司研究',
      expected_roles: ['tradingagents:market_analyst'],
      artifact_types: ['ResearchMemo'],
      can_start: true,
    }
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[aria-label="提交前任务上下文"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('本次提交依据')
  })

  it('distinguishes context loading from a bootstrap failure and offers retry only on failure', async () => {
    const { store, wrapper } = mountAgent()
    store.bootstrapStatus = 'loading'
    store.serverContextVersion = null
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('正在同步交易台上下文')
    expect(wrapper.text()).not.toContain('不能创建可审计任务')
    expect(wrapper.find('.agent-bootstrap-error').exists()).toBe(false)

    store.bootstrapStatus = 'error'
    store.bootstrapError = 'UNAUTHORIZED · 登录状态已失效'
    await wrapper.vm.$nextTick()

    expect(wrapper.get('.agent-bootstrap-error').text()).toContain('登录状态已失效')
    expect(wrapper.get('.agent-bootstrap-error button').text()).toBe('重新连接')
  })

  it('renders ordinary user and assistant messages as separate bubbles', async () => {
    const { store, wrapper } = mountAgent()
    store.agentMessages = [
      { id: 'u1', role: 'user', kind: 'text', createdAt: '2026-07-25T00:00:00Z', text: '你好' },
      { id: 'a1', role: 'assistant', kind: 'text', createdAt: '2026-07-25T00:00:01Z', text: '你好，我可以协助研究。', status: 'complete' },
    ]
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.agent-chat-message')).toHaveLength(2)
    expect(wrapper.find('.agent-chat-message.is-user').text()).toContain('你好')
    expect(wrapper.find('.agent-chat-message.is-assistant').text()).toContain('协助研究')
  })

  it('keeps conversation input available while a formal workflow is running', async () => {
    const { store, wrapper } = mountAgent()
    store.activeWorkflow = {
      run_id: 'run-active',
      status: 'running',
      workflow_key: 'company_research',
      workflow_version: '1',
      request_intent: '研究贵州茅台',
      revision: 2,
      created_at: '2026-07-25T00:00:00Z',
      updated_at: '2026-07-25T00:01:00Z',
      final_artifact: null,
    }
    await wrapper.vm.$nextTick()

    const input = wrapper.get<HTMLTextAreaElement>('[aria-label="向交易 Agent 输入指令"]')
    expect(input.element.disabled).toBe(false)
    expect(input.attributes('placeholder')).toContain('仍可提问')
  })

  it('keeps workflow progress inside a collapsible task bubble', async () => {
    const { store, wrapper } = mountAgent()
    store.activeWorkflow = {
      run_id: 'run-active',
      status: 'running',
      workflow_key: 'company_research',
      workflow_version: '1',
      request_intent: '研究贵州茅台',
      revision: 2,
      final_artifact: null,
    }
    store.activeWorkflowProgress = {
      run_id: 'run-active',
      workflow_key: 'company_research',
      workflow_version: '1',
      status: 'running',
      revision: 2,
      updated_at: '2026-07-25T00:01:00Z',
      total_node_count: 2,
      completed_node_artifact_count: 1,
      completed_node_artifacts: [],
      errors: [],
      is_terminal: false,
      nodes: [{
        node_id: 'market',
        title: '核查行情与估值',
        status: 'running',
        agent_ids: ['tradingagents:market_analyst'],
        service_id: null,
        attempt: 1,
        updated_at: '2026-07-25T00:01:00Z',
      }],
    }
    store.agentMessages = [{
      id: 'workflow-run-active',
      role: 'assistant',
      kind: 'workflow',
      createdAt: '2026-07-25T00:00:00Z',
      runId: 'run-active',
      intent: '研究贵州茅台',
      status: 'running',
    }]
    await wrapper.vm.$nextTick()

    const receipt = wrapper.get('.agent-chat-message.is-workflow')
    expect(receipt.text()).toContain('正式任务已开始执行')
    expect(receipt.text()).toContain('运行信息')
    expect(wrapper.find('[aria-label="当前工作流运行状态"]').exists()).toBe(false)

    const refresh = vi.spyOn(store, 'refreshWorkflow').mockResolvedValue()
    const details = receipt.get<HTMLDetailsElement>('.workflow-message-detail')
    expect(details.element.open).toBe(true)
    await details.trigger('toggle')
    await wrapper.vm.$nextTick()
    expect(refresh).toHaveBeenCalled()
    expect(details.text()).toContain('1 / 2 个节点产物')
    expect(details.text()).toContain('核查行情与估值')
    expect(details.find('.agent-task-list').exists()).toBe(true)
  })

  it('shows accepted and started workflow states directly in the Agent conversation', async () => {
    const { store, wrapper } = mountAgent()
    store.agentMessages = [{
      id: 'workflow-run-queued',
      role: 'assistant',
      kind: 'workflow',
      createdAt: '2026-07-25T00:00:00Z',
      runId: 'run-queued',
      intent: '研究贵州茅台',
      status: 'queued',
    }]
    await wrapper.vm.$nextTick()

    const receipt = wrapper.get('.agent-chat-message.is-workflow')
    expect(receipt.text()).toContain('正式任务已受理')
    expect(receipt.text()).not.toContain('正式任务已开始执行')
    expect(receipt.get<HTMLDetailsElement>('.workflow-message-detail').element.open).toBe(true)

    store.agentMessages = [{
      id: 'workflow-run-queued',
      role: 'assistant',
      kind: 'workflow',
      createdAt: '2026-07-25T00:00:00Z',
      runId: 'run-queued',
      intent: '研究贵州茅台',
      status: 'running',
    }]
    await wrapper.vm.$nextTick()

    expect(receipt.text()).toContain('正式任务已开始执行')
    expect(receipt.get<HTMLDetailsElement>('.workflow-message-detail').element.open).toBe(true)
  })

  it('explains a known quality-gate error instead of exposing its internal code', async () => {
    const { store, wrapper } = mountAgent()
    store.activeWorkflow = {
      run_id: 'run-attention',
      status: 'attention_required',
      workflow_key: 'portfolio_stress',
      workflow_version: '1',
      request_intent: '核查组合压力',
      revision: 3,
      final_artifact: null,
    }
    store.activeWorkflowProgress = {
      run_id: 'run-attention',
      workflow_key: 'portfolio_stress',
      workflow_version: '1',
      status: 'attention_required',
      revision: 3,
      updated_at: '2026-07-25T00:01:00Z',
      total_node_count: 8,
      completed_node_artifact_count: 3,
      completed_node_artifacts: [],
      errors: ['deterministic_quality_gate_failed'],
      is_terminal: true,
      nodes: [],
    }
    store.agentMessages = [{
      id: 'workflow-run-attention',
      role: 'assistant',
      kind: 'workflow',
      createdAt: '2026-07-25T00:00:00Z',
      runId: 'run-attention',
      intent: '核查组合压力',
      status: 'attention_required',
    }]
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('确定性输入校验未通过，请检查失败节点后重试。')
    expect(wrapper.text()).not.toContain('deterministic_quality_gate_failed')
  })

  it('renders queued formal tasks in a collapsible list', async () => {
    const { store, wrapper } = mountAgent()
    store.queuedWorkflowIntents = [{
      id: 'queued-1',
      intent: '研究宁德时代供应链风险',
      createdAt: '2026-07-25T00:02:00Z',
    }]
    await wrapper.vm.$nextTick()

    const queue = wrapper.get('.queued-workflows')
    expect(queue.text()).toContain('待执行正式任务')
    expect(queue.text()).toContain('研究宁德时代供应链风险')
    await queue.get('button').trigger('click')
    expect(store.queuedWorkflowIntents).toHaveLength(0)
  })

  it('keeps a research report inside an assistant bubble', async () => {
    const { store, wrapper } = mountAgent()
    store.agentMessages = [{
      id: 'report-1',
      role: 'assistant',
      kind: 'research_report',
      createdAt: '2026-07-25T00:00:00Z',
      runId: 'run-1',
      evidence: {
        object_type: 'evidence_bundle',
        object_id: 'bundle-1',
        version: '1',
        subject: '600519.SH',
        conclusion: '盈利质量稳定，但估值风险仍需跟踪。',
        provider: 'multi-agent',
        generated_at: '2026-07-25T00:00:00Z',
        facts: [{ kind: 'fact', statement: '收入保持增长。', author_agent_id: 'analyst', evidence_ids: ['E1'], unknowns: [], invalidation_conditions: [] }],
        inferences: [],
        counterpoints: ['估值处于历史较高区间。'],
        unknowns: [],
        invalidation_conditions: [],
        sources: [{ identifier: 'E1', source: 'PandaData', excerpt: '公司披露数据' }],
        agent_nodes: [],
        notices: [],
      },
    }]
    await wrapper.vm.$nextTick()
    const bubble = wrapper.get('.agent-chat-message.is-research_report')
    expect(bubble.text()).toContain('研究报告')
    expect(bubble.text()).toContain('盈利质量稳定')
    expect(bubble.text()).toContain('估值处于历史较高区间')
  })

  it('keeps an order draft inside an assistant bubble with an explicit review action', async () => {
    const { store, wrapper } = mountAgent()
    store.agentMessages = [{
      id: 'draft-1',
      role: 'assistant',
      kind: 'order_draft',
      createdAt: '2026-07-25T00:00:00Z',
      draft: {
        record_revision: 1,
        owner_id: 'user',
        mode: 'manual',
        draft: {
          draft_id: 'draft-1',
          status: 'draft',
          revision: 1,
          account_id: 'account-1',
          instrument_id: '600519.SH',
          side: 'buy',
          order_type: 'limit',
          quantity: '100',
          amount: null,
          limit_price: '1500.00',
          time_in_force: 'day',
          valid_until: '2026-07-26T00:00:00Z',
          input_versions: [],
        },
        reference_price: '1498.00',
        review: null,
        risk_result: null,
        cost_estimate: null,
        immutable_summary_hash: null,
        confirmed_at: null,
      },
    }]
    await wrapper.vm.$nextTick()
    const bubble = wrapper.get('.agent-chat-message.is-order_draft')
    expect(bubble.text()).toContain('模拟订单草稿')
    expect(bubble.text()).toContain('600519.SH')
    expect(bubble.text()).toContain('尚未提交')
    expect(bubble.get('button').text()).toContain('前往复核')
  })
})
