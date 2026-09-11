import { describe, expect, it } from "vitest"

import type { LatestWordJob, ReviewResult } from "./types"
import { isActiveWordJobStatus, planReviewStart } from "./resume"

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
