import { api } from "@/lib/api"
import type { PopulationRecipe } from "@/api/populations"

export type JobKind = "population_generate" | "run_simulate" | "report_generate"
export type JobStatus = "pending" | "running" | "succeeded" | "failed"

export type PopulationGenerateJobRequest = {
  name: string
  recipe: PopulationRecipe
  population_id?: number | null
  include_persona_ids?: string[]
}

export type RunSimulateJobRequest = {
  run_id: number
}

export type Job = {
  id: string
  kind: JobKind | string
  status: JobStatus
  label: string
  request: Record<string, unknown>
  result: {
    population_id?: number
    fingerprint?: number[][]
    member_count?: number
    run_id?: number
    engine?: string
    ticks_run?: number
    report_id?: string
    html_path?: string
    sources?: number
    dry_run?: boolean
  } | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
}

export type JobCreate = {
  kind: JobKind
  label?: string
  request: PopulationGenerateJobRequest | RunSimulateJobRequest | Record<string, unknown>
}

export function createJob(body: JobCreate): Promise<Job> {
  return api.post<Job>("/jobs", body)
}

export function listJobs(params?: {
  status?: JobStatus
  limit?: number
}): Promise<Job[]> {
  const qs = new URLSearchParams()
  if (params?.status) qs.set("status", params.status)
  if (params?.limit != null) qs.set("limit", String(params.limit))
  const suffix = qs.toString() ? `?${qs}` : ""
  return api.get<Job[]>(`/jobs${suffix}`)
}

export function getJob(id: string): Promise<Job> {
  return api.get<Job>(`/jobs/${id}`)
}
