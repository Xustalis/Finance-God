export interface BootstrapSession { hasToken: boolean; hydrate: () => Promise<void> }
export interface BootstrapOptions {
  hasToken?: boolean
  hydrate?: () => Promise<void>
  sessions?: BootstrapSession[]
  mount: () => void
  afterHydrate?: () => void | Promise<void>
}

export async function bootstrapApplication(options: BootstrapOptions): Promise<void> {
  const sessions = options.sessions || [{ hasToken: Boolean(options.hasToken), hydrate: options.hydrate || (async () => {}) }]
  options.mount()
  await Promise.all(sessions.filter(item => item.hasToken).map(async item => {
    try { await item.hydrate() } catch { /* Each auth store owns cleanup. */ }
  }))
  await options.afterHydrate?.()
}
