import { api } from "@/lib/api"
import { BOLAG_DEMO_CUSTOMER_ID } from "@/lib/scoping"

export type DdResultatFilter = "vinst" | "förlust" | "oavsett"

export type DdSourcingCriteria = {
  alder_min: number
  alder_max: number
  omrade: string
  resultat: DdResultatFilter
  fritext: string
}

export type DdCandidateCompany = {
  id: string
  namn: string
  organisationsnummer: string
  alder_ar: number
  omrade: string
  resultat: DdResultatFilter
  omsattning_sek: number | null
  anstallda: number | null
  beskrivning: string
}

export type DdCandidateRun = {
  candidate_id: string
  panel_session_id: string | null
  report_id: string | null
}

export type DdCampaign = {
  id: number
  module: string
  title: string
  status: string
  criteria: DdSourcingCriteria
  candidates: DdCandidateCompany[]
  selected_candidate_ids: string[]
  expert_role_keys: string[]
  customer_id: number
  candidate_runs: DdCandidateRun[]
  created_at: string
  updated_at: string
}

export function listDdCampaigns(params?: {
  module?: string
  customer_id?: number
}): Promise<DdCampaign[]> {
  const search = new URLSearchParams()
  if (params?.module) search.set("module", params.module)
  const customerId = params?.customer_id ?? BOLAG_DEMO_CUSTOMER_ID
  search.set("customer_id", String(customerId))
  const q = search.toString()
  return api.get<DdCampaign[]>(`/dd/campaigns?${q}`)
}

export function createDdCampaign(body: {
  title: string
  module?: string
  criteria?: DdSourcingCriteria
}): Promise<DdCampaign> {
  return api.post<DdCampaign>("/dd/campaigns", body)
}

export function getDdCampaign(id: number): Promise<DdCampaign> {
  return api.get<DdCampaign>(`/dd/campaigns/${id}`)
}

export function updateDdCampaign(
  id: number,
  body: Partial<{
    title: string
    status: string
    criteria: DdSourcingCriteria
    candidates: DdCandidateCompany[]
    selected_candidate_ids: string[]
    expert_role_keys: string[]
  }>,
): Promise<DdCampaign> {
  return api.patch<DdCampaign>(`/dd/campaigns/${id}`, body)
}

export function runDdCampaignSourcing(id: number): Promise<DdCampaign> {
  return api.post<DdCampaign>(`/dd/campaigns/${id}/sourcing/run`, {})
}

export function searchDdSourcing(criteria: DdSourcingCriteria): Promise<{ candidates: DdCandidateCompany[] }> {
  return api.post<{ candidates: DdCandidateCompany[] }>("/dd/sourcing/search", { criteria })
}

export function defaultDdCriteria(): DdSourcingCriteria {
  return { alder_min: 0, alder_max: 40, omrade: "", resultat: "oavsett", fritext: "" }
}
