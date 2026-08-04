import { api } from "@/lib/api"
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
}): Promise<RunSummary[]> {
  return api.get<RunSummary[]>("/runs", params)
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
