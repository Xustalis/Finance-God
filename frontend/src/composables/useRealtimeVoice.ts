import { computed, onBeforeUnmount, ref } from 'vue'
import { v1ApiBase } from '@/services/apiBase'

export type VoiceSurface = 'onboarding' | 'desk'
export type VoicePhase = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking' | 'error'

interface StartOptions {
  surface: VoiceSurface
  sessionId?: string
  contextVersion?: string
  onFinalTranscript?: (role: 'user' | 'assistant', text: string) => void
}

interface RealtimeEvent {
  type: string
  data?: string
  code?: string
  message?: string
}

const SAMPLE_RATE = 24000
const CONNECTION_TIMEOUT_MS = 10000
const CONNECTION_FAILED_MESSAGE = '实时语音连接失败，请使用文字输入。'
const WORKLET_SOURCE = `
class FinanceGodPcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.frame = new Float32Array(480)
    this.offset = 0
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (channel && channel.length) {
      for (let index = 0; index < channel.length; index += 1) {
        this.frame[this.offset] = channel[index]
        this.offset += 1
        if (this.offset === this.frame.length) {
          this.port.postMessage(this.frame)
          this.frame = new Float32Array(480)
          this.offset = 0
        }
      }
    }
    return true
  }
}
registerProcessor('finance-god-pcm', FinanceGodPcmProcessor)
`

function websocketUrl(): string {
  const configured = v1ApiBase()
  const base = configured.startsWith('http')
    ? configured.replace(/^http/, 'ws')
    : `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${configured}`
  return `${base.replace(/\/$/, '')}/voice/realtime`
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunk = 0x8000
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk))
  }
  return btoa(binary)
}

function floatsToPcm16(input: Float32Array): string {
  const buffer = new ArrayBuffer(input.length * 2)
  const view = new DataView(buffer)
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index]))
    view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
  }
  return bytesToBase64(new Uint8Array(buffer))
}

function base64ToPcm16(value: string): Float32Array {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  const view = new DataView(bytes.buffer)
  const output = new Float32Array(bytes.byteLength / 2)
  for (let index = 0; index < output.length; index += 1) output[index] = view.getInt16(index * 2, true) / 0x8000
  return output
}

function waitForOpen(socket: WebSocket): Promise<void> {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      window.clearTimeout(timer)
      socket.removeEventListener('open', handleOpen)
      socket.removeEventListener('error', handleError)
      socket.removeEventListener('close', handleClose)
    }
    const settle = (callback: () => void) => {
      cleanup()
      callback()
    }
    const handleOpen = () => settle(resolve)
    const handleError = () => settle(() => reject(new Error(CONNECTION_FAILED_MESSAGE)))
    const handleClose = () => settle(() => reject(new Error(CONNECTION_FAILED_MESSAGE)))
    const timer = window.setTimeout(
      () => settle(() => reject(new Error('实时语音连接超时，请使用文字输入。'))),
      CONNECTION_TIMEOUT_MS,
    )

    socket.addEventListener('open', handleOpen)
    socket.addEventListener('error', handleError)
    socket.addEventListener('close', handleClose)
  })
}

function serverError(payload: RealtimeEvent): string {
  const message = payload.message || '实时语音连接已结束，请使用文字输入。'
  return payload.code ? `${message}（${payload.code}）` : message
}

