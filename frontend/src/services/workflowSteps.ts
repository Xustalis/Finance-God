/* ═══════════════════════════════════════════════════
   工作流进度读模型 — 由真实 AgentRun 派生逐步进度
   Phase 3（Option A）：右侧 agent 的“工作状态”即 Multi-Agent
   运行计划的逐 agent 步骤。步骤状态严格由运行事实派生，不伪造：
   - 计划内 agent 且有结论 → done
   - 计划内 agent 被路由拦截（缺资源/授权）→ blocked
   - 计划内 agent 既无结论也无拦截通知 → blocked（未产出）
   完成后面板折叠为摘要，可展开查看每步结论与建议动作。
   ═══════════════════════════════════════════════════ */

import type { AgentRun } from '@/types/desk'

export type WorkflowStepStatus = 'done' | 'blocked'

export interface WorkflowStep {
  agentId: string
  reason: string
  status: WorkflowStepStatus
  summary: string | null
  proposedActions: string[]
  missing: string[]
}

export interface WorkflowProgressView {
  steps: WorkflowStep[]
  doneCount: number
  blockedCount: number
  total: number
}

/** 由已完成的 AgentRun 派生逐步进度；run 为空返回空视图。 */
export function deriveWorkflowSteps(run: AgentRun | null): WorkflowProgressView {
  if (!run) {
    return { steps: [], doneCount: 0, blockedCount: 0, total: 0 }
  }

  const resultByAgent = new Map(run.results.map((r) => [r.agent_id, r]))
  const noticeByAgent = new Map(run.plan.notices.map((n) => [n.agent_id, n]))

  const steps: WorkflowStep[] = []
  const seen = new Set<string>()

  for (const assignment of run.plan.assignments) {
    seen.add(assignment.agent_id)
    const result = resultByAgent.get(assignment.agent_id)
    const notice = noticeByAgent.get(assignment.agent_id)
    if (result) {
      steps.push({
        agentId: assignment.agent_id,
        reason: assignment.reason,
        status: 'done',
        summary: result.summary,
        proposedActions: result.proposed_actions,
        missing: [],
      })
    } else {
      steps.push({
        agentId: assignment.agent_id,
        reason: assignment.reason,
        status: 'blocked',
        summary: null,
        proposedActions: [],
        missing: notice
          ? [...notice.missing_resources, ...notice.missing_authorizations]
          : [],
      })
    }
  }

  // 出现在结论中但未列入计划的 agent（边界情况）：作为已完成步骤补入。
  for (const result of run.results) {
    if (seen.has(result.agent_id)) continue
    steps.push({
      agentId: result.agent_id,
      reason: '运行时补充产出',
      status: 'done',
      summary: result.summary,
      proposedActions: result.proposed_actions,
      missing: [],
    })
  }

  const doneCount = steps.filter((s) => s.status === 'done').length
  const blockedCount = steps.length - doneCount
  return { steps, doneCount, blockedCount, total: steps.length }
}
