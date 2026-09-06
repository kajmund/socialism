import { api } from "@/lib/api"

export type ExpertgranskningSessionStatus =
  | "draft"
  | "pending"
  | "running"
  | "succeeded"
  | "failed"

export type ExpertgranskningSession = {
  id: string
  protocol: string
  status: ExpertgranskningSessionStatus
  module: string
  topic: string
  document_text: string
  panel_id: number | null
  panel_name: string | null
  project_id: number | null
  job_id: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export type ExpertgranskningSessionSummary = {
  id: string
  topic: string
  status: ExpertgranskningSessionStatus
  panel_id: number | null
  panel_name: string | null
  job_id: string | null
  created_at: string
  updated_at: string
}

export type ExpertgranskningSessionCreate = {
  document_text?: string
  panel_id?: number | null
  title?: string
  project_id?: number
}

export type ExpertgranskningSessionUpdate = {
  document_text?: string
  panel_id?: number | null
  title?: string
  project_id?: number
  clear_panel?: boolean
}

export function listExpertgranskningSessions(): Promise<ExpertgranskningSessionSummary[]> {
  return api.get<ExpertgranskningSessionSummary[]>("/expertgranskning/sessions")
}

export function createExpertgranskningSession(
  body: ExpertgranskningSessionCreate = {},
): Promise<ExpertgranskningSession> {
  return api.post<ExpertgranskningSession>("/expertgranskning/sessions", body)
}

export function getExpertgranskningSession(id: string): Promise<ExpertgranskningSession> {
  return api.get<ExpertgranskningSession>(`/expertgranskning/sessions/${id}`)
}

export function updateExpertgranskningSession(
  id: string,
  body: ExpertgranskningSessionUpdate,
): Promise<ExpertgranskningSession> {
  return api.patch<ExpertgranskningSession>(`/expertgranskning/sessions/${id}`, body)
}

export function deleteExpertgranskningSession(id: string): Promise<void> {
  return api.delete(`/expertgranskning/sessions/${id}`)
}

export function runExpertgranskningSession(
  id: string,
): Promise<{ job_id: string; session_id: string }> {
  return api.post<{ job_id: string; session_id: string }>(
    `/expertgranskning/sessions/${id}/run`,
  )
}
