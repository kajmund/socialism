import type { PersonaLiveToken } from "@/api/personas"
import {
  createRingbackSamples,
  decodeGeminiLiveFrame,
  decodePcm16Base64,
  encodePcm16Base64,
  GEMINI_OUTPUT_SAMPLE_RATE,
  liveAudioMessage,
  liveClientContentMessage,
  liveSetupMessage,
  liveToolResponseMessage,
  parseGeminiLiveMessage,
  type GeminiLiveToolCall,
  updateGeminiLiveTranscripts,
} from "@/components/chat/geminiLiveProtocol"

export type GeminiLiveVoiceState =
  | "idle"
  | "connecting"
  | "ringing"
  | "active"
  | "error"
export type GeminiLiveVoiceError =
  | "microphoneDenied"
  | "microphoneUnavailable"
  | "connectionFailed"
  | "sessionFailed"

type VoiceSessionOptions = {
  getToken: () => Promise<PersonaLiveToken>
  onStateChange: (state: GeminiLiveVoiceState) => void
  onError: (error: GeminiLiveVoiceError) => void
  onTurnComplete: (userMessage: string, assistantMessage: string) => void
  onToolCall: (
    call: GeminiLiveToolCall,
    userMessage: string,
    history: Array<{ role: "user" | "assistant"; content: string }>,
  ) => Promise<string>
  onToolError: (name: string) => void
}

const LIVE_WEBSOCKET_URL =
  "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained"

export class GeminiLiveVoiceSession {
  private readonly options: VoiceSessionOptions
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
  private inputTranscript = ""
  private outputTranscript = ""
  private conversationHistory: Array<{
    role: "user" | "assistant"
    content: string
  }> = []
  private state: GeminiLiveVoiceState = "idle"
  private generation = 0
  private stopping = false

  constructor(options: VoiceSessionOptions) {
    this.options = options
  }

  async start(): Promise<void> {
    if (this.state === "connecting" || this.state === "active") return
    const generation = ++this.generation
    this.stopping = false
    this.setState("connecting")

    try {
      this.captureContext = new AudioContext()
      this.playbackContext = new AudioContext({ sampleRate: GEMINI_OUTPUT_SAMPLE_RATE })
      await Promise.all([
        this.captureContext.resume(),
        this.playbackContext.resume(),
      ])
      this.outputGain = this.playbackContext.createGain()
      this.outputGain.connect(this.playbackContext.destination)

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
      const token = await this.options.getToken()
      if (generation !== this.generation) return
      await this.prepareCapture()
      if (generation !== this.generation) return
      this.connect(token)
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
    if (this.websocket?.readyState === WebSocket.OPEN) {
      this.websocket.send(JSON.stringify({ realtimeInput: { audioStreamEnd: true } }))
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
      const encoded = encodePcm16Base64(event.data, context.sampleRate)
      if (encoded) this.websocket.send(liveAudioMessage(encoded))
    }
  }

  private connect(token: PersonaLiveToken): void {
    const url = `${LIVE_WEBSOCKET_URL}?access_token=${encodeURIComponent(token.token)}`
    const websocket = new WebSocket(url)
    websocket.binaryType = "arraybuffer"
    this.websocket = websocket

    websocket.onopen = () => {
      websocket.send(liveSetupMessage(token.model, token.voice))
      this.setupTimer = window.setTimeout(() => {
        void this.fail("connectionFailed")
      }, 10_000)
    }
    websocket.onmessage = async (event: MessageEvent<unknown>) => {
      const raw = await decodeGeminiLiveFrame(event.data)
      if (raw === null) return
      try {
        const message = parseGeminiLiveMessage(raw)
        if (message.setupComplete && this.state === "connecting") {
          this.clearSetupTimer()
          this.setState("ringing")
          await this.playRingback()
          if (
            this.websocket !== websocket ||
            websocket.readyState !== WebSocket.OPEN ||
            !this.isRinging()
          ) {
            return
          }
          this.setState("active")
          websocket.send(liveClientContentMessage(token.initial_turn))
          this.captureSource?.connect(this.captureNode!)
        }
        if (message.interrupted) {
          this.clearPlayback()
        }
        const transcriptUpdate = updateGeminiLiveTranscripts(
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
                }
              }
            }),
          )
          if (
            this.websocket === websocket &&
            websocket.readyState === WebSocket.OPEN
          ) {
            websocket.send(liveToolResponseMessage(responses))
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
      GEMINI_OUTPUT_SAMPLE_RATE,
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

  private async fail(error: GeminiLiveVoiceError): Promise<void> {
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

  private setState(state: GeminiLiveVoiceState): void {
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
