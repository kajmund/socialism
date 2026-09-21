import { useCallback, useEffect, useRef, useState } from "react"
import type { SmeMessage } from "@/api/sme"
import { connectJsonWebSocket } from "@/lib/ws"

type Options = {
  onDone: (threadId: string, messages: SmeMessage[], requestId: string) => void
  onSuggestions: (threadId: string, questions: string[]) => void
  onError: (threadId: string | null, detail: string, requestId: string | null) => void
  onToken: (threadId: string, text: string, requestId: string) => void
  onThreadMessage: (threadId: string, messages: SmeMessage[]) => void
  onConsultAnswered: (threadId: string) => void
  onReady: () => void
  onDisconnected: () => void
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
  onThreadMessage,
  onConsultAnswered,
  onReady,
  onDisconnected,
}: Options) {
  const [ready, setReady] = useState(false)
  const sendRef = useRef<((payload: unknown) => void) | null>(null)
  const wasReadyRef = useRef(false)
  const callbacksRef = useRef({
    onDone,
    onSuggestions,
    onError,
    onToken,
    onThreadMessage,
    onConsultAnswered,
    onReady,
    onDisconnected,
  })
  callbacksRef.current = {
    onDone,
    onSuggestions,
    onError,
    onToken,
    onThreadMessage,
    onConsultAnswered,
    onReady,
    onDisconnected,
  }

  useEffect(() => {
    const connection = connectJsonWebSocket({
      path: "/ws/sme",
      onOpen: () => undefined,
      onStatus: (status) => {
        if (status !== "open") {
          setReady(false)
          if (status === "closed" && wasReadyRef.current) {
            wasReadyRef.current = false
            callbacksRef.current.onDisconnected()
          }
        }
      },
      onMessage: (raw) => {
        if (!raw || typeof raw !== "object") return
        const event = raw as Record<string, unknown>
        const threadId =
          typeof event.thread_id === "string" ? event.thread_id : null
        const requestId =
          typeof event.request_id === "string" ? event.request_id : null
        switch (event.type) {
          case "ready":
            wasReadyRef.current = true
            setReady(true)
            callbacksRef.current.onReady()
            break
          case "token":
            if (threadId && requestId && typeof event.text === "string") {
              callbacksRef.current.onToken(threadId, event.text, requestId)
            }
            break
          case "done":
            if (threadId && requestId) {
              callbacksRef.current.onDone(
                threadId,
                messagesFromUnknown(event.messages),
                requestId,
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
          case "thread.message":
            if (threadId) {
              callbacksRef.current.onThreadMessage(
                threadId,
                messagesFromUnknown(event.messages),
              )
            }
            break
          case "consult.answered":
            if (threadId) callbacksRef.current.onConsultAnswered(threadId)
            break
          case "error":
            callbacksRef.current.onError(
              threadId,
              typeof event.detail === "string" ? event.detail : "Chat error",
              requestId,
            )
            break
          default:
            break
        }
      },
    })
    sendRef.current = connection.send
    return () => {
      wasReadyRef.current = false
      connection.close()
      sendRef.current = null
      setReady(false)
    }
  }, [])

  const send = useCallback(
    (threadId: string, message: string, imageSha256?: string | null) => {
      if (!ready || !sendRef.current) return null
      const requestId = crypto.randomUUID()
      sendRef.current({
        type: "send",
        request_id: requestId,
        thread_type: "expert",
        thread_id: threadId,
        message,
        ...(imageSha256 ? { image_sha256: imageSha256 } : {}),
      })
      return requestId
    },
    [ready],
  )

  const resend = useCallback(
    (
      requestId: string,
      threadId: string,
      message: string,
      imageSha256?: string | null,
    ) => {
      if (!ready || !sendRef.current) return false
      sendRef.current({
        type: "send",
        request_id: requestId,
        thread_type: "expert",
        thread_id: threadId,
        message,
        ...(imageSha256 ? { image_sha256: imageSha256 } : {}),
      })
      return true
    },
    [ready],
  )

  return { ready, send, resend }
}
