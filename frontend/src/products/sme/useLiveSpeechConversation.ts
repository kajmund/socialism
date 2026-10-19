import { useCallback, useEffect, useRef, useState } from "react"
import type { WorkspaceMessage } from "@/api/voiceWorkspaces"
import { encodePcm16 } from "@/components/chat/liveVoiceAudio"
import { useLocale } from "@/i18n"
import { authAdapter } from "@/lib/auth"
import { env } from "@/lib/env"
import { liveSpeechMicrophone } from "./liveSpeechMicrophone"
import { isUrgentBargeIn } from "./liveSpeechBarge"
import { preloadSpeechVad } from "./speechVad"
import { SpeechVadPipeline } from "./speechVadPipeline"
import { startVoiceCapture, type VoiceCaptureHandle } from "./voiceCapture"
import { sourceIdsFromWorkspaceContext } from "./sttFocus"
import { PcmQueue } from "./pcmQueue"
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
  error: (code: string, retryable: boolean) => void
  trace: (entry: ModelTraceEntry) => void
}

export class LiveSpeechClient {
  private socket: WebSocket | null = null
  private capture: AudioContext | null = null
  private playback: AudioContext | null = null
  private microphone: MediaStream | null = null
  private captureHandle: VoiceCaptureHandle | null = null
  private pipeline: SpeechVadPipeline
  private queue = new PcmQueue()
  private sequence = 0
  private heartbeat: number | null = null
  private muted = false
  private currentTurn: string | null = null
  private assistantText = ""
  private pendingFocus: string[] | null = null
  private stopped = false
  private dropIncomingAudio = false
  private audioOpen = false
  private speaking = false
  private lastGeneration = 0
  private blockedThroughGeneration = 0
  private firstFrameAt = 0

  constructor(
    private readonly workspaceId: string,
    private readonly expertId: string,
    private readonly language: string,
    private readonly callbacks: Callbacks,
  ) {
    this.pipeline = new SpeechVadPipeline({
      onStarted: () => {
        if (this.firstFrameAt > 0) {
          this.sendLatency("vad_reaction", performance.now() - this.firstFrameAt)
        }
        this.send({
          type: "audio.start",
          sequence: ++this.sequence,
          codec: "pcm16",
          sample_rate: 24000,
          channels: 1,
        })
      },
      onFrames: (frames, sampleRate) => {
        for (const item of frames) {
          if (this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send(encodePcm16(item, sampleRate))
          }
        }
      },
      onAbandon: () => {
        this.send({ type: "audio.cancel", turn_id: this.currentTurn })
      },
      onCommit: () => {
        this.send({
          type: "audio.commit",
          input_item_id: crypto.randomUUID(),
          sequence: ++this.sequence,
        })
      },
      onError: () => {
        this.callbacks.error("vad_failed", false)
        void this.stop().then(() => this.callbacks.state("error"))
      },
    })
  }

  async start(): Promise<void> {
    this.callbacks.state("connecting")
    // The model loads in parallel with the permission prompt and the socket
    // handshake; frames are buffered until it is ready. Best effort: the
    // session path reports a model failure to the user.
    void preloadSpeechVad().catch(() => undefined)
    const microphone = await navigator.mediaDevices.getUserMedia({
      audio: liveSpeechMicrophone,
    })
    if (this.stopped) {
      for (const track of microphone.getTracks()) track.stop()
      throw new DOMException("Live Speech start cancelled", "AbortError")
    }
    this.microphone = microphone
    // 24 kHz lets the browser's filtered resampler do the 48k→24k step once;
    // Silero then resamples 2:3 to 16 kHz and the PCM goes out as-is. The code
    // reads context.sampleRate, so browsers that ignore the request still work.
    this.capture = new AudioContext({ sampleRate: 24_000 })
    this.playback = new AudioContext({ sampleRate: 24_000 })
    await Promise.all([this.capture.resume(), this.playback.resume()])
    if (this.stopped) throw new DOMException("Live Speech start cancelled", "AbortError")
    await this.startCapture()
    await this.connect()
  }

