import type { Job } from "@/api/jobs"
import type { Report } from "@/api/reports"

export function sessionReports(reports: Report[], sessionId: string): Report[] {
  return reports.filter((row) =>
    row.sources.some(
      (src) =>
        src.type === "expertgranskning_session" && src.session_id === sessionId,
    ),
  )
}

function newestReportId(rows: Report[]): string | undefined {
  if (rows.length === 0) return undefined
  return [...rows].sort((a, b) =>
    (b.created_at ?? "") > (a.created_at ?? "") ? 1 : -1,
  )[0]?.id
}

/** Pick the report for the current panel run, ignoring pre-rerun reports. */
export function inferExpertgranskningReportId(
  reports: Report[],
  sessionId: string | null,
  panelJob: Job | undefined,
): string | undefined {
  if (!sessionId) return undefined
  const candidates = sessionReports(reports, sessionId)
  if (candidates.length === 0) return undefined

  if (!panelJob?.created_at) {
    return newestReportId(candidates)
  }

  const runStarted = new Date(panelJob.created_at).getTime()
  const afterRun = candidates.filter(
    (row) => row.created_at && new Date(row.created_at).getTime() >= runStarted,
  )

  if (afterRun.length > 0) {
    return newestReportId(afterRun)
  }

  if (
    panelJob.status === "pending" ||
    panelJob.status === "running" ||
    panelJob.status === "succeeded"
  ) {
    return undefined
  }

  return newestReportId(candidates)
}
