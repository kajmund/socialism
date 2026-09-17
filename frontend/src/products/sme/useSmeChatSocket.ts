import { useCallback, useEffect, useRef, useState } from "react"
import type { SmeMessage } from "@/api/sme"
import { connectJsonWebSocket } from "@/lib/ws"

type Options = {
  onDone: (threadId: string, messages: SmeMessage[]) => void
  onSuggestions: (threadId: string, questions: string[]) => void
  onError: (threadId: string | null, detail: string) => void
  onToken: (threadId: string, text: string) => void
}

function messagesFromUnknown(raw: unknown): SmeMessage[] {
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item): SmeMessage[] => {
    if (!item || typeof item !== "object") return []
    const row = item as Record<string, unknown>
    if (typeof row.id !== "number") return []
    if (row.role !== "user" && row.role !== "assistant") return []
    if (typeof row.content !== "string") return []
    return [
      {
        id: row.id,
        role: row.role,
        content: row.content,
        created_at: typeof row.created_at === "string" ? row.created_at : "",
        persona_id: null,
        persona_name: null,
        image_sha256:
          typeof row.image_sha256 === "string" ? row.image_sha256 : null,
      },
    ]
  })
}

function questionsFromUnknown(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (question): question is string =>
      typeof question === "string" && Boolean(question.trim()),
  )
}

export function useSmeChatSocket({
  onDone,
  onSuggestions,
  onError,
  onToken,
}: Options) {
  const [ready, setReady] = useState(false)
  const sendRef = useRef<((payload: unknown) => void) | null>(null)
  const callbacksRef = useRef({ onDone, onSuggestions, onError, onToken })
  callbacksRef.current = { onDone, onSuggestions, onError, onToken }

  useEffect(() => {
    const connection = connectJsonWebSocket({
      path: "/ws/sme",
      onOpen: () => undefined,
      onStatus: (status) => {
        if (status !== "open") setReady(false)
      },
      onMessage: (raw) => {
        if (!raw || typeof raw !== "object") return
        const event = raw as Record<string, unknown>
        const threadId =
          typeof event.thread_id === "string" ? event.thread_id : null
        switch (event.type) {
          case "ready":
            setReady(true)
            break
          case "token":
            if (threadId && typeof event.text === "string") {
              callbacksRef.current.onToken(threadId, event.text)
            }
            break
          case "done":
            if (threadId) {
              callbacksRef.current.onDone(
                threadId,
                messagesFromUnknown(event.messages),
              )
            }
            break
          case "suggestions":
            if (threadId) {
              callbacksRef.current.onSuggestions(
                threadId,
                questionsFromUnknown(event.questions),
              )
            }
            break
          case "error":
            callbacksRef.current.onError(
              threadId,
              typeof event.detail === "string" ? event.detail : "Chat error",
            )
            break
          default:
            break
        }
      },
    })
    sendRef.current = connection.send
    return () => {
      connection.close()
      sendRef.current = null
      setReady(false)
    }
  }, [])

  const send = useCallback(
    (threadId: string, message: string, imageSha256?: string | null) => {
      if (!ready || !sendRef.current) return false
      sendRef.current({
        type: "send",
        request_id: crypto.randomUUID(),
        thread_type: "expert",
        thread_id: threadId,
        message,
        ...(imageSha256 ? { image_sha256: imageSha256 } : {}),
      })
      return true
    },
    [ready],
  )

  return { ready, send }
}
