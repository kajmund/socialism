import { describe, expect, it } from "vitest"
import type { Job } from "@/api/jobs"
import {
  isFinishedResearchJob,
  isOngoingResearchJob,
  isResumableResearchJob,
  isRerunnableResearchJob,
  listSmeResearchJobs,
  researchAttemptId,
} from "@/products/sme/smeResearchJobs"

function job(partial: Partial<Job> & Pick<Job, "id" | "status" | "kind">): Job {
  return {
    customer_id: 1,
    label: partial.label ?? "Research",
    request: {},
    result: partial.result ?? { attempt_id: "attempt-1" },
    error: null,
    created_at: partial.created_at ?? "2026-01-01T10:00:00Z",
    started_at: null,
    finished_at: null,
    updated_at: partial.updated_at ?? "2026-01-01T10:00:00Z",
    ...partial,
  }
}

describe("smeResearchJobs", () => {
  it("lists research jobs without attempt_id while pending", () => {
    const rows = listSmeResearchJobs([
      job({
        id: "1",
        kind: "expert_chat_research",
        status: "running",
        result: null,
      }),
    ])
    expect(rows.ongoing).toHaveLength(1)
    expect(researchAttemptId(rows.ongoing[0])).toBeNull()
  })

  it("splits ongoing and finished research jobs", () => {
    const rows = listSmeResearchJobs([
      job({ id: "1", kind: "expert_chat_research", status: "running" }),
      job({ id: "2", kind: "expert_chat_research", status: "succeeded" }),
      job({ id: "3", kind: "report_generate", status: "running" }),
    ])
    expect(rows.ongoing).toHaveLength(1)
    expect(rows.finished).toHaveLength(1)
    expect(researchAttemptId(rows.ongoing[0])).toBe("attempt-1")
  })

  it("classifies job status", () => {
    expect(isOngoingResearchJob(job({ id: "1", kind: "expert_chat_research", status: "pending" }))).toBe(true)
    expect(isFinishedResearchJob(job({ id: "2", kind: "expert_chat_research", status: "failed" }))).toBe(true)
    expect(isResumableResearchJob(job({ id: "1", kind: "expert_chat_research", status: "failed" }))).toBe(true)
    expect(isResumableResearchJob(job({ id: "2", kind: "expert_chat_research", status: "running" }))).toBe(false)
    expect(isResumableResearchJob(job({ id: "3", kind: "dd_research", status: "failed" }))).toBe(false)
    expect(isRerunnableResearchJob(job({ id: "4", kind: "expert_chat_research", status: "succeeded" }))).toBe(true)
    expect(isRerunnableResearchJob(job({ id: "5", kind: "expert_chat_research", status: "failed" }))).toBe(true)
    expect(isRerunnableResearchJob(job({ id: "6", kind: "expert_chat_research", status: "running" }))).toBe(false)
    expect(isRerunnableResearchJob(job({ id: "7", kind: "dd_research", status: "succeeded" }))).toBe(false)
  })
})
