/** WebSocket payloads for /ws/runs (run_watch scope). */

export type RunWatchAgent = {
  index: number
  username: string
  member_name: string
  persona_id: string | null
  role: string
}

export type RunWatchActivityItem = {
  user_id: number
  action: string
  post_id?: number
  comment_id?: number
  content?: string
  /** Post body preview for report_post / like_post rows (not the agent's own post text). */
  post_preview?: string
  /** Comment body preview for like_comment / dislike_comment rows. */
  comment_preview?: string
  /** Parsed + server-enriched trace.info fields for describeTimelineAction(). */
  info?: Record<string, unknown>
  created_at?: string | number
}

export type RunWatchRound = {
  tickIndex: number
  roundIndex: number
  items: RunWatchActivityItem[]
}

export type RunWatchTick = {
  tickIndex: number
  day?: number
  silent?: boolean
  key?: string
  rounds?: number
  completed?: boolean
}

export type RunWatchVariantPlan = {
  id: string
  label: string
}
