import { api } from "@/lib/api"
import type {
  EditablePersona,
  PopulationMember,
  PopulationSummary,
} from "@/data/library-types"

export type PopulationDetail = PopulationSummary & {
  recipe: Record<string, unknown>
  members: PopulationMember[]
}

export type DistRow = { k: string; l: string; v: number }
export type DistGroup = { label: string; rows: DistRow[] }

export type PopulationRecipe = {
  size: number
  entryMode: "free" | "manual"
  freeText?: string
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
  name: string
  fingerprint?: number[][]
  recipe?: Record<string, unknown>
  members?: PopulationMemberWrite[]
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

export function listPopulations(): Promise<PopulationSummary[]> {
  return api.get<PopulationSummary[]>("/populations")
}

export function getPopulation(id: number): Promise<PopulationDetail> {
  return api.get<PopulationDetail>(`/populations/${id}`)
}

export function generatePopulation(
  body: PopulationGenerateRequest,
): Promise<PopulationGenerateResponse> {
  // DeepSeek builds each persona sequentially/in parallel; a full batch can take minutes.
  return api.post<PopulationGenerateResponse>("/populations/generate", body, {
    timeoutMs: 600_000,
  })
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
