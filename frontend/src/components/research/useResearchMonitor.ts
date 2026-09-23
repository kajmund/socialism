import { useCallback, useEffect, useRef, useState } from "react"
import {
  getResearchOverview,
  getResearchProgressEvents,
  type ResearchOverview,
  type ResearchProgressEvent,
} from "@/api/execution"
import { connectJsonWebSocket, type WsStatus } from "@/lib/ws"

function asProgressEvent(value: unknown): ResearchProgressEvent | null {
  if (!value || typeof value !== "object") return null
  const row = value as Record<string, unknown>
  if (
    typeof row.id !== "string" ||
    typeof row.attempt_id !== "string" ||
    typeof row.sequence !== "number" ||
    typeof row.event_type !== "string" ||
    typeof row.occurred_at !== "string"
  ) {
    return null
  }
  return {
    id: row.id,
    attempt_id: row.attempt_id,
    sequence: row.sequence,
    event_type: row.event_type,
    payload:
      row.payload && typeof row.payload === "object"
        ? (row.payload as Record<string, unknown>)
        : {},
    occurred_at: row.occurred_at,
  }
}

function mergeEvents(
  current: ResearchProgressEvent[],
  incoming: ResearchProgressEvent[],
): ResearchProgressEvent[] {
  const byId = new Map(current.map((event) => [event.id, event]))
  for (const event of incoming) byId.set(event.id, event)
  return [...byId.values()].sort((a, b) => a.sequence - b.sequence)
}

export function useResearchMonitor(attemptId: string | null) {
  const [overview, setOverview] = useState<ResearchOverview | null>(null)
  const [events, setEvents] = useState<ResearchProgressEvent[]>([])
  const [loading, setLoading] = useState(Boolean(attemptId))
  const [error, setError] = useState<string | null>(null)
  const [wsStatus, setWsStatus] = useState<WsStatus>("closed")
  const sequenceRef = useRef(0)
  const refreshTimer = useRef<number | undefined>(undefined)

  const refreshOverview = useCallback(async () => {
    if (!attemptId) return
    const next = await getResearchOverview(attemptId)
    setOverview(next)
  }, [attemptId])

  useEffect(() => {
    if (!attemptId) {
      setOverview(null)
      setEvents([])
      setLoading(false)
      return
    }
    const controller = new AbortController()
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      getResearchOverview(attemptId, { signal: controller.signal }),
      getResearchProgressEvents(attemptId, 0, { signal: controller.signal }),
    ])
      .then(([nextOverview, history]) => {
        if (cancelled) return
        setOverview(nextOverview)
        setEvents(history.events)
        sequenceRef.current = history.events.at(-1)?.sequence ?? 0
        setLoading(false)
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setLoading(false)
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [attemptId])

  useEffect(() => {
    if (!attemptId || loading || error) return
    const conn = connectJsonWebSocket({
      path: "/ws/research",
      onStatus: setWsStatus,
      onOpen: () => {
        conn.send({
          type: "hello",
          scope: "research_watch",
          attempt_id: attemptId,
          after_sequence: sequenceRef.current,
        })
        void refreshOverview()
      },
      onMessage: (data) => {
        if (!data || typeof data !== "object") return
        const message = data as Record<string, unknown>
        const incoming: ResearchProgressEvent[] = []
        if (message.type === "research.progress.replay" && Array.isArray(message.events)) {
          for (const raw of message.events) {
            const event = asProgressEvent(raw)
            if (event) incoming.push(event)
          }
        } else if (message.type === "research.progress") {
          const event = asProgressEvent(message)
          if (event) incoming.push(event)
        }
        if (incoming.length === 0) return
        sequenceRef.current = Math.max(
          sequenceRef.current,
          ...incoming.map((event) => event.sequence),
        )
        setEvents((current) => mergeEvents(current, incoming))
        if (refreshTimer.current != null) window.clearTimeout(refreshTimer.current)
        refreshTimer.current = window.setTimeout(() => {
          void refreshOverview()
        }, 200)
      },
    })
    return () => {
      conn.close()
      if (refreshTimer.current != null) window.clearTimeout(refreshTimer.current)
    }
  }, [attemptId, error, loading, refreshOverview])

  return { overview, events, loading, error, wsStatus, refreshOverview }
}
