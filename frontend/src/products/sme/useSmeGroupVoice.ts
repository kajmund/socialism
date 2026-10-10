import { useCallback, useEffect, useRef, useState } from "react"
import { authAdapter } from "@/lib/auth"
import { env } from "@/lib/env"

export type GroupVoiceSnapshot = {
  floor: string | null
  floor_name: string | null
  hands: string[]
  source_checked: string[]
  shared_result_count: number
}

type Options = {
  panelId: string | null
  enabled: boolean
}

export function useSmeGroupVoice({ panelId, enabled }: Options) {
  const [snapshot, setSnapshot] = useState<GroupVoiceSnapshot | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [listening, setListening] = useState(false)
  const socket = useRef<WebSocket | null>(null)
  const media = useRef<MediaStream | null>(null)
  const processor = useRef<ScriptProcessorNode | null>(null)
  const audioCtx = useRef<AudioContext | null>(null)

  const send = useCallback((payload: Record<string, unknown>) => {
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify(payload))
    }
  }, [])

  const playPcm = useCallback((pcm: ArrayBuffer) => {
    if (!audioCtx.current) {
      audioCtx.current = new AudioContext({ sampleRate: 24000 })
    }
    const ctx = audioCtx.current
    const int16 = new Int16Array(pcm)
    const float32 = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768
    const buffer = ctx.createBuffer(1, float32.length, 24000)
    buffer.copyToChannel(float32, 0)
    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)
    source.start()
  }, [])

  useEffect(() => {
    if (!enabled || !panelId) {
      setSnapshot(null)
      setConnected(false)
      return
    }

    let cancelled = false
    let ws: WebSocket | null = null

    void (async () => {
      const token = await authAdapter.getAccessToken()
      if (cancelled || !token) {
        setError("authentication_required")
        return
      }
      const url = `${env.wsBaseUrl}/ws/sme-group-voice?access_token=${encodeURIComponent(token)}`
      ws = new WebSocket(url)
      ws.binaryType = "arraybuffer"
      socket.current = ws

      ws.onopen = () => {
        if (cancelled) return
        setConnected(true)
        setError(null)
        ws?.send(JSON.stringify({ type: "start", panel_id: panelId }))
      }

      ws.onmessage = (event) => {
        if (cancelled) return
        if (event.data instanceof ArrayBuffer) {
          playPcm(event.data)
          return
        }
        try {
          const data = JSON.parse(String(event.data)) as { type?: string } & Partial<GroupVoiceSnapshot>
          if (data.type === "snapshot") {
            setSnapshot({
              floor: data.floor ?? null,
              floor_name: data.floor_name ?? null,
              hands: data.hands ?? [],
              source_checked: data.source_checked ?? [],
              shared_result_count: data.shared_result_count ?? 0,
            })
          } else if (data.type === "error") {
            setError(String((data as { detail?: string }).detail ?? "error"))
          }
        } catch {
          // ignore malformed
        }
      }

      ws.onerror = () => {
        if (!cancelled) setError("connection_failed")
      }

      ws.onclose = () => {
        if (!cancelled) {
          setConnected(false)
          socket.current = null
        }
      }
    })()

    return () => {
      cancelled = true
      ws?.close()
      socket.current = null
      setConnected(false)
      setListening(false)
      media.current?.getTracks().forEach((t) => t.stop())
      processor.current?.disconnect()
      audioCtx.current?.close()
    }
  }, [enabled, panelId, playPcm])

  const startListening = useCallback(async () => {
    if (listening || !socket.current) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      media.current = stream
      if (!audioCtx.current) audioCtx.current = new AudioContext({ sampleRate: 24000 })
      const source = audioCtx.current.createMediaStreamSource(stream)
      const proc = audioCtx.current.createScriptProcessor(4096, 1, 1)
      processor.current = proc
      proc.onaudioprocess = (e) => {
        if (socket.current?.readyState !== WebSocket.OPEN) return
        const input = e.inputBuffer.getChannelData(0)
        const pcm = new Int16Array(input.length)
        for (let i = 0; i < input.length; i++) {
          const s = Math.max(-1, Math.min(1, input[i]))
          pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
        }
        socket.current.send(pcm.buffer)
      }
      source.connect(proc)
      proc.connect(audioCtx.current.destination)
      setListening(true)
    } catch {
      setError("microphone_unavailable")
    }
  }, [listening])

  const stopListening = useCallback(() => {
    media.current?.getTracks().forEach((t) => t.stop())
    processor.current?.disconnect()
    media.current = null
    processor.current = null
    setListening(false)
    send({ type: "commit_audio" })
  }, [send])

  return {
    snapshot,
    connected,
    error,
    listening,
    startListening,
    stopListening,
    sendUtterance: (text: string) => send({ type: "utterance", text }),
    raiseHand: (personaId: string) => send({ type: "raise_hand", persona_id: personaId }),
    grantFloor: (personaId: string) => send({ type: "grant_floor", persona_id: personaId }),
    releaseFloor: (transcript = "") => send({ type: "release_floor", transcript }),
    attachTool: (personaId: string, toolName: string, summary = "", result: unknown = null) =>
      send({ type: "attach_tool", persona_id: personaId, tool_name: toolName, summary, result }),
  }
}
