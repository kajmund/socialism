import type { ResearchOverviewQuestion } from "@/api/execution"

export function blockingDependencyCount(question: Pick<ResearchOverviewQuestion, "status" | "blocking_dependency_ids">): number {
  if (question.status !== "waiting" && question.status !== "blocked") return 0
  return question.blocking_dependency_ids?.length ?? 0
}
