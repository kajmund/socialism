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
  const socket = useRef<WebSocket | null>(null)

  const send = useCallback((payload: Record<string, unknown>) => {
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify(payload))
    }
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
      socket.current = ws

      ws.onopen = () => {
        if (cancelled) return
        setConnected(true)
        setError(null)
        ws?.send(JSON.stringify({ type: "start", panel_id: panelId }))
      }

      ws.onmessage = (event) => {
        if (cancelled) return
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
    }
  }, [enabled, panelId])

  return {
    snapshot,
    connected,
    error,
    sendUtterance: (text: string) => send({ type: "utterance", text }),
    raiseHand: (personaId: string) => send({ type: "raise_hand", persona_id: personaId }),
    grantFloor: (personaId: string) => send({ type: "grant_floor", persona_id: personaId }),
    releaseFloor: (transcript = "") => send({ type: "release_floor", transcript }),
    attachTool: (personaId: string, toolName: string, summary = "", result: unknown = null) =>
      send({ type: "attach_tool", persona_id: personaId, tool_name: toolName, summary, result }),
  }
}
