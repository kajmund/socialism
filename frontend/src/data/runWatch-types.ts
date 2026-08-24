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
