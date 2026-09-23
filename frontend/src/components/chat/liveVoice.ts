import type { PersonaLiveSession } from "@/api/personas"
import {
  elevenLabsInitiationMessage,
  elevenLabsPongMessage,
  elevenLabsToolResultMessage,
  elevenLabsUserAudioMessage,
  parseElevenLabsMessage,
  updateElevenLabsTranscripts,
} from "@/components/chat/elevenlabsLiveProtocol"
import {
  liveAudioMessage,
  liveClientContentMessage,
  liveSetupMessage,
  liveToolResponseMessage,
  parseGeminiLiveMessage,
  updateGeminiLiveTranscripts,
} from "@/components/chat/geminiLiveProtocol"
import {
  createRingbackSamples,
  decodeLiveVoiceFrame,
  decodePcm16Base64,
  encodePcm16Base64,
  pcmSampleRate,
} from "@/components/chat/liveVoiceAudio"

export type LiveVoiceState =
  | "idle"
  | "connecting"
  | "ringing"
  | "active"
  | "error"
export type LiveVoiceError =
  | "microphoneDenied"
  | "microphoneUnavailable"
  | "connectionFailed"
  | "sessionFailed"

export type LiveVoiceToolCall = {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export type LiveVoiceSession = {
  start(): Promise<void>
  stop(): Promise<void>
  setMicrophoneMuted(muted: boolean): void
  setSpeakerMuted(muted: boolean): void
}

type LiveVoiceSessionOptions = {
  getSession: () => Promise<PersonaLiveSession>
  onStateChange: (state: LiveVoiceState) => void
  onError: (error: LiveVoiceError) => void
  onTurnComplete: (userMessage: string, assistantMessage: string) => void
  onToolCall: (
    call: LiveVoiceToolCall,
    userMessage: string,
    history: Array<{ role: "user" | "assistant"; content: string }>,
  ) => Promise<string>
  onToolError: (name: string) => void
}

type LiveVoiceAdapterEvent = {
  sessionReady: boolean
  interrupted: boolean
  audioChunks: string[]
  inputFormat: string | null
  outputFormat: string | null
  ping: { eventId: number; pingMs: number | null } | null
  toolCalls: LiveVoiceToolCall[]
  userTranscript: string
  assistantTranscript: string
  turnComplete: boolean
}

type TranscriptState = { input: string; output: string }

type LiveVoiceAdapter = {
  ringOnOpen: boolean
  ringbackOnReady: boolean
  openMessages: (session: PersonaLiveSession) => string[]
  afterReadyMessages: (session: PersonaLiveSession) => string[]
  parse: (raw: string) => LiveVoiceAdapterEvent
  audioMessage: (pcmBase64: string) => string
  toolResultMessages: (
    responses: Array<{ id: string; name: string; result: string; isError?: boolean }>,
  ) => string[]
  closeMessage: () => string | null
  pongMessage: (eventId: number) => string | null
  applyTranscript: (
    state: TranscriptState,
    event: LiveVoiceAdapterEvent,
  ) => { state: TranscriptState; completed: TranscriptState | null }
}

const geminiLiveAdapter: LiveVoiceAdapter = {
  ringOnOpen: false,
  ringbackOnReady: true,
  openMessages: (session) => [liveSetupMessage(session.model, session.voice)],
  afterReadyMessages: (session) => [liveClientContentMessage(session.initial_turn)],
  parse: (raw) => {
    const event = parseGeminiLiveMessage(raw)
    return {
      sessionReady: event.setupComplete,
      interrupted: event.interrupted,
      audioChunks: event.audioChunks,
      inputFormat: null,
      outputFormat: null,
      ping: null,
      toolCalls: event.toolCalls,
      userTranscript: event.inputTranscript,
      assistantTranscript: event.outputTranscript,
      turnComplete: event.turnComplete,
    }
  },
  audioMessage: liveAudioMessage,
  toolResultMessages: (responses) => [liveToolResponseMessage(responses)],
  closeMessage: () => JSON.stringify({ realtimeInput: { audioStreamEnd: true } }),
  pongMessage: () => null,
  applyTranscript: (state, event) =>
    updateGeminiLiveTranscripts(state, {
      setupComplete: event.sessionReady,
      interrupted: event.interrupted,
      audioChunks: event.audioChunks,
      inputTranscript: event.userTranscript,
      outputTranscript: event.assistantTranscript,
      turnComplete: event.turnComplete,
      toolCalls: event.toolCalls,
    }),
}

const elevenlabsLiveAdapter: LiveVoiceAdapter = {
  ringOnOpen: true,
  ringbackOnReady: false,
  openMessages: (session) => {
    if (!session.client_init) {
      throw new Error("ElevenLabs live session is missing client_init")
    }
    return [elevenLabsInitiationMessage(session.client_init)]
  },
  afterReadyMessages: () => [],
  parse: (raw) => {
    const event = parseElevenLabsMessage(raw)
    return {
      sessionReady: event.sessionReady,
      interrupted: event.interrupted,
      audioChunks: event.audioChunks,
      inputFormat: event.inputFormat,
      outputFormat: event.outputFormat,
      ping: event.ping,
      toolCalls: event.toolCalls,
      userTranscript: event.userTranscript,
      assistantTranscript: event.assistantTranscript,
      turnComplete: false,
    }
  },
  audioMessage: elevenLabsUserAudioMessage,
  toolResultMessages: elevenLabsToolResultMessage,
  closeMessage: () => null,
  pongMessage: elevenLabsPongMessage,
  applyTranscript: updateElevenLabsTranscripts,
}

function adapterFor(provider: PersonaLiveSession["provider"]): LiveVoiceAdapter {
  switch (provider) {
    case "gemini":
      return geminiLiveAdapter
    case "elevenlabs":
      return elevenlabsLiveAdapter
    default: {
      const exhaustive: never = provider
      throw new Error(`Unsupported live voice provider: ${String(exhaustive)}`)
    }
  }
}

class LiveVoiceSessionImpl implements LiveVoiceSession {
  private readonly options: LiveVoiceSessionOptions
  private websocket: WebSocket | null = null
  private microphone: MediaStream | null = null
  private captureContext: AudioContext | null = null
  private playbackContext: AudioContext | null = null
  private captureSource: MediaStreamAudioSourceNode | null = null
  private captureNode: AudioWorkletNode | null = null
  private muteGain: GainNode | null = null
  private outputGain: GainNode | null = null
  private playbackSources = new Set<AudioBufferSourceNode>()
  private nextPlaybackTime = 0
  private setupTimer: number | null = null
  private pingTimers = new Set<number>()
  private inputTranscript = ""
  private outputTranscript = ""
  private conversationHistory: Array<{
    role: "user" | "assistant"
    content: string
  }> = []
  private state: LiveVoiceState = "idle"
  private generation = 0
  private stopping = false
  private adapter: LiveVoiceAdapter | null = null
  private inputSampleRate = 16_000
  private outputSampleRate = 24_000

  constructor(options: LiveVoiceSessionOptions) {
    this.options = options
  }

  async start(): Promise<void> {
    if (this.state === "connecting" || this.state === "active") return
    const generation = ++this.generation
    this.stopping = false
    this.setState("connecting")

    try {
      this.captureContext = new AudioContext()
      await this.captureContext.resume()

      const microphone = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      })
      if (generation !== this.generation) {
        for (const track of microphone.getTracks()) track.stop()
        return
      }
      this.microphone = microphone
      const session = await this.options.getSession()
      if (generation !== this.generation) return
      if (session.provider !== "gemini" && session.provider !== "elevenlabs") {
        await this.fail("sessionFailed")
        return
      }
      const inputRate = pcmSampleRate(session.audio.input_format)
      const outputRate = pcmSampleRate(session.audio.output_format)
      if (inputRate === null || outputRate === null) {
        await this.fail("sessionFailed")
        return
      }
      this.inputSampleRate = inputRate
      this.outputSampleRate = outputRate
      this.adapter = adapterFor(session.provider)
      this.playbackContext = new AudioContext({ sampleRate: outputRate })
      await this.playbackContext.resume()
      this.outputGain = this.playbackContext.createGain()
      this.outputGain.connect(this.playbackContext.destination)
      await this.prepareCapture()
      if (generation !== this.generation) return
      this.connect(session, this.adapter)
    } catch (error) {
      if (generation !== this.generation) return
      const denied =
        error instanceof DOMException &&
        (error.name === "NotAllowedError" || error.name === "SecurityError")
      const unavailable =
        error instanceof DOMException &&
        (error.name === "NotFoundError" || error.name === "NotReadableError")
      await this.fail(
        denied
          ? "microphoneDenied"
          : unavailable
            ? "microphoneUnavailable"
            : "sessionFailed",
      )
    }
  }

  async stop(): Promise<void> {
    if (this.state === "idle") return
    this.stopping = true
    this.generation += 1
    this.flushTranscriptPair()
    const closeMessage = this.adapter?.closeMessage()
    if (closeMessage && this.websocket?.readyState === WebSocket.OPEN) {
      this.websocket.send(closeMessage)
    }
    await this.cleanup()
    this.setState("idle")
    this.stopping = false
  }

  setMicrophoneMuted(muted: boolean): void {
    for (const track of this.microphone?.getAudioTracks() ?? []) {
      track.enabled = !muted
    }
  }

  setSpeakerMuted(muted: boolean): void {
    if (this.outputGain) this.outputGain.gain.value = muted ? 0 : 1
  }

  private async prepareCapture(): Promise<void> {
    const context = this.captureContext
    const microphone = this.microphone
    if (!context || !microphone) throw new Error("Audio capture is not initialized")

    await context.audioWorklet.addModule(
      new URL("./pcmCapture.worklet.ts", import.meta.url),
    )
    this.captureSource = context.createMediaStreamSource(microphone)
    this.captureNode = new AudioWorkletNode(context, "pcm-capture")
    this.muteGain = context.createGain()
    this.muteGain.gain.value = 0
    this.captureNode.connect(this.muteGain)
    this.muteGain.connect(context.destination)
    this.captureNode.port.onmessage = (event: MessageEvent<unknown>) => {
      if (
        !(event.data instanceof Float32Array) ||
        this.websocket?.readyState !== WebSocket.OPEN ||
        this.state !== "active"
      ) {
        return
      }
      const encoded = encodePcm16Base64(
        event.data,
        context.sampleRate,
        this.inputSampleRate,
      )
      const payload = this.adapter?.audioMessage(encoded)
      if (payload) this.websocket.send(payload)
    }
  }

  private connect(session: PersonaLiveSession, adapter: LiveVoiceAdapter): void {
    const websocket = new WebSocket(session.websocket_url)
    websocket.binaryType = "arraybuffer"
    this.websocket = websocket

    websocket.onopen = () => {
      try {
        for (const message of adapter.openMessages(session)) {
          websocket.send(message)
        }
      } catch {
        void this.fail("sessionFailed")
        return
      }
      if (adapter.ringOnOpen && this.state === "connecting") {
        this.setState("ringing")
      }
      this.setupTimer = window.setTimeout(() => {
        void this.fail("connectionFailed")
      }, 10_000)
    }
    websocket.onmessage = async (event: MessageEvent<unknown>) => {
      const raw = await decodeLiveVoiceFrame(event.data)
      if (raw === null) return
      try {
        const message = adapter.parse(raw)
        if (message.inputFormat) {
          const rate = pcmSampleRate(message.inputFormat)
          if (rate !== null) this.inputSampleRate = rate
        }
        if (message.outputFormat) {
          const rate = pcmSampleRate(message.outputFormat)
          if (rate !== null) this.outputSampleRate = rate
        }
        if (message.ping) {
          const pong = adapter.pongMessage(message.ping.eventId)
          if (pong) {
            const delay = message.ping.pingMs ?? 0
            const sendPong = () => {
              if (
                this.websocket === websocket &&
                websocket.readyState === WebSocket.OPEN
              ) {
                websocket.send(pong)
              }
            }
            if (delay > 0) {
              const timer = window.setTimeout(() => {
                this.pingTimers.delete(timer)
                sendPong()
              }, delay)
              this.pingTimers.add(timer)
            } else {
              sendPong()
            }
          }
        }
        if (message.sessionReady && (this.state === "connecting" || this.state === "ringing")) {
          this.clearSetupTimer()
          if (adapter.ringbackOnReady) {
            this.setState("ringing")
            await this.playRingback()
            if (
              this.websocket !== websocket ||
              websocket.readyState !== WebSocket.OPEN ||
              !this.isRinging()
            ) {
              return
            }
          }
          this.setState("active")
          for (const readyMessage of adapter.afterReadyMessages(session)) {
            websocket.send(readyMessage)
          }
          this.captureSource?.connect(this.captureNode!)
        }
        if (message.interrupted) {
          this.clearPlayback()
        }
        const transcriptUpdate = adapter.applyTranscript(
          {
            input: this.inputTranscript,
            output: this.outputTranscript,
          },
          message,
        )
        this.inputTranscript = transcriptUpdate.state.input
        this.outputTranscript = transcriptUpdate.state.output
        for (const chunk of message.audioChunks) this.enqueuePlayback(chunk)
        if (message.toolCalls.length > 0) {
          const responses = await Promise.all(
            message.toolCalls.map(async (call) => {
              try {
                const result = await this.options.onToolCall(
                  call,
                  this.inputTranscript.trim(),
                  [...this.conversationHistory],
                )
                return { id: call.id, name: call.name, result }
              } catch {
                this.options.onToolError(call.name)
                return {
                  id: call.id,
                  name: call.name,
                  result: JSON.stringify({ error: "tool_execution_failed" }),
                  isError: true,
                }
              }
            }),
          )
          if (
            this.websocket === websocket &&
            websocket.readyState === WebSocket.OPEN
          ) {
            for (const payload of adapter.toolResultMessages(responses)) {
              websocket.send(payload)
            }
          }
        }
        if (transcriptUpdate.completed) {
          this.saveTranscriptPair(
            transcriptUpdate.completed.input,
            transcriptUpdate.completed.output,
          )
        }
      } catch {
        void this.fail("sessionFailed")
      }
    }
    websocket.onerror = () => {
      void this.fail("connectionFailed")
    }
    websocket.onclose = () => {
      if (!this.stopping && this.state !== "idle" && this.state !== "error") {
        void this.fail("connectionFailed")
      }
    }
  }

  private enqueuePlayback(encoded: string): void {
    const context = this.playbackContext
    if (!context) return
    const samples = decodePcm16Base64(encoded)
    if (samples.length === 0) return
    const buffer = context.createBuffer(
      1,
      samples.length,
      this.outputSampleRate,
    )
    buffer.getChannelData(0).set(samples)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(this.outputGain ?? context.destination)
    source.onended = () => this.playbackSources.delete(source)
    this.playbackSources.add(source)
    const startAt = Math.max(context.currentTime + 0.02, this.nextPlaybackTime)
    source.start(startAt)
    this.nextPlaybackTime = startAt + buffer.duration
  }

  private async playRingback(): Promise<void> {
    const context = this.playbackContext
    if (!context) return
    const samples = createRingbackSamples(context.sampleRate)

    const buffer = context.createBuffer(1, samples.length, context.sampleRate)
    buffer.getChannelData(0).set(samples)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(this.outputGain ?? context.destination)
    this.playbackSources.add(source)
    await new Promise<void>((resolve) => {
      source.onended = () => {
        this.playbackSources.delete(source)
        resolve()
      }
      source.start()
    })
    this.nextPlaybackTime = context.currentTime
  }

  private clearPlayback(): void {
    for (const source of this.playbackSources) {
      try {
        source.stop()
      } catch {
        // The source may already have ended between receiving and handling interruption.
      }
    }
    this.playbackSources.clear()
    this.nextPlaybackTime = this.playbackContext?.currentTime ?? 0
  }

  private async fail(error: LiveVoiceError): Promise<void> {
    if (this.state === "error" || this.stopping) return
    this.stopping = true
    this.generation += 1
    await this.cleanup()
    this.setState("error")
    this.options.onError(error)
    this.stopping = false
  }

  private async cleanup(): Promise<void> {
    this.clearSetupTimer()
    for (const timer of this.pingTimers) window.clearTimeout(timer)
    this.pingTimers.clear()
    this.captureSource?.disconnect()
    this.captureNode?.disconnect()
    this.muteGain?.disconnect()
    this.captureNode = null
    this.captureSource = null
    this.muteGain = null
    this.outputGain?.disconnect()
    this.outputGain = null
    this.clearPlayback()
    for (const track of this.microphone?.getTracks() ?? []) track.stop()
    this.microphone = null
    this.adapter = null

    const websocket = this.websocket
    this.websocket = null
    if (
      websocket &&
      (websocket.readyState === WebSocket.OPEN ||
        websocket.readyState === WebSocket.CONNECTING)
    ) {
      websocket.close()
    }
    const captureContext = this.captureContext
    const playbackContext = this.playbackContext
    this.captureContext = null
    this.playbackContext = null
    await Promise.all([
      captureContext && captureContext.state !== "closed"
        ? captureContext.close()
        : Promise.resolve(),
      playbackContext && playbackContext.state !== "closed"
        ? playbackContext.close()
        : Promise.resolve(),
    ])
    this.nextPlaybackTime = 0
    this.inputTranscript = ""
    this.outputTranscript = ""
    this.conversationHistory = []
  }

  private setState(state: LiveVoiceState): void {
    this.state = state
    this.options.onStateChange(state)
  }

  private flushTranscriptPair(): void {
    const userMessage = this.inputTranscript.trim()
    const assistantMessage = this.outputTranscript.trim()
    this.inputTranscript = ""
    this.outputTranscript = ""
    if (!userMessage || !assistantMessage) return
    this.saveTranscriptPair(userMessage, assistantMessage)
  }

  private saveTranscriptPair(
    userMessage: string,
    assistantMessage: string,
  ): void {
    this.conversationHistory.push(
      { role: "user", content: userMessage },
      { role: "assistant", content: assistantMessage },
    )
    this.conversationHistory = this.conversationHistory.slice(-50)
    this.options.onTurnComplete(userMessage, assistantMessage)
  }

  private isRinging(): boolean {
    return this.state === "ringing"
  }

  private clearSetupTimer(): void {
    if (this.setupTimer !== null) {
      window.clearTimeout(this.setupTimer)
      this.setupTimer = null
    }
  }
}

export function createLiveVoiceSession(
  options: LiveVoiceSessionOptions,
): LiveVoiceSession {
  return new LiveVoiceSessionImpl(options)
}
