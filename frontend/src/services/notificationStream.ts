import { financeApiBase } from '@/services/apiBase'
import { expireBrowserSession, USER_SESSION } from '@/services/authSession'

export interface NotificationCreatedEvent {
  event_id: string
  cursor: string
  event_type: 'notification.created'
  occurred_at: string
  notification_id: string
  fact_version: string
  payload: {
    notification_id: string
    severity: string
    required: boolean
    title: string
    message: string
    status: string
    created_at: string
    details: Record<string, string>
  }
}

export class NotificationStreamError extends Error {
  constructor(message: string, public status?: number, public code?: string) {
    super(message)
  }
}

export async function consumeNotificationStream(input: {
  cursor: string | null
  signal: AbortSignal
  onEvent: (event: NotificationCreatedEvent) => void
}): Promise<void> {
  const base = financeApiBase()
  const url = new URL(`${base.replace(/\/$/, '')}/events`, location.origin)
  if (input.cursor) url.searchParams.set('cursor', input.cursor)
  const token = localStorage.getItem('finance-god-token')
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal: input.signal,
  })
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null) as {
      error?: { code?: string; message?: string }
    } | null
    if (response.status === 401) expireBrowserSession(USER_SESSION)
    throw new NotificationStreamError(
      body?.error?.message || `实时提醒连接失败（${response.status}）`,
      response.status,
      body?.error?.code,
    )
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (!input.signal.aborted) {
    const { done, value } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const data = block
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n')
      if (data) input.onEvent(JSON.parse(data) as NotificationCreatedEvent)
      boundary = buffer.indexOf('\n\n')
    }
  }
}
