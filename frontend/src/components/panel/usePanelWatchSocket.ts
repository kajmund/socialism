import { useEffect, useState } from "react"
import type {
  PanelWatchExpertSlot,
  PanelWatchPendingTurn,
  PanelWatchSessionStatus,
  PanelWatchTurn,
  PanelWatchTurnPhase,
} from "@/data/panelWatch-types"
import { connectJsonWebSocket, type WsStatus } from "@/lib/ws"

function asExpertSlots(raw: unknown): PanelWatchExpertSlot[] {
  if (!Array.isArray(raw)) return []
  const out: PanelWatchExpertSlot[] = []
  for (const item of raw) {
    if (!item || typeof item !== "object") continue
    const row = item as Record<string, unknown>
    if (typeof row.slot_id !== "string") continue
    if (typeof row.label !== "string") continue
    out.push({
      slot_id: row.slot_id,
      label: row.label,
      profile: typeof row.profile === "string" ? row.profile : "",
    })
  }
  return out
}

function asTurnPhase(value: unknown): PanelWatchTurnPhase | null {
  if (typeof value !== "string") return null
  switch (value) {
    case "opening":
    case "raise_hand":
    case "expert":
    case "scratchpad":
    case "analysis":
    case "sub_question":
    case "score":
    case "unanswered":
      return value
    default:
      return null
  }
}

function asTurn(raw: unknown): PanelWatchTurn | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Record<string, unknown>
  if (typeof row.turn_id !== "string") return null
  if (typeof row.speaker !== "string") return null
  const phase = asTurnPhase(row.phase)
  if (phase == null) return null
  if (typeof row.content !== "string") return null
  return {
    turn_id: row.turn_id,
    speaker: row.speaker,
    phase,
    content: row.content,
    round_index: typeof row.round_index === "number" ? row.round_index : null,
    slot_id: typeof row.slot_id === "string" ? row.slot_id : null,
    sub_question_id:
      typeof row.sub_question_id === "string" ? row.sub_question_id : null,
  }
}

function asReplayTurns(raw: unknown): PanelWatchTurn[] {
  if (!Array.isArray(raw)) return []
  const out: PanelWatchTurn[] = []
  for (const item of raw) {
    const turn = asTurn(item)
    if (turn) out.push(turn)
  }
  return out
}

function upsertTurn(prev: PanelWatchTurn[], turn: PanelWatchTurn): PanelWatchTurn[] {
  const idx = prev.findIndex((row) => row.turn_id === turn.turn_id)
  if (idx >= 0) {
    return prev.map((row, i) => (i === idx ? turn : row))
  }
  return [...prev, turn]
}

type UsePanelWatchSocketOptions = {
  sessionId: string | null
  enabled: boolean
}

export function usePanelWatchSocket({ sessionId, enabled }: UsePanelWatchSocketOptions) {
  const [wsStatus, setWsStatus] = useState<WsStatus>("closed")
  const [sessionStatus, setSessionStatus] = useState<PanelWatchSessionStatus | null>(null)
  const [expertSlots, setExpertSlots] = useState<PanelWatchExpertSlot[]>([])
  const [turns, setTurns] = useState<PanelWatchTurn[]>([])
  const [pendingTurn, setPendingTurn] = useState<PanelWatchPendingTurn | null>(null)
  const [finished, setFinished] = useState(false)
  const [failedError, setFailedError] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled || !sessionId) {
      setWsStatus("closed")
      return
    }

    setSessionStatus(null)
    setExpertSlots([])
    setTurns([])
    setPendingTurn(null)
    setFinished(false)
    setFailedError(null)

    const conn = connectJsonWebSocket({
      path: "/ws/panels",
      onStatus: setWsStatus,
      onOpen: () => {
        conn.send({
          type: "hello",
          scope: "panel_watch",
          session_id: sessionId,
        })
      },
      onMessage: (data) => {
        if (!data || typeof data !== "object") return
        const msg = data as Record<string, unknown>
        switch (msg.type) {
          case "panel.replay": {
            const slots = asExpertSlots(msg.expert_slots)
            if (slots.length > 0) setExpertSlots(slots)
            const replayTurns = asReplayTurns(msg.turns)
            if (replayTurns.length > 0) setTurns(replayTurns)
            if (typeof msg.status === "string") {
              setSessionStatus(msg.status as PanelWatchSessionStatus)
              if (msg.status === "succeeded" || msg.status === "failed") {
                setFinished(true)
              }
            }
            break
          }
          case "turn.started": {
            if (typeof msg.turn_id !== "string") break
            if (typeof msg.speaker !== "string") break
            const phase = asTurnPhase(msg.phase)
            if (phase == null) break
            setPendingTurn({
              turn_id: msg.turn_id,
              speaker: msg.speaker,
              phase,
              round_index: typeof msg.round_index === "number" ? msg.round_index : null,
              slot_id: typeof msg.slot_id === "string" ? msg.slot_id : null,
              sub_question_id:
                typeof msg.sub_question_id === "string" ? msg.sub_question_id : null,
            })
            break
          }
          case "turn.completed": {
            const turn = asTurn(msg.turn)
            if (!turn) break
            setTurns((prev) => upsertTurn(prev, turn))
            setPendingTurn((prev) => (prev?.turn_id === turn.turn_id ? null : prev))
            break
          }
          case "panel.finished": {
            setFinished(true)
            if (typeof msg.status === "string") {
              setSessionStatus(msg.status as PanelWatchSessionStatus)
            }
            if (typeof msg.error === "string" && msg.error.trim()) {
              setFailedError(msg.error)
            }
            setPendingTurn(null)
            break
          }
          default:
            break
        }
      },
    })

    return () => conn.close()
  }, [enabled, sessionId])

  return {
    wsStatus,
    sessionStatus,
    expertSlots,
    turns,
    pendingTurn,
    finished,
    failedError,
  }
}
