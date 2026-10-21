import { useCallback, useEffect, useRef, useState } from "react"
import { encodePcm16 } from "@/components/chat/liveVoiceAudio"
import { authAdapter } from "@/lib/auth"
import { env } from "@/lib/env"
import { liveSpeechMicrophone } from "./liveSpeechMicrophone"
import { preloadSpeechVad } from "./speechVad"
import { SpeechVadPipeline } from "./speechVadPipeline"
import { startVoiceCapture, type VoiceCaptureHandle } from "./voiceCapture"
import { splitGenerationFrame } from "./liveSpeechPcm"
import { PcmQueue } from "./pcmQueue"

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
  workspaceId: string | null
  enabled: boolean
  onUserTranscript?: (text: string) => void
  onUserPartial?: (text: string | null) => void
  onExpertSpeech?: (personaId: string, name: string | null, text: string) => void
  onWorkspaceTool?: (name: string, args: Record<string, unknown>) => void
}

export function useSmeGroupVoice({
  panelId,
  workspaceId,
  enabled,
  onUserTranscript,
  onUserPartial,
  onExpertSpeech,
  onWorkspaceTool,
}: Options) {
  const [snapshot, setSnapshot] = useState<GroupVoiceSnapshot | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [muted, setMuted] = useState(false)
  const [status, setStatus] = useState<GroupVoiceStatus>("disconnected")
  const socket = useRef<WebSocket | null>(null)
  const media = useRef<MediaStream | null>(null)
  const captureCtx = useRef<AudioContext | null>(null)
  const captureHandle = useRef<VoiceCaptureHandle | null>(null)
  const pipeline = useRef<SpeechVadPipeline | null>(null)
  const playbackCtx = useRef<AudioContext | null>(null)
  const queue = useRef(new PcmQueue())
  const dropIncoming = useRef(false)
  const mutedRef = useRef(false)
  const callbacks = useRef({ onUserTranscript, onUserPartial, onExpertSpeech, onWorkspaceTool })
  callbacks.current = { onUserTranscript, onUserPartial, onExpertSpeech, onWorkspaceTool }
  const members = useRef<GroupVoiceMember[]>([])
  const workspace = useRef(workspaceId)
  workspace.current = workspaceId

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
    if (dropIncoming.current) return
    if (!playbackCtx.current) {
      playbackCtx.current = new AudioContext({ sampleRate: 24000 })
    }
    const ctx = playbackCtx.current
    if (ctx.state === "suspended") void ctx.resume()
    const framed = splitGenerationFrame(pcm)
    if (framed === null) return
    queue.current.play(ctx, framed.pcm)
  }, [])

  const stopPlayback = useCallback(() => {
    dropIncoming.current = true
    queue.current.stop(playbackCtx.current)
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
    const queued = queue.current
    setStatus("connecting")

    const vad = new SpeechVadPipeline({
      onFrames: (frames, sampleRate) => {
        for (const item of frames) {
          if (socket.current?.readyState === WebSocket.OPEN) {
            socket.current.send(encodePcm16(item, sampleRate))
          }
        }
      },
      onAbandon: () => send({ type: "clear_audio" }),
      onCommit: () => send({ type: "commit_audio" }),
      onError: () => {
        if (!cancelled) setStatus("error")
      },
    })
    pipeline.current = vad

    async function startCapture(stream: MediaStream) {
      // Same 24 kHz capture as a single expert: the browser resamples with a
      // filter, and the code below reads the actual context.sampleRate.
      const context = new AudioContext({ sampleRate: 24_000 })
      captureCtx.current = context
      captureHandle.current = await startVoiceCapture(context, stream, (frame, sampleRate) => {
        if (mutedRef.current) return
        vad.feed(frame, sampleRate)
      })
    }

    void (async () => {
      // Load the speech model in parallel with permission and the socket.
      void preloadSpeechVad().catch(() => undefined)
      const token = await authAdapter.getAccessToken()
      if (cancelled || !token) {
        setError("authentication_required")
        setStatus("error")
        return
      }
      try {
        media.current = await navigator.mediaDevices.getUserMedia({ audio: liveSpeechMicrophone })
      } catch {
        if (!cancelled) {
          setError("microphone_unavailable")
          setStatus("error")
        }
        return
      }
      if (cancelled) return
      try {
        // Capture before the model is ready so early speech is buffered.
        await startCapture(media.current)
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
        ws?.send(JSON.stringify({
          type: "start",
          panel_id: panelId,
          ...(workspace.current ? { workspace_id: workspace.current } : {}),
        }))
      }

      ws.onmessage = (event) => {
        if (cancelled) return
        if (event.data instanceof ArrayBuffer) {
          if (!dropIncoming.current) setStatus("speaking")
          playPcm(event.data)
          return
        }
        try {
          const data = JSON.parse(String(event.data)) as {
            type?: string
            text?: string
            persona_id?: string
            floor_name?: string
            vad?: unknown
            name?: string
            arguments?: Record<string, unknown>
          } & Partial<GroupVoiceSnapshot>
          if (data.type === "ready") {
            void vad.attach(data.vad).then(() => {
              if (!cancelled) setStatus("listening")
            }).catch(() => { if (!cancelled) setStatus("error") })
          } else if (data.type === "snapshot") {
            applySnapshot(data)
          } else if (data.type === "transcript.partial") {
            callbacks.current.onUserPartial?.(data.text ?? "")
            setStatus("listening")
          } else if (data.type === "transcript.final") {
            callbacks.current.onUserPartial?.(null)
            if (data.text) callbacks.current.onUserTranscript?.(data.text)
            setStatus("thinking")
          } else if (data.type === "assistant.speaking") {
            dropIncoming.current = false
            const personaId = data.persona_id ?? ""
            const name = members.current.find((member) => member.id === personaId)?.name ?? null
            if (data.text) callbacks.current.onExpertSpeech?.(personaId, name, data.text)
            setStatus("speaking")
          } else if (data.type === "assistant.cancelled") {
            stopPlayback()
            setStatus(mutedRef.current ? "paused" : "listening")
          } else if (data.type === "assistant.done" || data.type === "listening") {
            setStatus(mutedRef.current ? "paused" : "listening")
          } else if (data.type === "workspace.tool" && data.name && data.arguments) {
            callbacks.current.onWorkspaceTool?.(data.name, data.arguments)
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
      captureHandle.current?.stop()
      captureHandle.current = null
      pipeline.current = null
      media.current?.getTracks().forEach((track) => track.stop())
      media.current = null
      void captureCtx.current?.close()
      captureCtx.current = null
      const playback = playbackCtx.current
      queued.stop(playback)
      void playback?.close()
      playbackCtx.current = null
    }
  }, [applySnapshot, enabled, panelId, playPcm, send, stopPlayback])

  const toggleMute = useCallback(() => {
    mutedRef.current = !mutedRef.current
    setMuted(mutedRef.current)
    if (mutedRef.current) {
      pipeline.current?.reset()
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
