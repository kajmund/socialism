import { useCallback, useEffect, useRef, useState } from "react"
import type { ChatMode, PersonaMessage } from "@/api/personas"
import { connectJsonWebSocket } from "@/lib/ws"

export type ChatHello =
  | { scope: "library"; persona_id: string; mode: ChatMode }
  | {
      scope: "run_interview"
      run_id: number
      attempt_id: string
      variant_id: string
      persona_id: string
      through_tick_index: number
    }
  | { scope: "help"; session_id: string; locale: "sv" | "en"; view: HelpViewPayload }
  | {
      scope: "spinndoctor"
      session_id: string
      report_id: string
      locale: "sv" | "en"
    }

export type HelpViewPayload = {
  path: string
  view_key: string
  label: string
  params: Record<string, string>
  search: Record<string, string>
}

export type ChatDoneMessage = {
  id: number
  role: "user" | "assistant"
  content: string
  mode?: ChatMode
  created_at?: string
}

type UseChatSocketOptions = {
  hello: ChatHello | null
  sendExtras?: () => Record<string, unknown>
  onDone: (messages: ChatDoneMessage[]) => void
  onError: (detail: string) => void
}

function helloKey(hello: ChatHello | null): string {
  if (!hello) return ""
  if (hello.scope === "library") {
    return `library:${hello.persona_id}:${hello.mode}`
  }
  if (hello.scope === "help") {
    const viewKey = [
      hello.view.path,
      hello.view.view_key,
      JSON.stringify(hello.view.params),
      JSON.stringify(hello.view.search),
    ].join("|")
    return `help:${hello.session_id}:${hello.locale}:${viewKey}`
  }
  if (hello.scope === "spinndoctor") {
    return `spinndoctor:${hello.session_id}:${hello.report_id}:${hello.locale}`
  }
  return [
    "run",
    hello.run_id,
    hello.attempt_id,
    hello.variant_id,
    hello.persona_id,
    hello.through_tick_index,
  ].join(":")
}

function asDoneMessages(raw: unknown): ChatDoneMessage[] {
  if (!Array.isArray(raw)) return []
  const out: ChatDoneMessage[] = []
  for (const item of raw) {
    if (!item || typeof item !== "object") continue
    const m = item as Record<string, unknown>
    if (typeof m.id !== "number") continue
    if (m.role !== "user" && m.role !== "assistant") continue
    if (typeof m.content !== "string") continue
    out.push({
      id: m.id,
      role: m.role,
      content: m.content,
      mode: m.mode as ChatMode | undefined,
      created_at: typeof m.created_at === "string" ? m.created_at : undefined,
    })
  }
  return out
}

export function useChatSocket({ hello, sendExtras, onDone, onError }: UseChatSocketOptions) {
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [typing, setTyping] = useState(false)
  const [streamText, setStreamText] = useState<string | null>(null)
  const sendRef = useRef<((payload: unknown) => void) | null>(null)
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError
  const sendExtrasRef = useRef(sendExtras)
  sendExtrasRef.current = sendExtras
  const key = helloKey(hello)

  useEffect(() => {
    if (!hello) {
      setReady(false)
      sendRef.current = null
      return
    }

    const helloPayload = { type: "hello" as const, ...hello }
    const conn = connectJsonWebSocket({
      path: "/ws/chat",
      onOpen: () => {
        conn.send(helloPayload)
      },
      onMessage: (data) => {
        if (!data || typeof data !== "object") return
        const msg = data as Record<string, unknown>
        switch (msg.type) {
          case "ready":
            setReady(true)
            break
          case "typing":
            setTyping(Boolean(msg.on))
            if (msg.on) setStreamText(null)
            break
          case "token":
            if (typeof msg.text === "string") {
              setTyping(false)
              setStreamText((prev) => (prev ?? "") + msg.text)
            }
            break
          case "done": {
            setTyping(false)
            setStreamText(null)
            setBusy(false)
            const rows = asDoneMessages(msg.messages)
            if (rows.length > 0) onDoneRef.current(rows)
            break
          }
          case "error":
            setTyping(false)
            setStreamText(null)
            setBusy(false)
            onErrorRef.current(
              typeof msg.detail === "string" ? msg.detail : "Chat error",
            )
            break
          default:
            break
        }
      },
      onStatus: (status) => {
        if (status !== "open") setReady(false)
      },
    })
    sendRef.current = conn.send

    return () => {
      conn.close()
      sendRef.current = null
      setReady(false)
      setBusy(false)
      setTyping(false)
      setStreamText(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || !hello || busy) return false
      if (!sendRef.current || !ready) {
        return false
      }
      setBusy(true)
      setTyping(true)
      setStreamText(null)
      const extras = sendExtrasRef.current?.() ?? {}
      sendRef.current({ type: "send", message: trimmed, ...extras })
      return true
    },
    [hello, busy, ready],
  )

  return { ready, busy, typing, streamText, send }
}

export function doneToPersonaMessages(
  rows: ChatDoneMessage[],
  fallbackMode: ChatMode,
): PersonaMessage[] {
  return rows.map((m) => ({
    id: m.id,
    mode: (m.mode ?? fallbackMode) as ChatMode,
    role: m.role,
    content: m.content,
    created_at: m.created_at ?? "",
  }))
}
