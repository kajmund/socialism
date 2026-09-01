import { api } from "@/lib/api"
import type { DdCandidateCompany } from "@/api/dd"

export type PanelSessionStatus = "draft" | "pending" | "running" | "succeeded" | "failed"

export type PanelExpertSlot = {
  slot_id: string
  label: string
  profile: string
}

export type PanelSessionConfig = {
  protocol: "generic_panel" | "dd_panel"
  topic: string
  brief: string
  expert_slots: PanelExpertSlot[]
  max_rounds: number
  campaign_id: number | null
  candidate: DdCandidateCompany | null
  candidate_id: string | null
  expert_role_keys: string[]
}

export type PanelSession = {
  id: string
  protocol: "generic_panel" | "dd_panel"
  status: PanelSessionStatus
  config: PanelSessionConfig
  panel_id: number | null
  project_id: number | null
  campaign_id: number | null
  job_id: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export function createPanelSession(body: {
  config: Omit<PanelSessionConfig, "expert_slots"> & { expert_slots?: PanelExpertSlot[] }
  panel_id?: number | null
  project_id?: number | null
}): Promise<PanelSession> {
  return api.post<PanelSession>("/panel/sessions", body)
}

export function createDdPanelSession(
  campaignId: number,
  body: {
    campaign_id: number
    candidate_id: string
    expert_role_keys?: string[]
  },
): Promise<PanelSession> {
  return api.post<PanelSession>(`/dd/campaigns/${campaignId}/panel-sessions`, body)
}

export function getPanelSession(sessionId: string): Promise<PanelSession> {
  return api.get<PanelSession>(`/panel/sessions/${sessionId}`)
}

export function runPanelSession(sessionId: string): Promise<{ job_id: string; session_id: string }> {
  return api.post<{ job_id: string; session_id: string }>(`/panel/sessions/${sessionId}/run`, {})
}
