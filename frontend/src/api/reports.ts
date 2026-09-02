import { api, ApiError } from "@/lib/api"
import { env } from "@/lib/env"
import type { Locale } from "@/i18n"

export type ReportStatus = "pending" | "running" | "succeeded" | "failed"

export type OasisReportSource = {
  type?: "oasis"
  run_id: number
  attempt_id: string
  label?: string
}

export type DdReportSource = {
  type: "dd_session"
  session_id: string
  candidate_id: string
  label?: string
}

export type ExpertgranskningReportSource = {
  type: "expertgranskning_session"
  session_id: string
  label?: string
}

export type ReportSource = OasisReportSource | DdReportSource | ExpertgranskningReportSource

/** Legacy rows may still be `"full"`; new OASIS reports are `"quick"`. */
export type ReportMode = "full" | "quick" | "dd" | "expertgranskning"

export type Report = {
  id: string
  customer_id: number
  status: ReportStatus
  title: string
  locale: Locale
  mode: ReportMode
  sources: ReportSource[]
  html_path: string | null
  slots_path: string | null
  job_id: string | null
  error: string | null
  created_at: string
  finished_at: string | null
  updated_at: string
}

export type OasisReportCreate = {
  sources: Array<{ run_id: number; attempt_id: string }>
  title?: string
  locale?: Locale
  mode?: "quick"
}

export type DdReportCreate = {
  sources: Array<{
    type: "dd_session"
    session_id: string
    candidate_id: string
  }>
  title?: string
  locale?: Locale
  mode?: "dd"
}

export type ExpertgranskningReportCreate = {
  sources: Array<{
    type: "expertgranskning_session"
    session_id: string
  }>
  title?: string
  locale?: Locale
  mode?: "expertgranskning"
}

export type ReportCreate = OasisReportCreate | DdReportCreate | ExpertgranskningReportCreate

export function createReport(body: OasisReportCreate): Promise<Report> {
  return api.post<Report>("/reports", body)
}

export function createDdReport(body: {
  session_id: string
  candidate_id: string
  title?: string
  locale?: Locale
}): Promise<Report> {
  return api.post<Report>("/reports", {
    mode: "dd",
    title: body.title,
    locale: body.locale,
    sources: [
      {
        type: "dd_session",
        session_id: body.session_id,
        candidate_id: body.candidate_id,
      },
    ],
  })
}

export function createExpertgranskningReport(body: {
  session_id: string
  title?: string
  locale?: Locale
}): Promise<Report> {
  return api.post<Report>("/reports", {
    mode: "expertgranskning",
    title: body.title,
    locale: body.locale,
    sources: [
      {
        type: "expertgranskning_session",
        session_id: body.session_id,
      },
    ],
  })
}

export function listReports(params?: {
  status?: ReportStatus
  limit?: number
}): Promise<Report[]> {
  return api.get<Report[]>("/reports", params)
}

export function getReport(id: string): Promise<Report> {
  return api.get<Report>(`/reports/${id}`)
}

export function deleteReport(id: string): Promise<void> {
  return api.delete(`/reports/${id}`)
}

export type ReportBulkDeleteResult = {
  deleted_ids: string[]
}

export function bulkDeleteReports(ids: string[]): Promise<ReportBulkDeleteResult> {
  return api.post<ReportBulkDeleteResult>("/reports/bulk-delete", { ids })
}

export function reportHtmlUrl(id: string): string {
  const base = env.apiBaseUrl.replace(/\/$/, "")
  return `${base}/reports/${id}/html`
}

export async function getReportHtml(id: string): Promise<string> {
  const body = await api.get<unknown>(`/reports/${id}/html`)
  if (typeof body !== "string" || !body.trim()) {
    throw new ApiError("Report HTML missing")
  }
  return body
}

export type RecommendationSnapshot = {
  score: number
  action: string
  recommended_arm: string | null
  verdict_key: string
}

export type VerdictCalibration = {
  report_id: string
  matches: boolean | null
  note: string | null
  recommendation: RecommendationSnapshot | null
  updated_at: string | null
}

export type VerdictCalibrationWrite = {
  matches: boolean
  note?: string | null
}

export function getVerdictCalibration(reportId: string): Promise<VerdictCalibration> {
  return api.get<VerdictCalibration>(`/reports/${reportId}/verdict-calibration`)
}

export function saveVerdictCalibration(
  reportId: string,
  body: VerdictCalibrationWrite,
): Promise<VerdictCalibration> {
  return api.post<VerdictCalibration>(`/reports/${reportId}/verdict-calibration`, body)
}
