import { describe, expect, it } from "vitest"
import type { Job } from "@/api/jobs"
import type { Report } from "@/api/reports"
import { inferExpertgranskningReportId } from "@/lib/expertgranskningReport"

const SESSION = "ps_rerun"

function report(id: string, createdAt: string): Report {
  return {
    id,
    customer_id: 1,
    status: "succeeded",
    title: "Test",
    locale: "sv",
    mode: "expertgranskning",
    sources: [{ type: "expertgranskning_session", session_id: SESSION }],
    html_path: null,
    slots_path: null,
    job_id: null,
    error: null,
    created_at: createdAt,
    finished_at: createdAt,
    updated_at: createdAt,
  }
}

function panelJob(
  overrides: Partial<Job> & Pick<Job, "id" | "created_at" | "status">,
): Job {
  return {
    id: overrides.id,
    customer_id: 1,
    kind: "panel_session_run",
    status: overrides.status,
    label: "Panel",
    request: { session_id: SESSION },
    result: null,
    error: null,
    created_at: overrides.created_at,
    started_at: overrides.started_at ?? null,
    finished_at: overrides.finished_at ?? null,
    updated_at: overrides.updated_at ?? overrides.created_at,
    ...overrides,
  }
}

describe("inferExpertgranskningReportId", () => {
  it("returns the newest report when no panel job is known", () => {
    const reports = [
      report("rpt_old", "2026-09-01T10:00:00Z"),
      report("rpt_new", "2026-09-02T10:00:00Z"),
    ]
    expect(inferExpertgranskningReportId(reports, SESSION, undefined)).toBe("rpt_new")
  })

  it("ignores reports from before the current panel run", () => {
    const reports = [
      report("rpt_old", "2026-09-01T10:00:00Z"),
      report("rpt_new", "2026-09-03T12:00:00Z"),
    ]
    const job = panelJob({
      id: "job_rerun",
      created_at: "2026-09-03T11:00:00Z",
      status: "succeeded",
    })
    expect(inferExpertgranskningReportId(reports, SESSION, job)).toBe("rpt_new")
  })

  it("returns undefined while a rerun succeeded but no new report exists yet", () => {
    const reports = [report("rpt_old", "2026-09-01T10:00:00Z")]
    const job = panelJob({
      id: "job_rerun",
      created_at: "2026-09-03T11:00:00Z",
      status: "succeeded",
    })
    expect(inferExpertgranskningReportId(reports, SESSION, job)).toBeUndefined()
  })

  it("returns undefined while the panel job is still running", () => {
    const reports = [report("rpt_old", "2026-09-01T10:00:00Z")]
    const job = panelJob({
      id: "job_rerun",
      created_at: "2026-09-03T11:00:00Z",
      status: "running",
    })
    expect(inferExpertgranskningReportId(reports, SESSION, job)).toBeUndefined()
  })
})
