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
  project_id: number | null
  job_id: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export type ExpertgranskningSessionCreate = {
  document_text: string
  panel_id: number
  title?: string
  project_id?: number
}

export function createExpertgranskningSession(
  body: ExpertgranskningSessionCreate,
): Promise<ExpertgranskningSession> {
  return api.post<ExpertgranskningSession>("/expertgranskning/sessions", body)
}

export function getExpertgranskningSession(id: string): Promise<ExpertgranskningSession> {
  return api.get<ExpertgranskningSession>(`/expertgranskning/sessions/${id}`)
}

export function runExpertgranskningSession(
  id: string,
): Promise<{ job_id: string; session_id: string }> {
  return api.post<{ job_id: string; session_id: string }>(
    `/expertgranskning/sessions/${id}/run`,
  )
}
