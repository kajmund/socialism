import { describe, expect, it } from "vitest"

import type { LatestWordJob, WordAction } from "./types"
import { finishedJobView, isActiveWordJobStatus, planReviewStart } from "./resume"

function job(overrides: Partial<LatestWordJob> = {}): LatestWordJob {
  return {
    job_id: "job_1",
    status: "pending",
    actions: [],
    ...overrides,
  }
}

function action(overrides: Partial<WordAction> = {}): WordAction {
  return {
    id: "wa_1",
    job_id: "job_1",
    action_type: "comment",
    content: "Text",
    word_artifact_id: null,
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

  it("blocks a new review while pending or unresolved remain", () => {
    expect(
      planReviewStart(
        job({
          status: "succeeded",
          actions: [action({ status: "pending" })],
        }),
      ),
    ).toEqual({ action: "blockUndecided" })
    expect(
      planReviewStart(
        job({
          status: "succeeded",
          actions: [action({ status: "unresolved" })],
        }),
      ),
    ).toEqual({ action: "blockUndecided" })
  })

  it("blocks a new review while applying is uncertain", () => {
    expect(
      planReviewStart(
        job({
          status: "succeeded",
          actions: [action({ status: "applying" })],
        }),
      ),
    ).toEqual({ action: "blockApplying" })
  })

  it("starts a new job when every action is applied or dismissed", () => {
    expect(
      planReviewStart(
        job({
          status: "succeeded",
          actions: [
            action({ status: "applied", word_artifact_id: "word-1" }),
            action({ id: "wa_2", status: "dismissed", word_artifact_id: null }),
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
  it("exposes pending unresolved applying and dismissed from a finished job", () => {
    expect(
      finishedJobView(
        job({
          status: "succeeded",
          actions: [
            action({ status: "applied", word_artifact_id: "word-1" }),
            action({ id: "wa_2", status: "pending" }),
            action({ id: "wa_3", status: "unresolved" }),
            action({ id: "wa_4", status: "applying" }),
            action({ id: "wa_5", status: "dismissed" }),
          ],
        }),
      ),
    ).toEqual({
      jobId: "job_1",
      phase: "done",
      error: "succeeded",
      actions: [
        action({ status: "applied", word_artifact_id: "word-1" }),
        action({ id: "wa_2", status: "pending" }),
        action({ id: "wa_3", status: "unresolved" }),
        action({ id: "wa_4", status: "applying" }),
        action({ id: "wa_5", status: "dismissed" }),
      ],
    })
  })

  it("marks a failed finished job without treating it as resume", () => {
    expect(finishedJobView(job({ status: "failed" }))).toEqual({
      jobId: "job_1",
      phase: "failed",
      error: "failed",
      actions: [],
    })
    expect(planReviewStart(job({ status: "failed" }))).toEqual({
      action: "startNew",
      resolveCommentIds: [],
    })
  })

  it("surfaces the backend job error on failed resume", () => {
    expect(
      finishedJobView(
        job({
          status: "failed",
          error: "WordCommentConvergence/json_invalid",
        }),
      ),
    ).toEqual({
      jobId: "job_1",
      phase: "failed",
      error: "WordCommentConvergence/json_invalid",
      actions: [],
    })
    expect(finishedJobView(job({ status: "failed", error: "   " }))).toEqual({
      jobId: "job_1",
      phase: "failed",
      error: "failed",
      actions: [],
    })
  })

  it("ignores live jobs and missing history", () => {
    expect(finishedJobView(job({ status: "running" }))).toBeNull()
    expect(finishedJobView(null)).toBeNull()
  })
})
