import { newReviewBlock, wordArtifactIds } from "@/lib/actionQueue"
import type { LatestWordJob, WordAction } from "@/lib/types"

export function isActiveWordJobStatus(status: string): boolean {
  return status === "pending" || status === "running"
}

export type ReviewStartPlan =
  | { action: "resume"; jobId: string }
  | { action: "startNew"; resolveCommentIds: string[] }
  | { action: "blockUndecided" }
  | { action: "blockApplying" }

export type FinishedJobView = {
  jobId: string
  phase: "done" | "failed"
  error: string
  actions: WordAction[]
}

export function planReviewStart(latest: LatestWordJob | null): ReviewStartPlan {
  if (latest && isActiveWordJobStatus(latest.status)) {
    return { action: "resume", jobId: latest.job_id }
  }
  const block = newReviewBlock(latest?.actions ?? [])
  switch (block) {
    case "applying":
      return { action: "blockApplying" }
    case "undecided":
      return { action: "blockUndecided" }
    case null:
      return {
        action: "startNew",
        resolveCommentIds: wordArtifactIds(latest?.actions ?? []),
      }
    default: {
      const _exhaustive: never = block
      return _exhaustive
    }
  }
}

export function finishedJobView(latest: LatestWordJob | null): FinishedJobView | null {
  if (!latest || isActiveWordJobStatus(latest.status)) return null
  const error = (latest.error ?? "").trim()
  return {
    jobId: latest.job_id,
    phase: latest.status === "failed" ? "failed" : "done",
    error: error || latest.status,
    actions: latest.actions,
  }
}
