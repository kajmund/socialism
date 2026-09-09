import { api } from "@/lib/api"
import type { Job } from "@/api/jobs"

export type RattsunderlagLocale = "sv" | "en"
export type SourcingStatus = "complete" | "partial" | "no_sources_found"

export type RattsunderlagSessionStatus =
  | "draft"
  | "pending"
  | "running"
  | "succeeded"
  | "failed"

export type LagtextRef = {
  sfs_id: string
  rubrik: string
  utdrag: string
  url?: string | null
}

export type PraxisRef = {
  referens: string
  instans: string
  utdrag: string
  url?: string | null
}

export type ForarbeteRef = {
  referens: string
  titel: string
  utdrag: string
  url?: string | null
}

export type RattsunderlagResult = {
  fraga: string
  lagtext: LagtextRef[]
  praxis: PraxisRef[]
  forarbeten: ForarbeteRef[]
  sammanfattning: string
  sourcing_status: SourcingStatus
}

export type RattsunderlagJob = Job & {
  result: Job["result"] & {
    result?: RattsunderlagResult
    underlag_id?: string
    report_id?: string
    sourcing_status?: SourcingStatus
  }
}

export type RattsunderlagSession = {
  id: string
  title: string
  fraga: string
  locale: RattsunderlagLocale
  status: RattsunderlagSessionStatus
  job_id: string | null
  report_id: string | null
  underlag_id: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export type RattsunderlagSessionSummary = {
  id: string
  title: string
  topic: string
  status: RattsunderlagSessionStatus
  job_id: string | null
  report_id: string | null
  created_at: string
  updated_at: string
}

export type RattsunderlagSessionWrite = {
  fraga?: string
  title?: string
  locale?: RattsunderlagLocale
}

export function listRattsunderlagSessions(): Promise<RattsunderlagSessionSummary[]> {
  return api.get<RattsunderlagSessionSummary[]>("/rattsunderlag/sessions")
}

export function createRattsunderlagSession(
  body: RattsunderlagSessionWrite = {},
): Promise<RattsunderlagSession> {
  return api.post<RattsunderlagSession>("/rattsunderlag/sessions", body)
}

export function getRattsunderlagSession(id: string): Promise<RattsunderlagSession> {
  return api.get<RattsunderlagSession>(`/rattsunderlag/sessions/${id}`)
}

export function updateRattsunderlagSession(
  id: string,
  body: RattsunderlagSessionWrite,
): Promise<RattsunderlagSession> {
  return api.patch<RattsunderlagSession>(`/rattsunderlag/sessions/${id}`, body)
}

export function deleteRattsunderlagSession(id: string): Promise<void> {
  return api.delete(`/rattsunderlag/sessions/${id}`)
}

export function runRattsunderlagSession(
  id: string,
): Promise<{ job_id: string; session_id: string }> {
  return api.post<{ job_id: string; session_id: string }>(`/rattsunderlag/sessions/${id}/run`)
}

export function getRattsunderlagResearch(jobId: string): Promise<RattsunderlagJob> {
  return api.get<RattsunderlagJob>(`/rattsunderlag/research/${jobId}`)
}

export function resultFromJob(job: RattsunderlagJob): RattsunderlagResult | null {
  const payload = job.result?.result
  if (!payload || typeof payload !== "object") return null
  if (typeof payload.fraga !== "string") return null
  return payload
}

export function rattsunderlagHref(job: { id: string; request?: Record<string, unknown> }): string {
  const sessionId =
    typeof job.request?.session_id === "string" ? job.request.session_id : null
  return `/rattsunderlag/${sessionId ?? job.id}?tab=results`
}
