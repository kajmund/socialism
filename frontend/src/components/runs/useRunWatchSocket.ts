import { useEffect, useState } from "react"
import type {
  RunWatchActivityItem,
  RunWatchAgent,
  RunWatchRound,
  RunWatchTick,
} from "@/data/runWatch-types"
import { connectJsonWebSocket, type WsStatus } from "@/lib/ws"

function upsertRound(prev: RunWatchRound[], round: RunWatchRound): RunWatchRound[] {
  const idx = prev.findIndex(
    (row) => row.tickIndex === round.tickIndex && row.roundIndex === round.roundIndex,
  )
  const next = idx >= 0 ? prev.map((row, i) => (i === idx ? round : row)) : [...prev, round]
  return next.sort(
    (a, b) => a.tickIndex - b.tickIndex || a.roundIndex - b.roundIndex,
  )
}

function upsertTick(prev: RunWatchTick[], tick: RunWatchTick): RunWatchTick[] {
  const idx = prev.findIndex((row) => row.tickIndex === tick.tickIndex)
  const next = idx >= 0
    ? prev.map((row, i) => (i === idx ? { ...row, ...tick } : row))
    : [...prev, tick]
  return next.sort((a, b) => a.tickIndex - b.tickIndex)
}

function asAgents(raw: unknown): RunWatchAgent[] {
  if (!Array.isArray(raw)) return []
  const out: RunWatchAgent[] = []
  for (const item of raw) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (typeof row.index !== "number") continue
    out.push({
      index: row.index,
      username: typeof row.username === "string" ? row.username : "",
      member_name: typeof row.member_name === "string" ? row.member_name : "",
      persona_id: typeof row.persona_id === "string" ? row.persona_id : null,
      role: typeof row.role === "string" ? row.role : "population",
    })
  }
  return out
}

function asActivityItems(raw: unknown): RunWatchActivityItem[] {
  if (!Array.isArray(raw)) return []
  const out: RunWatchActivityItem[] = []
  for (const item of raw) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (typeof row.user_id !== "number") continue
    if (typeof row.action !== "string") continue
    const parsed: RunWatchActivityItem = {
      user_id: row.user_id,
      action: row.action,
    }
    if (typeof row.post_id === "number") parsed.post_id = row.post_id
    if (typeof row.comment_id === "number") parsed.comment_id = row.comment_id
    if (typeof row.content === "string" && row.content) parsed.content = row.content
    if (row.created_at != null && row.created_at !== "") {
      parsed.created_at = row.created_at as string | number
    }
    out.push(parsed)
  }
  return out
}

function asReplayRounds(raw: unknown): RunWatchRound[] {
  if (!Array.isArray(raw)) return []
  const out: RunWatchRound[] = []
  for (const item of raw) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (typeof row.tick_index !== "number") continue
    if (typeof row.round_index !== "number") continue
    out.push({
      tickIndex: row.tick_index,
      roundIndex: row.round_index,
      items: asActivityItems(row.items),
    })
  }
  return out
}

type UseRunWatchSocketOptions = {
  runId: number | null
  variantId: string | null
  enabled: boolean
}

export function useRunWatchSocket({
  runId,
  variantId,
  enabled,
}: UseRunWatchSocketOptions) {
  const [wsStatus, setWsStatus] = useState<WsStatus>("closed")
  const [agents, setAgents] = useState<RunWatchAgent[]>([])
  const [attemptId, setAttemptId] = useState<string | null>(null)
  const [rounds, setRounds] = useState<RunWatchRound[]>([])
  const [ticks, setTicks] = useState<RunWatchTick[]>([])
  const [finished, setFinished] = useState(false)
  const [failedError, setFailedError] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled || runId == null || !variantId) {
      setWsStatus("closed")
      return
    }

    setAgents([])
    setAttemptId(null)
    setRounds([])
    setTicks([])
    setFinished(false)
    setFailedError(null)

    const conn = connectJsonWebSocket({
      path: "/ws/runs",
      onStatus: setWsStatus,
      onOpen: () => {
        conn.send({
          type: "hello",
          scope: "run_watch",
          run_id: runId,
          variant_id: variantId,
        })
      },
      onMessage: (data) => {
        if (!data || typeof data !== "object") return
        const msg = data as Record<string, unknown>
        switch (msg.type) {
          case "run.replay": {
            const replayRounds = asReplayRounds(msg.rounds)
            if (replayRounds.length === 0) break
            setRounds((prev) => {
              let next = prev
              for (const round of replayRounds) {
                next = upsertRound(next, round)
              }
              return next
            })
            break
          }
          case "round.activity": {
            if (typeof msg.tick_index !== "number") break
            if (typeof msg.round_index !== "number") break
            setRounds((prev) =>
              upsertRound(prev, {
                tickIndex: msg.tick_index as number,
                roundIndex: msg.round_index as number,
                items: asActivityItems(msg.items),
              }),
            )
            break
          }
          case "run.attempt_started": {
            if (typeof msg.attempt_id === "string") {
              setAttemptId(msg.attempt_id)
            }
            const nextAgents = asAgents(msg.agents)
            if (nextAgents.length > 0) setAgents(nextAgents)
            break
          }
          case "tick.started": {
            if (typeof msg.tick_index !== "number") break
            setTicks((prev) =>
              upsertTick(prev, {
                tickIndex: msg.tick_index,
                day: typeof msg.day === "number" ? msg.day : undefined,
                silent: msg.silent === true,
                key: typeof msg.key === "string" ? msg.key : undefined,
                rounds: typeof msg.rounds === "number" ? msg.rounds : undefined,
                completed: false,
              }),
            )
            break
          }
          case "tick.completed": {
            if (typeof msg.tick_index !== "number") break
            setTicks((prev) =>
              upsertTick(prev, {
                tickIndex: msg.tick_index,
                day: typeof msg.day === "number" ? msg.day : undefined,
                silent: msg.silent === true,
                key: typeof msg.key === "string" ? msg.key : undefined,
                rounds: typeof msg.rounds === "number" ? msg.rounds : undefined,
                completed: true,
              }),
            )
            break
          }
          case "variant.failed": {
            const error =
              typeof msg.error === "string" && msg.error.trim()
                ? msg.error
                : "unknown error"
            setFailedError(error)
            break
          }
          case "run.attempt_finished": {
            setFinished(true)
            if (typeof msg.error === "string" && msg.error.trim()) {
              setFailedError(msg.error)
            }
            break
          }
          default:
            break
        }
      },
    })

    return () => conn.close()
  }, [enabled, runId, variantId])

  return {
    wsStatus,
    agents,
    attemptId,
    rounds,
    ticks,
    finished,
    failedError,
  }
}
