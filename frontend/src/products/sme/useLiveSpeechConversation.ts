import { useCallback, useEffect, useRef, useState } from "react"
import type { WorkspaceMessage } from "@/api/voiceWorkspaces"
import { decodePcm16, encodePcm16 } from "@/components/chat/liveVoiceAudio"
import { useLocale } from "@/i18n"
import { authAdapter } from "@/lib/auth"
import { env } from "@/lib/env"
import { EnergyVad } from "./liveSpeechVad"
import { modelTraceEntry, type ModelTraceEntry } from "./modelTrace"

export type VoiceState =
  | "disconnected"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "paused"
  | "error"

type Options = {
  workspaceId: string | null
  expertId: string | null
  onMessage: (message: WorkspaceMessage) => void
  onPreview: (text: string | null) => void
  onTool: (
    name: string,
    args: Record<string, unknown>,
    isCurrent: () => boolean,
  ) => Promise<unknown>
  onError: (message: string) => void
  onModelTrace: (entry: ModelTraceEntry) => void
}

type Callbacks = {
  state: (state: VoiceState) => void
  message: (message: WorkspaceMessage) => void
  preview: (text: string | null) => void
  tool: Options["onTool"]
  error: (code: string) => void
  trace: (entry: ModelTraceEntry) => void
}

export class LiveSpeechClient {
  private socket: WebSocket | null = null
  private capture: AudioContext | null = null
  private playback: AudioContext | null = null
  private microphone: MediaStream | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private worklet: AudioWorkletNode | null = null
  private silentGain: GainNode | null = null
  private playbackSources = new Set<AudioBufferSourceNode>()
  private nextPlayback = 0
  private sequence = 0
  private heartbeat: number | null = null
  private muted = false
  private currentTurn: string | null = null
  private assistantText = ""
  private vad = new EnergyVad(0.018, 250, 600)
  private stopped = false

  constructor(
    private readonly workspaceId: string,
    private readonly expertId: string,
    private readonly language: string,
    private readonly callbacks: Callbacks,
  ) {}

  async start(): Promise<void> {
    this.callbacks.state("connecting")
    const microphone = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
    if (this.stopped) {
      for (const track of microphone.getTracks()) track.stop()
      throw new DOMException("Live Speech start cancelled", "AbortError")
    }
    this.microphone = microphone
    this.capture = new AudioContext()
    this.playback = new AudioContext({ sampleRate: 24_000 })
    await Promise.all([this.capture.resume(), this.playback.resume()])
    if (this.stopped) throw new DOMException("Live Speech start cancelled", "AbortError")
    await this.connect()
  }

