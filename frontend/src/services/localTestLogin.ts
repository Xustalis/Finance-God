export function shouldAutoLoginLocalTestUser(hostname: string, redirect: unknown): boolean {
  const isLocalHost = hostname === '127.0.0.1' || hostname === 'localhost'
  return isLocalHost && typeof redirect === 'string' && (
    redirect === '/desk' || redirect.startsWith('/desk?')
  )
}
