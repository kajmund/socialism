import { api, ApiError } from "@/lib/api"
import { env } from "@/lib/env"
import type { Locale } from "@/i18n"

export type ReportStatus = "pending" | "running" | "succeeded" | "failed"

export type ReportSource = {
  run_id: number
  attempt_id: string
  label?: string
}

export type ReportMode = "full" | "quick"

export type Report = {
  id: string
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

export type ReportCreate = {
  sources: Array<{ run_id: number; attempt_id: string }>
  title?: string
  locale?: Locale
  mode?: ReportMode
}

export function createReport(body: ReportCreate): Promise<Report> {
  return api.post<Report>("/reports", body)
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
