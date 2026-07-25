import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  consumeNotificationStream,
  NotificationStreamError,
} from '@/services/notificationStream'

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('notification SSE stream', () => {
  it('parses chunked owner event frames and forwards the durable cursor', async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(': connected\n\nevent: notification.created\n'))
        controller.enqueue(encoder.encode('id: 7\ndata: {"event_id":"e-1","cursor":"7","event_type":"notification.created",'))
        controller.enqueue(encoder.encode('"occurred_at":"2026-07-25T03:00:00Z","notification_id":"n-1","fact_version":"v1","payload":{"notification_id":"n-1","severity":"warning","required":false,"title":"提醒","message":"异动","status":"unread","created_at":"2026-07-25T03:00:00Z","details":{"symbol":"300750.SZ"}}}\n\n'))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, { status: 200 })))
    const onEvent = vi.fn()

    await consumeNotificationStream({
      cursor: '6',
      signal: new AbortController().signal,
      onEvent,
    })

    expect(onEvent).toHaveBeenCalledOnce()
    expect(onEvent.mock.calls[0][0]).toMatchObject({
      cursor: '7',
      notification_id: 'n-1',
      payload: { details: { symbol: '300750.SZ' } },
    })
    expect(vi.mocked(fetch).mock.calls[0][0].toString()).toContain('cursor=6')
    expect(vi.mocked(fetch).mock.calls[0][0].toString()).toContain('/api/events?')
    expect(vi.mocked(fetch).mock.calls[0][0].toString()).not.toContain('/api/v1/events')
  })

  it('surfaces an expired cursor instead of silently polling', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'EVENT_CURSOR_EXPIRED', message: '事件游标已过期' },
    }), { status: 409, headers: { 'Content-Type': 'application/json' } })))

    await expect(consumeNotificationStream({
      cursor: '1',
      signal: new AbortController().signal,
      onEvent: vi.fn(),
    })).rejects.toMatchObject({
      code: 'EVENT_CURSOR_EXPIRED',
      status: 409,
    } satisfies Partial<NotificationStreamError>)
  })

  it('expires the browser session when the stream rejects its Bearer token', async () => {
    history.replaceState({}, '', '/login')
    localStorage.setItem('finance-god-token', 'expired-token')
    localStorage.setItem('finance-god-user', '{"id":"user-1"}')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'UNAUTHORIZED', message: 'valid Bearer authentication is required' },
    }), { status: 401, headers: { 'Content-Type': 'application/json' } })))

    await expect(consumeNotificationStream({
      cursor: null,
      signal: new AbortController().signal,
      onEvent: vi.fn(),
    })).rejects.toMatchObject({ code: 'UNAUTHORIZED', status: 401 })

    expect(localStorage.getItem('finance-god-token')).toBeNull()
    expect(localStorage.getItem('finance-god-user')).toBeNull()
  })
})
