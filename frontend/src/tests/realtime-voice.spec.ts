import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { useRealtimeVoice } from '@/composables/useRealtimeVoice'

class MockWebSocket extends EventTarget {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  static instances: MockWebSocket[] = []

  readonly url: string
  readyState = MockWebSocket.CONNECTING
  sent: string[] = []
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null

  constructor(url: string) {
    super()
    this.url = url
    MockWebSocket.instances.push(this)
  }

  open() {
    this.readyState = MockWebSocket.OPEN
    this.dispatchEvent(new Event('open'))
  }

  fail() {
    this.dispatchEvent(new Event('error'))
    this.onerror?.()
  }

  closeBeforeOpen() {
    this.readyState = MockWebSocket.CLOSED
    this.dispatchEvent(new Event('close'))
  }

  message(payload: object) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(payload) }))
  }

  send(value: string) {
    this.sent.push(value)
  }

  close() {
    if (this.readyState === MockWebSocket.CLOSED) return
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }
}

class MockAudioContext {
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) }
  destination = {}
  currentTime = 0

  createMediaStreamSource() {
    return { connect: vi.fn(), disconnect: vi.fn() }
  }

  close = vi.fn().mockResolvedValue(undefined)
}

class MockAudioWorkletNode {
  port = { onmessage: null }
  disconnect = vi.fn()
}

const trackStop = vi.fn()
const mediaStream = { getTracks: () => [{ stop: trackStop }] }
const getUserMedia = vi.fn()
const wrappers: VueWrapper[] = []

function createVoice() {
  let voice!: ReturnType<typeof useRealtimeVoice>
  const wrapper = mount(defineComponent({
    setup() {
      voice = useRealtimeVoice()
      return () => null
    },
  }))
  wrappers.push(wrapper)
  return voice
}

async function pendingSocket(): Promise<MockWebSocket> {
  await vi.waitFor(() => expect(MockWebSocket.instances).toHaveLength(1))
  return MockWebSocket.instances[0]
}

async function openSession() {
  const voice = createVoice()
  const started = voice.start({ surface: 'desk', contextVersion: 'desk:user-1:information' })
  const socket = await pendingSocket()
  socket.open()
  await vi.waitFor(() => expect(socket.sent).toHaveLength(1))
  socket.message({ type: 'session.ready' })
  await started
  return { voice, socket }
}

describe('useRealtimeVoice connection lifecycle', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    getUserMedia.mockReset().mockResolvedValue(mediaStream)
    trackStop.mockReset()
    localStorage.setItem('finance-god-token', 'test-token')
    vi.stubGlobal('WebSocket', MockWebSocket)
    vi.stubGlobal('AudioContext', MockAudioContext)
    vi.stubGlobal('AudioWorkletNode', MockAudioWorkletNode)
    vi.stubGlobal('isSecureContext', true)
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    })
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:worklet')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  })

  afterEach(() => {
    wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('opens the same-origin websocket and sends the existing auth contract', async () => {
    const { voice, socket } = await openSession()

    expect(socket.url).toBe(
      `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/v1/voice/realtime`,
    )
    expect(JSON.parse(socket.sent[0])).toEqual({
      type: 'auth',
      token: 'test-token',
      surface: 'desk',
      context_version: 'desk:user-1:information',
    })
    expect(voice.active.value).toBe(true)

    expect(voice.phase.value).toBe('listening')
  })

  it('fails immediately when the websocket proxy reports an error', async () => {
    const voice = createVoice()
    const started = voice.start({ surface: 'onboarding', sessionId: 'session-1' })
    const socket = await pendingSocket()

    socket.fail()
    await started

    expect(voice.error.value).toBe('实时语音连接失败，请使用文字输入。')
    expect(voice.phase.value).toBe('error')
    expect(voice.canStart.value).toBe(true)
    expect(trackStop).toHaveBeenCalledOnce()
  })

  it('fails immediately when the websocket closes before opening', async () => {
    const voice = createVoice()
    const started = voice.start({ surface: 'onboarding', sessionId: 'session-1' })
    const socket = await pendingSocket()

    socket.closeBeforeOpen()
    await started

    expect(voice.error.value).toBe('实时语音连接失败，请使用文字输入。')
    expect(voice.phase.value).toBe('error')
  })

  it('times out after ten seconds and releases the microphone', async () => {
    vi.useFakeTimers()
    const voice = createVoice()
    const started = voice.start({ surface: 'onboarding', sessionId: 'session-1' })
    await pendingSocket()

    await vi.advanceTimersByTimeAsync(10000)
    await started

    expect(voice.error.value).toBe('实时语音连接超时，请使用文字输入。')
    expect(voice.phase.value).toBe('error')
    expect(trackStop).toHaveBeenCalledOnce()
  })

  it.each([
    ['authentication_failed', '语音会话认证失败。'],
    ['upstream_unavailable', '实时语音服务连接中断，请改用文字输入。'],
  ])('preserves the server error for %s', async (code, message) => {
    const { voice, socket } = await openSession()

    socket.message({ type: 'session.error', code, message })
    await vi.waitFor(() => expect(voice.phase.value).toBe('error'))

    expect(voice.error.value).toBe(`${message}（${code}）`)
    expect(voice.active.value).toBe(false)
  })

  it('reports a denied microphone without creating a websocket', async () => {
    getUserMedia.mockRejectedValueOnce(new DOMException('denied', 'NotAllowedError'))
    const voice = createVoice()

    await voice.start({ surface: 'onboarding', sessionId: 'session-1' })

    expect(voice.error.value).toBe('麦克风权限被拒绝，请允许访问后重试。')
    expect(voice.phase.value).toBe('error')
    expect(MockWebSocket.instances).toHaveLength(0)
  })

  it('can retry after a failed connection', async () => {
    const voice = createVoice()
    const failedStart = voice.start({ surface: 'onboarding', sessionId: 'session-1' })
    const firstSocket = await pendingSocket()
    firstSocket.fail()
    await failedStart

    const retried = voice.start({ surface: 'onboarding', sessionId: 'session-1' })
    await vi.waitFor(() => expect(MockWebSocket.instances).toHaveLength(2))
    MockWebSocket.instances[1].open()
    await vi.waitFor(() => expect(MockWebSocket.instances[1].sent).toHaveLength(1))
    MockWebSocket.instances[1].message({ type: 'session.ready' })
    await retried

    expect(voice.active.value).toBe(true)
    expect(voice.error.value).toBe('')
  })
})
