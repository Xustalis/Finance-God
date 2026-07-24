import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const requestInterceptor = vi.fn()
  return {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    requestInterceptor,
    create: vi.fn(() => ({
      get: mocks.get,
      post: mocks.post,
      put: mocks.put,
      interceptors: {
        request: { use: mocks.requestInterceptor },
      },
    })),
  }
})

vi.mock('axios', () => ({
  default: { create: mocks.create },
  AxiosError: class AxiosError extends Error {},
}))

describe('desk API authentication and lifecycle requests', () => {
  beforeEach(() => {
    localStorage.setItem('finance-god-token', 'user-token')
    mocks.get.mockReset()
    mocks.post.mockReset()
  })

  it('attaches the existing user JWT and never emits an owner header', async () => {
    await import('@/api/desk')
    const interceptor = mocks.requestInterceptor.mock.calls[0][0]
    const config = interceptor({ headers: {} })

    expect(config.headers.Authorization).toBe('Bearer user-token')
    expect(config.headers).not.toHaveProperty('x-finance-god-owner-id')
  })

  it('sends account and draft transitions with their required idempotency/revision fields', async () => {
    mocks.post.mockResolvedValue({
      data: {
        account_id: 'account-1',
        owner_id: 'user-1',
        status: 'active',
        cash_total_rmb: '100000',
        cash_available_rmb: '100000',
        cash_frozen_rmb: '0',
        margin_rmb: '0',
        revision: 1,
      },
    })
    const api = await import('@/api/desk')

    await api.createSimulationAccount(100000, 'account-key')
    expect(mocks.post).toHaveBeenCalledWith(
      '/simulation/accounts',
      { initial_cash_rmb: 100000 },
      { headers: { 'idempotency-key': 'account-key' } },
    )

    mocks.post.mockResolvedValue({
      data: {
        record_revision: 2,
        draft: {
          quantity: '100',
          amount: null,
          limit_price: null,
        },
      },
    })
    await api.reviewOrderDraft('draft-1', 1)
    expect(mocks.post).toHaveBeenLastCalledWith(
      '/simulation/drafts/draft-1/review',
      { expected_revision: 1 },
    )
  })

  it('normalizes Pydantic Decimal JSON strings at the API boundary', async () => {
    const api = await import('@/api/desk')
    mocks.get.mockResolvedValueOnce({
      data: {
        account_id: 'account-1',
        owner_id: 'user-1',
        status: 'active',
        cash_total_rmb: '100000.00',
        cash_available_rmb: '99999.50',
        cash_frozen_rmb: '0',
        margin_rmb: '0',
        revision: 1,
      },
    })

    const account = await api.fetchCurrentAccount()

    expect(account.cash_total_rmb).toBe(100000)
    expect(account.cash_available_rmb).toBe(99999.5)
    expect(typeof account.cash_available_rmb).toBe('number')
  })
})
