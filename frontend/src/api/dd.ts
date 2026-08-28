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

export type DdAccountFigure = {
  kod: string
  namn: string
  enhet: "sek" | "pct" | "antal" | "tal"
  sek: number | null
  tal: string | null
}

export type DdAccountYear = {
  year: string
  omsattning_sek: number | null
  resultat_sek: number | null
  ebitda_sek: number | null
  utdelning_sek?: number | null
  anstallda: number | null
  eget_kapital_sek: number | null
  soliditet_pct: string | null
  poster?: DdAccountFigure[]
}

export type DdOfficer = {
  namn: string
  roll: string
  grupp: string
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
  fskatt?: boolean | null
  moms?: boolean | null
  arbetsgivaravgift?: boolean | null
  styrelse?: DdOfficer[]
  firmateckning?: string[]
  koncern_bolag?: number | null
  koncern_dotter?: number | null
  moderbolag?: string
  varumarken?: string[]
  rakenskaper?: DdAccountYear[]
  sni?: string[]
  handelser?: string[]
  arbetsstallen?: string[]
  relaterade_bolag?: string[]
  telefon?: string
  foretagshypotek?: boolean | null
  betalningsanmarkning?: boolean | null
  gasell?: boolean | null
}

export type DdCandidateRun = {
  candidate_id: string
  panel_session_id: string | null
  report_id: string | null
  created_at?: string
  updated_at?: string
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
  expert_panel_id: number | null
  panel_assignments: Record<string, number>
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

export function deleteDdCampaign(id: number): Promise<void> {
  return api.delete(`/dd/campaigns/${id}`)
}

export function deleteDdCandidateRun(campaignId: number, candidateId: string): Promise<void> {
  return api.delete(`/dd/campaigns/${campaignId}/runs/${candidateId}`)
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
    expert_panel_id: number | null
    panel_assignments: Record<string, number>
    enrich_from_allabolag: boolean
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

export type DdSourcingChatMessage = {
  role: "user" | "assistant"
  content: string
}

export function chatDdSourcing(
  campaignId: number,
  body: { message: string; history: DdSourcingChatMessage[] },
): Promise<{ reply: string; candidates: DdCandidateCompany[] }> {
  return api.post(`/dd/campaigns/${campaignId}/sourcing/chat`, body, { timeoutMs: 120_000 })
}

export function defaultDdCriteria(): DdSourcingCriteria {
  return { alder_min: 0, alder_max: 40, omrade: "", resultat: "oavsett", fritext: "" }
}

export function mergeDdCandidates(
  existing: DdCandidateCompany[],
  incoming: DdCandidateCompany[],
): DdCandidateCompany[] {
  const byOrgnr = new Map(existing.map((c) => [c.organisationsnummer, c]))
  const order = existing.map((c) => c.organisationsnummer)
  for (const candidate of incoming) {
    if (byOrgnr.has(candidate.organisationsnummer)) continue
    order.push(candidate.organisationsnummer)
    byOrgnr.set(candidate.organisationsnummer, candidate)
  }
  return order.map((orgnr) => byOrgnr.get(orgnr)!)
}
