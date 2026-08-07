import { env } from "@/lib/env"

export type WsStatus = "connecting" | "open" | "closed"

export type ReconnectingWebSocketOptions = {
  /** Path beginning with `/`, e.g. `/ws/jobs`. */
  path: string
  onMessage: (data: unknown) => void
  onStatus?: (status: WsStatus) => void
  /** Called after each successful open (including reconnects). */
  onOpen?: () => void
  /** Initial reconnect delay in ms (doubles up to max). */
  baseDelayMs?: number
  maxDelayMs?: number
}

/**
 * Thin reconnecting WebSocket. No deps — browser WebSocket only.
 */
export function connectJsonWebSocket(options: ReconnectingWebSocketOptions): {
  send: (payload: unknown) => void
  close: () => void
} {
  const baseDelay = options.baseDelayMs ?? 800
  const maxDelay = options.maxDelayMs ?? 12_000
  let closedByUser = false
  let socket: WebSocket | null = null
  let retryTimer: number | undefined
  let delay = baseDelay
  let attempt = 0

  function url(): string {
    const base = env.wsBaseUrl.replace(/\/$/, "")
    const path = options.path.startsWith("/") ? options.path : `/${options.path}`
    return `${base}${path}`
  }

  function setStatus(status: WsStatus) {
    options.onStatus?.(status)
  }

  function scheduleReconnect() {
    if (closedByUser) return
    if (retryTimer != null) window.clearTimeout(retryTimer)
    retryTimer = window.setTimeout(() => {
      retryTimer = undefined
      open()
    }, delay)
    delay = Math.min(maxDelay, delay * 2)
  }

  function open() {
    if (closedByUser) return
    setStatus("connecting")
    const ws = new WebSocket(url())
    socket = ws

    ws.onopen = () => {
      delay = baseDelay
      attempt = 0
      setStatus("open")
      options.onOpen?.()
    }

    ws.onmessage = (event) => {
      try {
        const parsed: unknown = JSON.parse(String(event.data))
        options.onMessage(parsed)
      } catch {
        // Ignore non-JSON frames.
      }
    }

    ws.onerror = () => {
      // onclose follows; reconnect there.
    }

    ws.onclose = () => {
      if (socket === ws) socket = null
      setStatus("closed")
      if (!closedByUser) {
        attempt += 1
        scheduleReconnect()
      }
    }
  }

  open()

  return {
    send(payload: unknown) {
      if (!socket || socket.readyState !== WebSocket.OPEN) return
      socket.send(JSON.stringify(payload))
    },
    close() {
      closedByUser = true
      if (retryTimer != null) window.clearTimeout(retryTimer)
      retryTimer = undefined
      if (socket) {
        socket.close()
        socket = null
      }
      setStatus("closed")
    },
  }
}
