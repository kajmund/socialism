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

export type ResearchNeedAssessment = {
  research_need_id: string
  sufficient: boolean
  supporting_evidence_ids: string[]
  missing_or_weak: string
  contradictions: string[]
  further_information: string | null
}

export type ResearchNeedOrigin = "initial" | "derived" | "global_completeness"

export type ResearchStopReason =
  | "sufficient"
  | "max_iterations"
  | "max_needs"
  | "no_novel_followups"
  | "max_completeness_passes"
  | "capability_unavailable"

export type RuntimeResearchNeed = {
  research_need_id: string
  question: string
  why_needed: string
  requested_by: string[]
  source_types: string[]
  domains: string[]
  modalities: string[]
  capabilities: string[]
  origin: ResearchNeedOrigin | string
  wave_number: number
  parent_research_need_id: string | null
  source_assessment_pass: number | null
  source_completeness_pass?: number | null
  source_gap: string
  question_key: string
}

export type MissingQuestion = {
  question: string
  why_needed: string
  rationale: string
  source_types: string[]
  unavailable_source_types?: string[]
  capability_gap?: string | null
}

export type ResearchCompleteness = {
  id: string
  attempt_id: string
  evidence_set_id: string
  completeness_pass: number
  result: "complete" | "incomplete" | string
  rationale: string
  missing_questions: MissingQuestion[]
  considered_evidence_ids: string[]
  considered_question_keys: string[]
  evidence_fingerprint: string
  question_fingerprint: string
  model_provider: string | null
  model_name: string | null
  model_version: string | null
  created_at: string
}

export type ResearchAssessment = {
  id: string
  attempt_id: string
  evidence_set_id: string
  assessment_pass: number
  result: "sufficient" | "insufficient" | string
  rationale: string
  need_assessments: ResearchNeedAssessment[]
  gaps: string[]
  contradictions: string[]
  considered_evidence_ids: string[]
  evidence_fingerprint: string
  model_provider: string | null
  model_name: string | null
  model_version: string | null
  created_at: string
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
  research_objective_snapshot?: Record<string, unknown> | null
  research_plan_snapshot: Record<string, unknown> | null
  evidence: EvidenceSummary | null
  assessment: ResearchAssessment | null
  assessments?: ResearchAssessment[]
  completeness?: ResearchCompleteness | null
  completeness_passes?: ResearchCompleteness[]
  research_wave?: number
  stop_reason?: ResearchStopReason | string | null
  runtime_needs?: RuntimeResearchNeed[]
  result: AttemptResult | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export type EvidenceQualityFlag = {
  code: string
  detail: string
}

export type EvidenceQuality = {
  id: string
  evidence_set_item_id: string
  original_evidence_id: string | null
  scoring_policy_version: string
  authority: string
  relevance: string
  currentness: string
  source_nature: string
  source_timestamp: string | null
  independence_key: string
  independent_source_count: number
  flags: EvidenceQualityFlag[]
  rationale: string
  declared_signals: Record<string, unknown>
  model_provider: string | null
  model_name: string | null
  model_version: string | null
  created_at: string
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
  quality?: EvidenceQuality | null
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

export type ResearchProgressEventType =
  | "question_running"
  | "question_completed"
  | "question_failed"
  | "objective_accepted"
  | "initial_plan_accepted"
  | "research_need_planned"
  | "follow_up_need_derived"
  | "global_need_derived"
  | "need_queued"
  | "need_running"
  | "need_completed"
  | "need_failed"
  | "evidence_found"
  | "evidence_not_found"
  | "evidence_error"
  | "local_assessment_persisted"
  | "global_completeness_persisted"
  | "capability_unavailable"
  | "research_frozen_ready"
  | "research_failed"

export type ResearchProgressEvent = {
  id: string
  attempt_id: string
  sequence: number
  event_type: ResearchProgressEventType | string
  payload: Record<string, unknown>
  occurred_at: string
}

export type ResearchProgressEventList = {
  attempt_id: string
  after_sequence: number
  events: ResearchProgressEvent[]
}

export function getResearchProgressEvents(
  attemptId: string,
  afterSequence = 0,
): Promise<ResearchProgressEventList> {
  const query = afterSequence > 0 ? `?after_sequence=${afterSequence}` : ""
  return api.get<ResearchProgressEventList>(
    `/execution/attempts/${attemptId}/progress-events${query}`,
  )
}

export type ResearchOverviewSource = {
  id: string
  status: string
  title: string | null
  excerpt: string | null
  locator: string | null
  source_url: string | null
  source_type: string
  provider: string | null
}

export type ResearchOverviewExpert = {
  id: string
  name: string
}

export type ResearchOverviewQuestion = {
  id: string
  question: string
  specific_question: string
  why_needed: string
  status: string
  raw_status: string
  outcome_reason: string | null
  origin: string
  depth: number
  child_attempt_id: string | null
  child_attempt_status: string | null
  dependency_ids: string[]
  raised_by: ResearchOverviewExpert[]
  assigned_to: ResearchOverviewExpert | null
  sources: ResearchOverviewSource[]
  assessment_result: string | null
  assessment_rationale: string | null
  completeness_result: string | null
  completeness_rationale: string | null
}

export type ResearchOverview = {
  run_id: string
  attempt_id: string
  attempt_status: string
  phase: "researching" | "completed" | "completed_with_gaps" | "not_needed"
  latest_sequence: number
  counts: {
    total: number
    answered: number
    running: number
    waiting: number
    insufficient: number
    unanswered: number
    failed: number
    blocked: number
  }
  questions: ResearchOverviewQuestion[]
}

export function getResearchOverview(attemptId: string): Promise<ResearchOverview> {
  return api.get<ResearchOverview>(
    `/execution/attempts/${attemptId}/research-overview`,
  )
}
