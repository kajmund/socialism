import type { Job } from "@/api/jobs"

const RESEARCH_KINDS = new Set([
  "dd_research",
  "rattsunderlag_research",
  "expert_chat_research",
])

export function isResearchJob(job: Job): boolean {
  return RESEARCH_KINDS.has(job.kind)
}

export function researchAttemptId(job: Job): string | null {
  if (typeof job.result?.execution_attempt_id === "string") {
    return job.result.execution_attempt_id
  }
  if (typeof job.result?.attempt_id === "string") {
    return job.result.attempt_id
  }
  return null
}

export function isOngoingResearchJob(job: Job): boolean {
  return job.status === "pending" || job.status === "running"
}

export function isFinishedResearchJob(job: Job): boolean {
  return job.status === "succeeded" || job.status === "failed"
}

export function isResumableResearchJob(job: Job): boolean {
  return job.kind === "expert_chat_research" && job.status === "failed"
}

export function isRerunnableResearchJob(job: Job): boolean {
  return job.kind === "expert_chat_research" && isFinishedResearchJob(job)
}

export function listSmeResearchJobs(jobs: Job[]): {
  ongoing: Job[]
  finished: Job[]
} {
  const research = jobs.filter(isResearchJob)
  research.sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )
  return {
    ongoing: research.filter(isOngoingResearchJob),
    finished: research.filter(isFinishedResearchJob),
  }
}
