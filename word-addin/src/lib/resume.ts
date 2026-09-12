import type { LatestWordJob, WordAction } from "@/lib/types"

export function isActiveWordJobStatus(status: string): boolean {
  return status === "pending" || status === "running"
}

export type ReviewStartPlan =
  | { action: "resume"; jobId: string }
  | { action: "startNew"; resolveCommentIds: string[] }

export type FinishedJobView = {
  jobId: string
  phase: "done" | "failed"
  actions: WordAction[]
}

export function planReviewStart(latest: LatestWordJob | null): ReviewStartPlan {
  if (latest && isActiveWordJobStatus(latest.status)) {
    return { action: "resume", jobId: latest.job_id }
  }
  return {
    action: "startNew",
    resolveCommentIds: (latest?.actions ?? [])
      .map((row) => row.word_artifact_id)
      .filter((id): id is string => typeof id === "string" && id.length > 0),
  }
}

export function finishedJobView(latest: LatestWordJob | null): FinishedJobView | null {
  if (!latest || isActiveWordJobStatus(latest.status)) return null
  return {
    jobId: latest.job_id,
    phase: latest.status === "failed" ? "failed" : "done",
    actions: latest.actions,
  }
}
