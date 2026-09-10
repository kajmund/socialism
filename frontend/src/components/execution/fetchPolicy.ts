import type { ExecutionAttempt } from "@/api/execution"
import { ApiError } from "@/lib/http"
import type { ExecutionLoadState } from "@/components/execution/ExecutionInspector"

export function shouldFetchEvidence(attempt: ExecutionAttempt): boolean {
  return attempt.evidence != null
}

export function shouldFetchResult(attempt: ExecutionAttempt): boolean {
  return attempt.result != null
}

export function loadStateFromError(err: unknown): ExecutionLoadState {
  if (err instanceof ApiError && err.status === 404) return "not_found"
  if (err instanceof ApiError && err.status === 403) return "forbidden"
  return "error"
}
