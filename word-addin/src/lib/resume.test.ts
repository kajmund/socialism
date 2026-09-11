import { describe, expect, it } from "vitest"

import type { LatestWordJob, ReviewResult } from "./types"
import { finishedJobView, isActiveWordJobStatus, planReviewStart } from "./resume"

function job(overrides: Partial<LatestWordJob> = {}): LatestWordJob {
  return {
    job_id: "job_1",
    status: "pending",
    results: [],
    ...overrides,
  }
}

function result(overrides: Partial<ReviewResult> = {}): ReviewResult {
  return {
    id: "egr_1",
    job_id: "job_1",
    paragraph_index: 1,
    expert_id: "slot_1",
    expert_namn: "Anna",
    kommentar: "Text",
    is_heading_suggestion: false,
    comment_id: "word-1",
    status: "applied",
    ...overrides,
  }
}

describe("isActiveWordJobStatus", () => {
  it("treats pending and running as live", () => {
    expect(isActiveWordJobStatus("pending")).toBe(true)
    expect(isActiveWordJobStatus("running")).toBe(true)
    expect(isActiveWordJobStatus("succeeded")).toBe(false)
    expect(isActiveWordJobStatus("failed")).toBe(false)
  })
})

describe("planReviewStart", () => {
  it("resumes a pending or running job", () => {
    expect(planReviewStart(job({ status: "pending" }))).toEqual({
      action: "resume",
      jobId: "job_1",
    })
    expect(planReviewStart(job({ status: "running", job_id: "job_live" }))).toEqual({
      action: "resume",
      jobId: "job_live",
    })
  })

  it("starts a new job after a finished run and lists comments to resolve", () => {
    expect(
      planReviewStart(
        job({
          status: "succeeded",
          results: [
            result({ comment_id: "word-1" }),
            result({ id: "egr_2", comment_id: null }),
          ],
        }),
      ),
    ).toEqual({ action: "startNew", resolveCommentIds: ["word-1"] })
  })

  it("starts a new job when there is no history", () => {
    expect(planReviewStart(null)).toEqual({
      action: "startNew",
      resolveCommentIds: [],
    })
  })
})

describe("finishedJobView", () => {
  it("exposes applying and unresolved rows from a finished job", () => {
    expect(
      finishedJobView(
        job({
          status: "succeeded",
          results: [
            result({ status: "applied", comment_id: "word-1" }),
            result({ id: "egr_2", status: "applying", comment_id: null }),
            result({ id: "egr_3", status: "unresolved", comment_id: null }),
          ],
        }),
      ),
    ).toEqual({
      jobId: "job_1",
      phase: "done",
      results: [
        result({ status: "applied", comment_id: "word-1" }),
        result({ id: "egr_2", status: "applying", comment_id: null }),
        result({ id: "egr_3", status: "unresolved", comment_id: null }),
      ],
    })
  })

  it("marks a failed finished job without treating it as resume", () => {
    expect(finishedJobView(job({ status: "failed" }))).toEqual({
      jobId: "job_1",
      phase: "failed",
      results: [],
    })
    expect(planReviewStart(job({ status: "failed" }))).toEqual({
      action: "startNew",
      resolveCommentIds: [],
    })
  })

  it("ignores live jobs and missing history", () => {
    expect(finishedJobView(job({ status: "running" }))).toBeNull()
    expect(finishedJobView(null)).toBeNull()
  })
})