  async stop(): Promise<void> {
    if (this.stopped) return
    this.stopped = true
    this.pipeline.reset()
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.send({ type: "session.stop", reason: "user" })
    }
    this.socket?.close()
    this.socket = null
    if (this.heartbeat !== null) window.clearInterval(this.heartbeat)
    this.heartbeat = null
    this.clearPlayback()
    this.captureHandle?.stop()
    this.captureHandle = null
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
      this.pipeline.reset()
      this.send({ type: "audio.cancel", turn_id: this.currentTurn })
    }
    this.send({ type: "session.mute", muted: this.muted })
    this.callbacks.state(this.muted ? "paused" : "listening")
    return this.muted
  }

  cancel(reason = "user"): void {
    const stopStartedAt = performance.now()
    // Stop locally first: stale segments must never play after a barge-in.
    this.dropIncomingAudio = true
    this.audioOpen = false
    this.speaking = false
    this.blockedThroughGeneration = Math.max(
      this.blockedThroughGeneration,
      this.lastGeneration,
    )
    this.clearPlayback()
    this.sendLatency("stop_playback", performance.now() - stopStartedAt)
    if (this.currentTurn) {
      this.send({ type: "turn.cancel", turn_id: this.currentTurn, reason })
    }
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
        else void this.handleControl(String(event.data))
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

  focusDocuments(sourceIds: string[]): void {
    this.pendingFocus = sourceIds
    this.sendFocus()
  }

  private sendFocus(): void {
    if (this.pendingFocus === null || this.socket?.readyState !== WebSocket.OPEN) return
    this.send({ type: "stt.focus", source_ids: this.pendingFocus })
  }

  private async handleControl(raw: string): Promise<void> {
    let event: Record<string, unknown>
    try {
      const parsed: unknown = JSON.parse(raw)
      if (!parsed || typeof parsed !== "object") throw new Error("invalid_event")
      event = parsed as Record<string, unknown>
    } catch {
      this.callbacks.error("invalid_event", false)
      void this.stop().then(() => this.callbacks.state("error"))
      return
    }
    const type = typeof event.type === "string" ? event.type : ""
    if (type === "session.ready") {
      try {
        await this.pipeline.attach(event.vad)
      } catch {
        this.callbacks.error("vad_failed", false)
        void this.stop().then(() => this.callbacks.state("error"))
        return
      }
      this.sendFocus()
    } else if (type === "session.state") {
      this.handleState(event.state)
    } else if (type === "transcript.partial") {
      const text = string(event.text)
      this.callbacks.preview(text)
      if (this.speaking && isUrgentBargeIn(text)) this.cancel("urgent")
    } else if (type === "transcript.backchannel") {
      return
    } else if (type === "assistant.waiting") {
      this.callbacks.preview(string(event.text))
    } else if (type === "assistant.opening") {
      this.currentTurn = "opening"
      this.speaking = true
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
    } else if (type === "audio.output.start") {
      const generation = number(event.generation_id)
      if (generation !== null && generation <= this.blockedThroughGeneration) return
      if (generation !== null) this.lastGeneration = generation
      this.audioOpen = true
      this.dropIncomingAudio = false
      this.speaking = true
    } else if (type === "audio.output.end") {
      const generation = number(event.generation_id)
      if (generation === null || generation >= this.lastGeneration) {
        this.audioOpen = false
      }
    } else if (type === "assistant.cancelled") {
      this.dropIncomingAudio = true
      this.audioOpen = false
      this.speaking = false
      this.clearPlayback()
      this.callbacks.preview(null)
    } else if (type === "workspace.tool") {
      this.handleTool(event)
    } else if (type === "model_trace") {
      const entry = modelTraceEntry(event)
      if (entry) this.callbacks.trace(entry)
    } else if (type === "session.error") {
      this.callbacks.error(string(event.code), event.retryable === true)
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
      if (raw === "listening" || raw === "paused") {
        this.speaking = false
        if (raw === "listening") this.firstFrameAt = 0
      }
    } else if (raw === "closed") {
      this.callbacks.state("disconnected")
    }
  }

  private async startCapture(): Promise<void> {
    const context = this.capture
    const microphone = this.microphone
    if (!context || !microphone) throw new Error("microphone_unavailable")
    this.captureHandle = await startVoiceCapture(context, microphone, (frame, sampleRate) => {
      if (this.muted) return
      if (this.firstFrameAt === 0) this.firstFrameAt = performance.now()
      this.pipeline.feed(frame, sampleRate)
    })
  }

  private sendLatency(phase: string, milliseconds: number): void {
    this.send({ type: "client.latency", phase, milliseconds })
  }

  private play(data: ArrayBuffer): void {
    if (this.dropIncomingAudio || !this.audioOpen) return
    const context = this.playback
    if (!context) return
    this.queue.play(context, data)
  }

  private clearPlayback(): void {
    this.queue.stop(this.playback)
  }

  private handleTool(event: Record<string, unknown>): void {
    const name = string(event.name)
    const args =
      event.arguments && typeof event.arguments === "object"
        ? event.arguments as Record<string, unknown>
        : {}
    void this.callbacks
      .tool(name, args, () => this.socket?.readyState === WebSocket.OPEN)
      .catch(() => this.callbacks.error("workspace_tool_failed", false))
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
        error: (code, retryable) => {
          if (client.current !== current) return
          // A retryable empty transcript means VAD opened on noise; the
          // session stays listening, so do not toast it as a hard error.
          if (code === "empty_transcript" && retryable) return
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
    contextualUpdate: (text: string) => {
      const sourceIds = sourceIdsFromWorkspaceContext(text)
      if (sourceIds) client.current?.focusDocuments(sourceIds)
    },
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

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}
