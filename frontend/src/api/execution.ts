import { api } from "@/lib/api"

export type AttemptStatus =
  | "created"
  | "researching"
  | "ready"
  | "running"
  | "completed"
  | "failed"

export type EvidenceItemStatus = "found" | "not_found" | "error"

export type EvidenceSetStatus = "building" | "frozen" | "failed"

export type ExecutionRun = {
  id: string
  customer_id: number
  module: string
  title: string
  context: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type EvidenceSummary = {
  evidence_set_id: string
  status: string
  found_count: number
  not_found_count: number
  error_count: number
}

export type AttemptResult = {
  id: string
  result_type: string
  schema_version: string
  payload: Record<string, unknown>
  evidence_refs: Record<string, unknown>
  panel_session_id: string | null
  created_at: string
}

export type ExecutionAttempt = {
  id: string
  run_id: string
  parent_attempt_id: string | null
  attempt_type: string
  status: AttemptStatus | string
  configuration_snapshot: Record<string, unknown>
  input_snapshot: Record<string, unknown>
  research_plan_snapshot: Record<string, unknown> | null
  evidence: EvidenceSummary | null
  result: AttemptResult | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export type EvidenceSetItem = {
  id: string
  evidence_set_id: string
  research_need_id: string | null
  original_evidence_id: string | null
  ordinal: number
  source_type: string
  status: EvidenceItemStatus | string
  title: string | null
  excerpt: string | null
  locator: string | null
  source_id: string | null
  source_url: string | null
  provider: string | null
  score: number | null
  provenance: Record<string, unknown>
  retrieved_at: string
  content_hash: string
}

export type EvidenceSet = {
  id: string
  run_id: string
  created_from_attempt_id: string | null
  status: EvidenceSetStatus | string
  created_at: string
  frozen_at: string | null
  items: EvidenceSetItem[]
}

export function getExecutionRun(runId: string): Promise<ExecutionRun> {
  return api.get<ExecutionRun>(`/execution/runs/${runId}`)
}

export function listExecutionAttempts(runId: string): Promise<ExecutionAttempt[]> {
  return api.get<ExecutionAttempt[]>(`/execution/runs/${runId}/attempts`)
}

export function getExecutionAttempt(attemptId: string): Promise<ExecutionAttempt> {
  return api.get<ExecutionAttempt>(`/execution/attempts/${attemptId}`)
}

export function getExecutionEvidence(attemptId: string): Promise<EvidenceSet> {
  return api.get<EvidenceSet>(`/execution/attempts/${attemptId}/evidence`)
}

export function getExecutionResult(attemptId: string): Promise<AttemptResult> {
  return api.get<AttemptResult>(`/execution/attempts/${attemptId}/result`)
}
