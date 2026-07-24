export interface BootstrapSession { hasToken: boolean; hydrate: () => Promise<void> }
export interface BootstrapOptions {
  hasToken?: boolean
  hydrate?: () => Promise<void>
  sessions?: BootstrapSession[]
  mount: () => void
}

export async function bootstrapApplication(options: BootstrapOptions): Promise<void> {
  const sessions = options.sessions || [{ hasToken: Boolean(options.hasToken), hydrate: options.hydrate || (async () => {}) }]
  await Promise.all(sessions.filter(item => item.hasToken).map(async item => {
    try { await item.hydrate() } catch { /* Each auth store owns cleanup. */ }
  }))
  options.mount()
}
