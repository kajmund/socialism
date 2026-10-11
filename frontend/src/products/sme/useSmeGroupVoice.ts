import { useCallback, useEffect, useRef, useState } from "react"
import { encodePcm16 } from "@/components/chat/liveVoiceAudio"
import { authAdapter } from "@/lib/auth"
import { env } from "@/lib/env"
import { EnergyVad } from "./liveSpeechVad"

export type GroupVoiceMember = { id: string; name: string }

export type GroupVoiceSnapshot = {
  floor: string | null
  floor_name: string | null
  hands: string[]
  members: GroupVoiceMember[]
  source_checked: string[]
  shared_result_count: number
}

export type GroupVoiceStatus =
  | "disconnected"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "paused"
  | "error"

type Options = {
  panelId: string | null
  enabled: boolean
  onUserTranscript?: (text: string) => void
  onUserPartial?: (text: string | null) => void
  onExpertSpeech?: (personaId: string, name: string | null, text: string) => void
}

export function useSmeGroupVoice({
  panelId,
  enabled,
  onUserTranscript,
  onUserPartial,
  onExpertSpeech,
}: Options) {
  const [snapshot, setSnapshot] = useState<GroupVoiceSnapshot | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [muted, setMuted] = useState(false)
  const [status, setStatus] = useState<GroupVoiceStatus>("disconnected")
  const socket = useRef<WebSocket | null>(null)
  const media = useRef<MediaStream | null>(null)
  const captureCtx = useRef<AudioContext | null>(null)
  const playbackCtx = useRef<AudioContext | null>(null)
  const nextPlayback = useRef(0)
  const vad = useRef(new EnergyVad(0.018, 250, 600))
  const mutedRef = useRef(false)
  const callbacks = useRef({ onUserTranscript, onUserPartial, onExpertSpeech })
  callbacks.current = { onUserTranscript, onUserPartial, onExpertSpeech }
  const members = useRef<GroupVoiceMember[]>([])

  const send = useCallback((payload: Record<string, unknown>) => {
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify(payload))
    }
  }, [])

  const primeAudio = useCallback(async () => {
    if (!playbackCtx.current) {
      playbackCtx.current = new AudioContext({ sampleRate: 24000 })
    }
    if (playbackCtx.current.state === "suspended") await playbackCtx.current.resume()
  }, [])

  const playPcm = useCallback((pcm: ArrayBuffer) => {
    if (!playbackCtx.current) {
      playbackCtx.current = new AudioContext({ sampleRate: 24000 })
    }
    const ctx = playbackCtx.current
    if (ctx.state === "suspended") void ctx.resume()
    const view = new DataView(pcm)
    const samples = new Float32Array(Math.floor(pcm.byteLength / 2))
    for (let index = 0; index < samples.length; index += 1) {
      const value = view.getInt16(index * 2, true)
      samples[index] = value < 0 ? value / 0x8000 : value / 0x7fff
    }
    const buffer = ctx.createBuffer(1, samples.length, 24000)
    buffer.copyToChannel(samples, 0)
    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)
    const start = Math.max(ctx.currentTime + 0.01, nextPlayback.current)
    source.start(start)
    nextPlayback.current = start + buffer.duration
  }, [])

  const applySnapshot = useCallback((data: Partial<GroupVoiceSnapshot>) => {
    setSnapshot({
      floor: data.floor ?? null,
      floor_name: data.floor_name ?? null,
      hands: data.hands ?? [],
      members: data.members ?? [],
      source_checked: data.source_checked ?? [],
      shared_result_count: data.shared_result_count ?? 0,
    })
    if (data.members) members.current = data.members
  }, [])

  useEffect(() => {
    if (!enabled || !panelId) {
      setSnapshot(null)
      setConnected(false)
      setMuted(false)
      mutedRef.current = false
      setStatus("disconnected")
      return
    }

    let cancelled = false
    let ws: WebSocket | null = null
    let worklet: AudioWorkletNode | null = null
    setStatus("connecting")
    vad.current = new EnergyVad(0.018, 250, 600)

    function sendFrame(frame: Float32Array, sampleRate: number) {
      if (mutedRef.current || socket.current?.readyState !== WebSocket.OPEN) return
      const result = vad.current.process(frame, sampleRate)
      for (const item of result.frames) {
        if (socket.current?.readyState === WebSocket.OPEN) {
          socket.current.send(encodePcm16(item, sampleRate))
        }
      }
      if (result.abandon) send({ type: "clear_audio" })
      if (result.commit) send({ type: "commit_audio" })
    }

    async function startCapture(stream: MediaStream) {
      const context = new AudioContext()
      captureCtx.current = context
      await context.audioWorklet.addModule(
        new URL("../../components/chat/pcmCapture.worklet.ts", import.meta.url),
      )
      if (cancelled) return
      const source = context.createMediaStreamSource(stream)
      worklet = new AudioWorkletNode(context, "pcm-capture")
      const silent = context.createGain()
      silent.gain.value = 0
      source.connect(worklet)
      worklet.connect(silent)
      silent.connect(context.destination)
      worklet.port.onmessage = (event: MessageEvent<unknown>) => {
        if (event.data instanceof Float32Array) sendFrame(event.data, context.sampleRate)
      }
      setStatus((current) => (current === "connecting" ? "listening" : current))
    }

    void (async () => {
      const token = await authAdapter.getAccessToken()
      if (cancelled || !token) {
        setError("authentication_required")
        setStatus("error")
        return
      }
      try {
        media.current = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        })
      } catch {
        if (!cancelled) {
          setError("microphone_unavailable")
          setStatus("error")
        }
        return
      }
      if (cancelled) return
      const url = `${env.wsBaseUrl}/ws/sme-group-voice?access_token=${encodeURIComponent(token)}`
      ws = new WebSocket(url)
      ws.binaryType = "arraybuffer"
      socket.current = ws

      ws.onopen = () => {
        if (cancelled) return
        setConnected(true)
        setError(null)
        ws?.send(JSON.stringify({ type: "start", panel_id: panelId }))
        const stream = media.current
        if (stream) void startCapture(stream).catch(() => { if (!cancelled) setStatus("error") })
      }

      ws.onmessage = (event) => {
        if (cancelled) return
        if (event.data instanceof ArrayBuffer) {
          setStatus("speaking")
          playPcm(event.data)
          return
        }
        try {
          const data = JSON.parse(String(event.data)) as { type?: string; text?: string; persona_id?: string; floor_name?: string } & Partial<GroupVoiceSnapshot>
          if (data.type === "snapshot") {
            applySnapshot(data)
          } else if (data.type === "transcript.partial") {
            callbacks.current.onUserPartial?.(data.text ?? "")
            setStatus("listening")
          } else if (data.type === "transcript.final") {
            callbacks.current.onUserPartial?.(null)
            if (data.text) callbacks.current.onUserTranscript?.(data.text)
            setStatus("thinking")
          } else if (data.type === "assistant.speaking") {
            const personaId = data.persona_id ?? ""
            const name = members.current.find((member) => member.id === personaId)?.name ?? null
            if (data.text) callbacks.current.onExpertSpeech?.(personaId, name, data.text)
            setStatus("speaking")
          } else if (data.type === "assistant.done") {
            setStatus(mutedRef.current ? "paused" : "listening")
          } else if (data.type === "error") {
            setError(String((data as { detail?: string }).detail ?? "error"))
          }
        } catch {
          // ignore malformed
        }
      }

      ws.onerror = () => {
        if (!cancelled) {
          setError("connection_failed")
          setStatus("error")
        }
      }

      ws.onclose = () => {
        if (!cancelled) {
          setConnected(false)
          socket.current = null
          setStatus("disconnected")
        }
      }
    })()

    return () => {
      cancelled = true
      ws?.close()
      socket.current = null
      setConnected(false)
      worklet?.disconnect()
      media.current?.getTracks().forEach((track) => track.stop())
      media.current = null
      void captureCtx.current?.close()
      captureCtx.current = null
      void playbackCtx.current?.close()
      playbackCtx.current = null
      nextPlayback.current = 0
    }
  }, [applySnapshot, enabled, panelId, playPcm, send])

  const toggleMute = useCallback(() => {
    mutedRef.current = !mutedRef.current
    setMuted(mutedRef.current)
    if (mutedRef.current) {
      vad.current = new EnergyVad(0.018, 250, 600)
      send({ type: "clear_audio" })
      setStatus("paused")
    } else {
      setStatus("listening")
    }
  }, [send])

  return {
    snapshot,
    connected,
    error,
    muted,
    status,
    primeAudio,
    toggleMute,
    sendUtterance: (text: string) => send({ type: "utterance", text }),
    raiseHand: (personaId: string) => send({ type: "raise_hand", persona_id: personaId }),
    grantFloor: (personaId: string) => send({ type: "grant_floor", persona_id: personaId }),
    releaseFloor: (transcript = "") => send({ type: "release_floor", transcript }),
    attachTool: (personaId: string, toolName: string, summary = "", result: unknown = null) =>
      send({ type: "attach_tool", persona_id: personaId, tool_name: toolName, summary, result }),
  }
}
