/** WebSocket payloads for /ws/panels (panel_watch scope). */

export type PanelWatchTurnPhase =
  | "opening"
  | "raise_hand"
  | "expert"
  | "scratchpad"
  | "analysis"
  | "sub_question"
  | "score"

export type PanelWatchExpertSlot = {
  slot_id: string
  label: string
  profile: string
}

export type PanelWatchTurn = {
  turn_id: string
  speaker: string
  phase: PanelWatchTurnPhase
  content: string
  round_index?: number | null
  slot_id?: string | null
  sub_question_id?: string | null
}

export type PanelWatchPendingTurn = {
  turn_id: string
  speaker: string
  phase: PanelWatchTurnPhase
  round_index?: number | null
  slot_id?: string | null
  sub_question_id?: string | null
}

export type PanelWatchSessionStatus =
  | "draft"
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
