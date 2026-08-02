import { api } from "@/lib/api"
import type {
  BranchState,
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
  results: OasisRunResults | null
}

export type RunWrite = {
  name: string
  population_id: number
  seed?: string
  start_date?: string | null
  status?: RunStatus
  main_ticks?: Tick[]
  branch?: BranchState | null
}

export type RunUpdate = {
  name?: string
  population_id?: number
  seed?: string
  start_date?: string | null
  status?: RunStatus
  main_ticks?: Tick[]
  branch?: BranchState | null
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
  // OASIS in-request sim can take several minutes with small agent caps.
  return api.post<RunDetail>(`/runs/${id}/start`, undefined, { timeoutMs: 600_000 })
}

export function duplicateRun(id: number): Promise<RunDetail> {
  return api.post<RunDetail>(`/runs/${id}/duplicate`)
}

export function deleteRun(id: number): Promise<void> {
  return api.delete(`/runs/${id}`)
}
