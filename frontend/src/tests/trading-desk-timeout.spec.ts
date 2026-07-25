import { AxiosError } from 'axios'
import { describe, expect, it, vi } from 'vitest'
import {
  apiError,
  DESK_AGENT_REQUEST_TIMEOUT_MS,
  fetchProfile,
  streamDeskAgentDecision,
} from '@/services/tradingDesk'
import { profileApi } from '@/api'

describe('trading desk agent timeout policy', () => {
  it('allows agent endpoints to outlive the default request timeout', () => {
    expect(DESK_AGENT_REQUEST_TIMEOUT_MS).toBe(70_000)
  })

  it('does not expose the raw Axios timeout message', () => {
    const error = new AxiosError(
      'timeout of 30000ms exceeded',
      AxiosError.ECONNABORTED,
    )

    expect(apiError(error).message).toBe('Agent 服务响应超时，请重新连接')
  })

  it('reads the profile through the independent v1 client', async () => {
    const profile = { profile: { id: 'profile-1' }, recommendations: [] }
    const latest = vi.spyOn(profileApi, 'latest').mockResolvedValue(profile as never)

    await expect(fetchProfile()).resolves.toBe(profile)
    expect(latest).toHaveBeenCalledOnce()
  })

  it('rejects an Agent stream that reaches EOF without a done event', async () => {
    const decision = {
      decision_id: 'decision-1',
      decision_source: 'agent_generated_policy_approved',
      mode: 'answer',
      message: 'ok',
      workflow_key: null,
      workflow_title: null,
      routing_reason: 'direct',
      expected_stages: [],
      can_start: true,
      answer_text: null,
      ui_actions: [],
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      `${JSON.stringify({ type: 'start', decision })}\n`
      + `${JSON.stringify({ type: 'delta', text: '未完成' })}\n`,
      { headers: { 'content-type': 'application/x-ndjson' } },
    )))

    await expect(streamDeskAgentDecision({
      message: '测试',
      section: 'information',
      symbol: '000001.SZ',
      contextVersion: 'desk:user:information:000001.SZ:1',
      activeWorkflow: false,
    }, vi.fn())).rejects.toMatchObject({ code: 'AI_STREAM_INCOMPLETE' })
  })
})
