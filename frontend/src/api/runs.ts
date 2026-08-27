import { api } from "@/lib/api"
import { OS_DEFAULT_PROJECT_ID } from "@/lib/scoping"
import type {
  BranchState,
  OasisRunOptions,
  OasisRunResults,
  RunPopulationOption,
  RunStatus,
  RunSummary,
  Tick,
} from "@/data/runs-types"

export type RunDetail = RunSummary & {
  population_id: number
  start_date: string | null
  main_ticks: Tick[]
  branch: BranchState | null
  oasis_options: OasisRunOptions
  results: OasisRunResults | null
  job_id?: string | null
}

export type RunWrite = {
  name: string
  population_id: number
  start_date?: string | null
  status?: RunStatus
  main_ticks?: Tick[]
  branch?: BranchState | null
  oasis_options?: OasisRunOptions
}

export type RunUpdate = {
  name?: string
  population_id?: number
  start_date?: string | null
  status?: RunStatus
  main_ticks?: Tick[]
  branch?: BranchState | null
  oasis_options?: OasisRunOptions
}

export function listRuns(params?: {
  q?: string
  status?: string
  project_id?: number
}): Promise<RunSummary[]> {
  return api.get<RunSummary[]>("/runs", {
    ...params,
    project_id: params?.project_id ?? OS_DEFAULT_PROJECT_ID,
  })
}

export function listRunPopulations(): Promise<RunPopulationOption[]> {
  return api.get<RunPopulationOption[]>("/runs/populations")
}

export function getRun(id: number): Promise<RunDetail> {
  return api.get<RunDetail>(`/runs/${id}`)
}

export function createRun(body: RunWrite): Promise<RunDetail> {
  return api.post<RunDetail>("/runs", body)
}

export function updateRun(id: number, body: RunUpdate): Promise<RunDetail> {
  return api.put<RunDetail>(`/runs/${id}`, body)
}

export function startRun(id: number): Promise<RunDetail> {
  return api.post<RunDetail>(`/runs/${id}/start`)
}

export function duplicateRun(id: number): Promise<RunDetail> {
  return api.post<RunDetail>(`/runs/${id}/duplicate`)
}

export function deleteRun(id: number): Promise<void> {
  return api.delete(`/runs/${id}`)
}

export async function deleteRunResultAttempt(
  runId: number,
  attemptId: string,
): Promise<RunDetail> {
  await api.delete(
    `/runs/${runId}/results/attempts/${encodeURIComponent(attemptId)}`,
  )
  return getRun(runId)
}

export type TopicStatus = "on_topic" | "drifted"

export type RunTaggableTextRow = {
  source_type: "comment" | "tick_interview" | "posthoc_interview"
  source_ref: Record<string, unknown>
  text: string
  meta: Record<string, unknown>
  tone_labels: string[]
  style_labels: string[]
  tone_predicted?: string | null
  style_predicted?: string | null
  tone_pmf?: Record<string, number> | null
  style_pmf?: Record<string, number> | null
  topic_status?: TopicStatus | null
}

export type RunMisclassificationFlagCreate = {
  text: string
  predicted_label: string
  expected_label: string
  kind: "tone" | "style"
  source_type: RunTaggableTextRow["source_type"]
  source_ref: Record<string, unknown>
  attempt_id: string
  variant_id: string
  locale?: "sv" | "en"
}

export type RunMisclassificationFlag = {
  id: number
  anchor_set_id: number
  kind: "tone" | "style"
  text: string
  predicted_label: string
  expected_label: string
  source_type: RunTaggableTextRow["source_type"]
  source_ref: Record<string, unknown>
  source_run_id: number | null
  source_attempt_id: string | null
  source_variant_id: string | null
  status: "open" | "dismissed" | "resolved"
  pool_item_id: number | null
  created_at: string
  resolved_at: string | null
}

export type RunTaggableTextsResponse = {
  run_id: number
  attempt_id: string
  variant_id: string
  anchor_context: {
    locale: string
    tone: { id: number; name: string; kind: string; labels: string[]; pool_revision: number }
    style: { id: number; name: string; kind: string; labels: string[]; pool_revision: number }
  }
  rows: RunTaggableTextRow[]
  post_topic_status?: Record<number, TopicStatus>
}

export function fetchRunTaggableTexts(
  runId: number,
  params: { attemptId: string; variantId: string; locale: string },
): Promise<RunTaggableTextsResponse> {
  return api.get<RunTaggableTextsResponse>(`/runs/${runId}/taggable-texts`, {
    attempt_id: params.attemptId,
    variant_id: params.variantId,
    locale: params.locale,
  })
}

export function addRunAnchorPoolItems(
  runId: number,
  body: {
    text: string
    source_type: RunTaggableTextRow["source_type"]
    source_ref: Record<string, unknown>
    attempt_id: string
    variant_id: string
    tone_label?: string | null
    style_label?: string | null
    add_to_calibration?: boolean
    locale?: string
  },
): Promise<{ created: Array<{ kind: string; id: number; label: string }> }> {
  return api.post(`/runs/${runId}/anchor-pool`, body)
}

export function createRunMisclassificationFlag(
  runId: number,
  body: RunMisclassificationFlagCreate,
): Promise<RunMisclassificationFlag> {
  return api.post<RunMisclassificationFlag>(
    `/runs/${runId}/misclassification-flags`,
    body,
  )
}

export type RunInterviewMessage = {
  id: number
  mode: "interview" | "character"
  role: "user" | "assistant"
  content: string
  created_at: string
  run_id?: number | null
  attempt_id?: string | null
  variant_id?: string | null
  through_tick_index?: number | null
  asked_by?: "doctor" | "human" | null
}

function interviewPath(
  runId: number,
  attemptId: string,
  variantId: string,
  personaId: string,
): string {
  return (
    `/runs/${runId}/attempts/${encodeURIComponent(attemptId)}` +
    `/variants/${encodeURIComponent(variantId)}` +
    `/personas/${encodeURIComponent(personaId)}/interview`
  )
}

export function listRunPersonaInterviewMessages(
  runId: number,
  attemptId: string,
  variantId: string,
  personaId: string,
  throughTickIndex: number,
): Promise<RunInterviewMessage[]> {
  return api.get<RunInterviewMessage[]>(
    interviewPath(runId, attemptId, variantId, personaId),
    { through_tick_index: throughTickIndex },
  )
}

export function runPersonaInterview(
  runId: number,
  attemptId: string,
  variantId: string,
  personaId: string,
  body: { through_tick_index: number; message: string },
): Promise<{ reply: string; messages: RunInterviewMessage[] }> {
  return api.post(interviewPath(runId, attemptId, variantId, personaId), body)
}

export function clearRunPersonaInterview(
  runId: number,
  attemptId: string,
  variantId: string,
  personaId: string,
  throughTickIndex: number,
): Promise<void> {
  return api.delete(
    `${interviewPath(runId, attemptId, variantId, personaId)}?through_tick_index=${throughTickIndex}`,
  )
}
