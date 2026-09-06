import { api } from "@/lib/api"
import type {
  EditablePersona,
  PopulationMember,
  PopulationSummary,
} from "@/data/library-types"

export type PopulationDistQaRow = {
  k: string
  l: string
  target_v: number
  achieved_v: number
}

export type PopulationDistQaGroup = {
  key: string
  label: string
  rows: PopulationDistQaRow[]
}

export type PopulationDetail = PopulationSummary & {
  recipe: Record<string, unknown>
  members: PopulationMember[]
  target_fp: number[][]
  qa_warnings: string[]
  dist_qa: PopulationDistQaGroup[]
  fingerprint_inferred: boolean
}

export type DistRow = { k: string; l: string; v: number }
export type DistGroup = { label: string; rows: DistRow[] }

export type PopulationRecipe = {
  size: number
  dist: Record<string, DistGroup>
  locale?: string
  seed?: number | null
}

export type GeneratedPersona = {
  name: string
  initials: string
  age: number
  occ: string
  district: string
  occ_key: string
  district_key: string
  lean: string
  lean_label: string
  trait: string
  quote: string
  profile: EditablePersona
}

export type GenerationCandidate = {
  key: string
  source: "generated" | "library"
  persona_id: string | null
  persona: GeneratedPersona
}

export type PopulationGenerateRequest = {
  recipe: PopulationRecipe
  include_persona_ids?: string[]
  generation_id?: string | null
  existing?: GenerationCandidate[]
  replace_keys?: string[]
  mode?: "replace" | "append"
}

export type PopulationGenerateResponse = {
  generation_id: string
  fingerprint: number[][]
  candidates: GenerationCandidate[]
  warnings?: string[]
}

export type PopulationMemberWrite = {
  persona_id?: string | null
  name: string
  initials: string
  age: number
  occ: string
  district: string
  trait?: string
}

export type PopulationWrite = {
  kind?: "persona" | "expert_panel"
  name: string
  fingerprint?: number[][]
  recipe?: Record<string, unknown>
  members?: PopulationMemberWrite[]
  include_persona_ids?: string[]
  generation_id?: string
  keep_keys?: string[]
}

export type PopulationUpdate = {
  name?: string
  fingerprint?: number[][]
  recipe?: Record<string, unknown>
  members?: PopulationMemberWrite[]
  bump_version?: boolean
  generation_id?: string
  keep_keys?: string[]
}

export function listPopulations(params: {
  kind: "persona" | "expert_panel"
}): Promise<PopulationSummary[]> {
  const search = new URLSearchParams({ kind: params.kind })
  return api.get<PopulationSummary[]>(`/populations?${search.toString()}`)
}

export function getPopulation(id: number): Promise<PopulationDetail> {
  return api.get<PopulationDetail>(`/populations/${id}`)
}

export function generatePopulation(
  body: PopulationGenerateRequest,
): Promise<PopulationGenerateResponse> {
  return api.post<PopulationGenerateResponse>("/populations/generate", body)
}

export function createPopulation(body: PopulationWrite): Promise<PopulationDetail> {
  return api.post<PopulationDetail>("/populations", body)
}

export function updatePopulation(
  id: number,
  body: PopulationUpdate,
): Promise<PopulationDetail> {
  return api.put<PopulationDetail>(`/populations/${id}`, body)
}

export function deletePopulation(id: number): Promise<void> {
  return api.delete(`/populations/${id}`)
}

export function duplicatePopulation(id: number): Promise<PopulationDetail> {
  return api.post<PopulationDetail>(`/populations/${id}/duplicate`)
}

export function addPopulationMember(
  populationId: number,
  body: PopulationMemberWrite,
): Promise<PopulationMember> {
  return api.post<PopulationMember>(`/populations/${populationId}/members`, body)
}

export function removePopulationMember(
  populationId: number,
  memberId: number,
): Promise<void> {
  return api.delete(`/populations/${populationId}/members/${memberId}`)
}
