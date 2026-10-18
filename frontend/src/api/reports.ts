import { api, ApiError } from "@/lib/api"
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

export type RattsunderlagReportSource = {
  type: "rattsunderlag"
  session_id: string
  label?: string
}

export type ReportSource =
  | OasisReportSource
  | DdReportSource
  | ExpertgranskningReportSource
  | RattsunderlagReportSource

/** Legacy rows may still be `"full"`; new OASIS reports are `"quick"`. */
export type ReportMode = "full" | "quick" | "dd" | "expertgranskning" | "rattsunderlag"

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
  has_source_pdf: boolean
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

export async function getReportHtml(id: string): Promise<string> {
  const body = await api.get<unknown>(`/reports/${id}/html`)
  if (typeof body !== "string" || !body.trim()) {
    throw new ApiError("Report HTML missing")
  }
  return body
}

export function getReportSourcePdf(id: string): Promise<Blob> {
  return api.getBlob(`/reports/${id}/source-pdf`)
}