  async stop(): Promise<void> {
    if (this.stopped) return
    this.stopped = true
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.send({ type: "session.stop", reason: "user" })
    }
    this.socket?.close()
    this.socket = null
    if (this.heartbeat !== null) window.clearInterval(this.heartbeat)
    this.heartbeat = null
    this.clearPlayback()
    this.worklet?.disconnect()
    this.source?.disconnect()
    this.silentGain?.disconnect()
    for (const track of this.microphone?.getTracks() ?? []) track.stop()
    await Promise.all([
      this.capture?.state !== "closed" ? this.capture?.close() : undefined,
      this.playback?.state !== "closed" ? this.playback?.close() : undefined,
    ])
    this.callbacks.preview(null)
    this.callbacks.state("disconnected")
  }

  toggleMute(): boolean {
    this.muted = !this.muted
    if (this.muted) {
      this.vad.resetTurn()
      this.send({ type: "audio.cancel", turn_id: this.currentTurn })
    }
    this.send({ type: "session.mute", muted: this.muted })
    this.callbacks.state(this.muted ? "paused" : "listening")
    return this.muted
  }

  cancel(reason = "user"): void {
    if (!this.currentTurn) return
    this.send({ type: "turn.cancel", turn_id: this.currentTurn, reason })
    this.clearPlayback()
  }

  private async connect(): Promise<void> {
    const token = await authAdapter.getAccessToken()
    if (!token) throw new Error("authentication_required")
    const url = `${env.wsBaseUrl}/ws/live-speech?access_token=${encodeURIComponent(token)}`
    const socket = new WebSocket(url)
    socket.binaryType = "arraybuffer"
    this.socket = socket
    await new Promise<void>((resolve, reject) => {
      socket.onerror = () => reject(new Error("live_speech_connection_failed"))
      socket.onmessage = (event) => {
        if (this.stopped) return
        if (event.data instanceof ArrayBuffer) this.play(event.data)
        else this.handleControl(String(event.data))
      }
      socket.onclose = () => {
        if (!this.stopped) void this.stop()
      }
      socket.onopen = () => {
        if (this.stopped) {
          socket.close()
          reject(new DOMException("Live Speech start cancelled", "AbortError"))
          return
        }
        this.send({
          type: "session.start",
          workspace_id: this.workspaceId,
          expert_id: this.expertId,
          language: this.language,
          client_request_id: crypto.randomUUID(),
        })
        this.heartbeat = window.setInterval(
          () => this.send({ type: "client.ping", sequence: ++this.sequence }),
          30_000,
        )
        resolve()
      }
    })
  }

  private handleControl(raw: string): void {
    let event: Record<string, unknown>
    try {
      const parsed: unknown = JSON.parse(raw)
      if (!parsed || typeof parsed !== "object") throw new Error("invalid_event")
      event = parsed as Record<string, unknown>
    } catch {
      this.callbacks.error("invalid_event")
      void this.stop().then(() => this.callbacks.state("error"))
      return
    }
    const type = typeof event.type === "string" ? event.type : ""
    if (type === "session.ready") {
      const vad = event.vad as Record<string, unknown> | undefined
      this.vad = new EnergyVad(
        number(vad?.threshold, 0.018),
        number(vad?.preroll_ms, 250),
        number(vad?.hangover_ms, 600),
        number(vad?.min_speech_ms, 300),
        number(vad?.urgent_ms, 120),
      )
      void this.startCapture()
    } else if (type === "session.state") {
      this.handleState(event.state)
    } else if (type === "transcript.partial") {
      this.callbacks.preview(string(event.text))
    } else if (type === "transcript.backchannel") {
      return
    } else if (type === "assistant.waiting") {
      this.callbacks.preview(string(event.text))
    } else if (type === "assistant.opening") {
      this.callbacks.preview(null)
      this.callbacks.message(localMessage("agent", string(event.text)))
    } else if (type === "transcript.final") {
      this.currentTurn = string(event.turn_id)
      this.assistantText = ""
      this.callbacks.preview(null)
      this.callbacks.message(localMessage("user", string(event.text)))
    } else if (type === "assistant.text.delta") {
      this.currentTurn = string(event.turn_id)
      this.assistantText += string(event.text)
      this.callbacks.preview(this.assistantText)
    } else if (type === "assistant.text.final") {
      this.callbacks.preview(null)
      this.callbacks.message(localMessage("agent", string(event.text)))
      this.assistantText = ""
    } else if (type === "assistant.cancelled") {
      this.clearPlayback()
      this.callbacks.preview(null)
    } else if (type === "workspace.tool") {
      this.handleTool(event)
    } else if (type === "model_trace") {
      const entry = modelTraceEntry(event)
      if (entry) this.callbacks.trace(entry)
    } else if (type === "session.error") {
      this.callbacks.error(string(event.code))
      if (event.retryable === true) this.callbacks.state("listening")
      else void this.stop().then(() => this.callbacks.state("error"))
    }
  }

  private handleState(raw: unknown): void {
    if (
      raw === "connecting" ||
      raw === "listening" ||
      raw === "thinking" ||
      raw === "speaking" ||
      raw === "paused" ||
      raw === "error"
    ) {
      this.callbacks.state(raw)
    } else if (raw === "closed") {
      this.callbacks.state("disconnected")
    }
  }

  private async startCapture(): Promise<void> {
    const context = this.capture
    const microphone = this.microphone
    if (!context || !microphone) throw new Error("microphone_unavailable")
    await context.audioWorklet.addModule(
      new URL("../../components/chat/pcmCapture.worklet.ts", import.meta.url),
    )
    this.source = context.createMediaStreamSource(microphone)
    this.worklet = new AudioWorkletNode(context, "pcm-capture")
    this.silentGain = context.createGain()
    this.silentGain.gain.value = 0
    this.source.connect(this.worklet)
    this.worklet.connect(this.silentGain)
    this.silentGain.connect(context.destination)
    this.worklet.port.onmessage = (event: MessageEvent<unknown>) => {
      if (!(event.data instanceof Float32Array) || this.muted) return
      this.captureFrame(event.data, context.sampleRate)
    }
    this.callbacks.state("listening")
  }

  private captureFrame(frame: Float32Array, sampleRate: number): void {
    const result = this.vad.process(frame, sampleRate)
    if (result.started) {
      this.send({
        type: "audio.start",
        sequence: ++this.sequence,
        codec: "pcm16",
        sample_rate: 24000,
        channels: 1,
      })
    }
    for (const item of result.frames) {
      if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(encodePcm16(item, sampleRate))
      }
    }
    if (result.abandon) {
      this.send({ type: "audio.cancel", turn_id: this.currentTurn })
    }
    if (result.commit) {
      this.send({
        type: "audio.commit",
        input_item_id: crypto.randomUUID(),
        sequence: ++this.sequence,
      })
    }
  }

  private play(data: ArrayBuffer): void {
    const context = this.playback
    if (!context) return
    const samples = decodePcm16(data)
    const buffer = context.createBuffer(1, samples.length, 24_000)
    buffer.getChannelData(0).set(samples)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    source.onended = () => this.playbackSources.delete(source)
    this.playbackSources.add(source)
    const start = Math.max(context.currentTime + 0.01, this.nextPlayback)
    source.start(start)
    this.nextPlayback = start + buffer.duration
  }

  private clearPlayback(): void {
    for (const source of this.playbackSources) {
      try {
        source.stop()
      } catch {
        // Playback may have ended between the event and interruption.
      }
    }
    this.playbackSources.clear()
    this.nextPlayback = this.playback?.currentTime ?? 0
  }

  private handleTool(event: Record<string, unknown>): void {
    const name = string(event.name)
    const args =
      event.arguments && typeof event.arguments === "object"
        ? event.arguments as Record<string, unknown>
        : {}
    void this.callbacks
      .tool(name, args, () => this.socket?.readyState === WebSocket.OPEN)
      .catch(() => this.callbacks.error("workspace_tool_failed"))
  }

  private send(payload: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload))
    }
  }
}

