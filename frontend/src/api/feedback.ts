import { api } from "@/lib/api"

export type FeedbackKind = "bug" | "idea" | "opinion"
export type FeedbackStatus = "open" | "in_progress" | "done" | "archived"
export type FeedbackSource = "help" | "admin"

export type FeedbackItem = {
  id: number
  kind: FeedbackKind
  title: string
  body: string
  status: FeedbackStatus
  source: FeedbackSource
  session_id: string | null
  view_path: string | null
  created_at: string
  updated_at: string
}

export type FeedbackListParams = {
  status?: FeedbackStatus
  kind?: FeedbackKind
  include_archived?: boolean
  limit?: number
}

export function listFeedback(params: FeedbackListParams = {}): Promise<FeedbackItem[]> {
  return api.get<FeedbackItem[]>("/feedback", params)
}

export function updateFeedback(
  id: number,
  body: { status?: FeedbackStatus; title?: string; body?: string; kind?: FeedbackKind },
): Promise<FeedbackItem> {
  return api.patch<FeedbackItem>(`/feedback/${id}`, body)
}
