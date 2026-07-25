import { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'
import {
  apiError,
  DESK_AGENT_REQUEST_TIMEOUT_MS,
} from '@/services/tradingDesk'

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
})
