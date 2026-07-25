export const USER_SESSION = {
  tokenKey: 'finance-god-token',
  userKey: 'finance-god-user',
  loginPath: '/login',
} as const

export interface BrowserSession {
  tokenKey: string
  userKey: string
  loginPath: string
}

export function expireBrowserSession(session: BrowserSession): void {
  localStorage.removeItem(session.tokenKey)
  localStorage.removeItem(session.userKey)
  if (session.tokenKey === USER_SESSION.tokenKey) {
    localStorage.removeItem('finance-god-profile-completed')
  }
  if (location.pathname !== session.loginPath) location.assign(session.loginPath)
}
