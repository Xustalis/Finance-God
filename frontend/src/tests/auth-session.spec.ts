import { describe, expect, it, vi } from 'vitest'
import { expireBrowserSession, USER_SESSION } from '@/services/authSession'

describe('browser auth session', () => {
  it('clears an invalid user session without redirecting again on the login route', () => {
    history.replaceState({}, '', USER_SESSION.loginPath)
    localStorage.setItem(USER_SESSION.tokenKey, 'expired-token')
    localStorage.setItem(USER_SESSION.userKey, '{"id":"user-1"}')
    const assign = vi.spyOn(location, 'assign')

    expireBrowserSession(USER_SESSION)

    expect(localStorage.getItem(USER_SESSION.tokenKey)).toBeNull()
    expect(localStorage.getItem(USER_SESSION.userKey)).toBeNull()
    expect(assign).not.toHaveBeenCalled()
  })
})