export function useLiveSpeechConversation(options: Options) {
  const { locale, t } = useLocale()
  const [status, setStatus] = useState<VoiceState>("disconnected")
  const [voice, setVoice] = useState(false)
  const [muted, setMuted] = useState(false)
  const client = useRef<LiveSpeechClient | null>(null)
  const generation = useRef(0)
  const latest = useRef(options)
  latest.current = options

  const stop = useCallback(async () => {
    generation.current += 1
    const current = client.current
    client.current = null
    setVoice(false)
    setMuted(false)
    setStatus("disconnected")
    if (current) await current.stop()
  }, [])

  useEffect(() => () => { void stop() }, [stop])
  useEffect(() => { void stop() }, [options.workspaceId, options.expertId, stop])

  const start = useCallback(async (_mode: "voice" | "text") => {
    if (!options.workspaceId || !options.expertId) {
      throw new Error(t("voiceWorkspaceChat.noExperts"))
    }
    await stop()
    let current: LiveSpeechClient
    current = new LiveSpeechClient(
      options.workspaceId,
      options.expertId,
      locale,
      {
        state: (next) => {
          if (client.current !== current) return
          setStatus(next)
          if (next === "disconnected" || next === "error") {
            setVoice(false)
            setMuted(false)
          }
        },
        message: (message) => { if (client.current === current) latest.current.onMessage(message) },
        preview: (text) => { if (client.current === current) latest.current.onPreview(text) },
        tool: (name, args, isCurrent): Promise<unknown> => client.current === current
          ? latest.current.onTool(name, args, () => client.current === current && isCurrent())
          : Promise.reject(new Error("stale_live_speech_session")),
        trace: (entry) => {
          if (client.current === current) latest.current.onModelTrace(entry)
        },
        error: (code) => {
          if (client.current !== current) return
          latest.current.onError(
            code.startsWith("stt_") || code === "empty_transcript"
              ? t("voiceWorkspaceChat.transcriptionError")
              : code === "tts_failed"
                ? t("voiceWorkspaceChat.speechError")
                : t("voiceWorkspaceChat.sessionError"),
          )
        },
      },
    )
    client.current = current
    const admittedGeneration = generation.current
    setVoice(true)
    try {
      await current.start()
    } catch (error) {
      await current.stop()
      if (client.current === current && generation.current === admittedGeneration) {
        client.current = null
        setStatus("error")
        setVoice(false)
      }
      throw error
    }
    return current
  }, [locale, options.expertId, options.workspaceId, stop, t])

  const toggleMute = useCallback(() => {
    const current = client.current
    if (current) setMuted(current.toggleMute())
  }, [])
  const cancel = useCallback((reason = "user") => client.current?.cancel(reason), [])

  return {
    status,
    voice,
    muted,
    start,
    stop,
    toggleMute,
    cancel,
    cancelForText: () => cancel("text_message"),
    contextualUpdate: (_text: string) => undefined,
    userActivity: () => undefined,
  }
}

function localMessage(role: "user" | "agent", content: string): WorkspaceMessage {
  return {
    id: -Date.now() - Math.floor(Math.random() * 1000),
    role,
    content,
    created_at: new Date().toISOString(),
    event_key: `live-speech:${crypto.randomUUID()}`,
    session_id: "live-speech",
  }
}

function string(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function number(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback
}