export function useRealtimeVoice() {
  const active = ref(false)
  const muted = ref(false)
  const phase = ref<VoicePhase>('idle')
  const statusText = ref('文字模式')
  const userTranscript = ref('')
  const assistantTranscript = ref('')
  const error = ref('')

  let socket: WebSocket | null = null
  let stream: MediaStream | null = null
  let inputContext: AudioContext | null = null
  let outputContext: AudioContext | null = null
  let inputNode: AudioWorkletNode | null = null
  let sourceNode: MediaStreamAudioSourceNode | null = null
  let nextPlaybackAt = 0
  let finalCallback: StartOptions['onFinalTranscript']
  let workletUrl: string | null = null
  let stopping = false

  const canStart = computed(() => phase.value === 'idle' || phase.value === 'error')

  function stopPlayback() {
    if (outputContext) void outputContext.close()
    outputContext = null
    nextPlaybackAt = 0
  }

  async function playPcm(encoded: string) {
    if (!encoded) return
    outputContext ??= new AudioContext({ sampleRate: SAMPLE_RATE })
    const samples = base64ToPcm16(encoded)
    const buffer = outputContext.createBuffer(1, samples.length, SAMPLE_RATE)
    buffer.copyToChannel(new Float32Array(samples), 0)
    const source = outputContext.createBufferSource()
    source.buffer = buffer
    source.connect(outputContext.destination)
    const now = outputContext.currentTime
    const startAt = Math.max(now, nextPlaybackAt)
    source.start(startAt)
    nextPlaybackAt = startAt + buffer.duration
  }

  function completeTranscript(role: 'user' | 'assistant', value?: string) {
    const transcript = (value || (role === 'user' ? userTranscript.value : assistantTranscript.value)).trim()
    if (transcript) finalCallback?.(role, transcript)
  }

  function handleEvent(event: MessageEvent<string>) {
    const payload = JSON.parse(event.data) as RealtimeEvent
    if (payload.type === 'session.ready') {
      phase.value = 'listening'
      statusText.value = '正在聆听'
    } else if (payload.type === 'speech.started') {
      socket?.send(JSON.stringify({ type: 'response.cancel' }))
      stopPlayback()
      userTranscript.value = ''
      phase.value = 'listening'
      statusText.value = '正在聆听'
    } else if (payload.type === 'speech.stopped') {
      phase.value = 'thinking'
      statusText.value = '正在理解'
    } else if (payload.type === 'transcript.user.delta') {
      userTranscript.value += payload.data || ''
    } else if (payload.type === 'transcript.user.done') {
      if (payload.data) userTranscript.value = payload.data
      completeTranscript('user', payload.data)
    } else if (payload.type === 'transcript.assistant.delta') {
      assistantTranscript.value += payload.data || ''
      phase.value = 'speaking'
      statusText.value = 'AI 正在回答'
    } else if (payload.type === 'transcript.assistant.done') {
      if (payload.data) assistantTranscript.value = payload.data
      completeTranscript('assistant', payload.data)
    } else if (payload.type === 'audio.delta') {
      phase.value = 'speaking'
      statusText.value = 'AI 正在回答'
      void playPcm(payload.data || '')
    } else if (payload.type === 'audio.done') {
      assistantTranscript.value = ''
      phase.value = 'listening'
      statusText.value = '正在聆听'
    } else if (payload.type === 'session.warning') {
      statusText.value = payload.message || '通话即将结束'
    } else if (payload.type === 'session.error' || payload.type === 'session.closed') {
      error.value = serverError(payload)
      void stop('error')
    }
  }

  async function setupMicrophone() {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    inputContext = new AudioContext({ sampleRate: SAMPLE_RATE })
    workletUrl = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'text/javascript' }))
    await inputContext.audioWorklet.addModule(workletUrl)
    sourceNode = inputContext.createMediaStreamSource(stream)
    inputNode = new AudioWorkletNode(inputContext, 'finance-god-pcm')
    inputNode.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (!muted.value && socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'audio.append', audio: floatsToPcm16(event.data) }))
      }
    }
    sourceNode.connect(inputNode)
  }

  async function start(options: StartOptions) {
    if (!canStart.value) return
    error.value = ''
    phase.value = 'connecting'
    statusText.value = '正在连接实时语音'
    finalCallback = options.onFinalTranscript
    try {
      await setupMicrophone()
      socket = new WebSocket(websocketUrl())
      socket.onmessage = handleEvent
      await waitForOpen(socket)
      const token = localStorage.getItem('finance-god-token')
      if (!token) throw new Error('登录状态已失效')
      socket.send(JSON.stringify({
        type: 'auth',
        token,
        surface: options.surface,
        session_id: options.sessionId,
        context_version: options.contextVersion,
      }))
      active.value = true
      socket.onerror = () => {
        if (!error.value) error.value = CONNECTION_FAILED_MESSAGE
      }
      socket.onclose = () => {
        if (stopping) return
        if (!error.value) error.value = '实时语音连接已中断，请使用文字输入。'
        void stop('error')
      }
    } catch (cause) {
      if (!error.value) {
        error.value = cause instanceof DOMException && cause.name === 'NotAllowedError'
          ? '麦克风权限被拒绝，请允许访问后重试。'
          : cause instanceof Error ? cause.message : '无法启动实时语音。'
      }
      await stop('error')
    }
  }

  async function stop(nextPhase: 'idle' | 'error' = 'idle') {
    if (stopping) return
    stopping = true
    if (socket?.readyState === 1) socket.send(JSON.stringify({ type: 'session.close' }))
    socket?.close()
    socket = null
    inputNode?.disconnect()
    sourceNode?.disconnect()
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
    inputNode = null
    sourceNode = null
    if (inputContext) await inputContext.close()
    inputContext = null
    stopPlayback()
    if (workletUrl) URL.revokeObjectURL(workletUrl)
    workletUrl = null
    active.value = false
    muted.value = false
    phase.value = nextPhase
    statusText.value = nextPhase === 'error' ? '语音不可用' : '文字模式'
    stopping = false
  }

  function toggleMute() {
    muted.value = !muted.value
    statusText.value = muted.value ? '麦克风已静音' : '正在聆听'
  }

  onBeforeUnmount(() => { void stop() })

  return {
    active, muted, phase, statusText, userTranscript, assistantTranscript, error, canStart,
    start, stop, toggleMute,
  }
}
