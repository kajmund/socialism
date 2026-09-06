import { api } from "@/lib/api"
import type { Job } from "@/api/jobs"

export type RattsunderlagLocale = "sv" | "en"
export type SourcingStatus = "complete" | "partial" | "no_sources_found"

export type LagtextRef = {
  sfs_id: string
  rubrik: string
  utdrag: string
  url?: string | null
}

export type PraxisRef = {
  referens: string
  instans: string
  utdrag: string
  url?: string | null
}

export type ForarbeteRef = {
  referens: string
  titel: string
  utdrag: string
  url?: string | null
}

export type RattsunderlagResult = {
  fraga: string
  lagtext: LagtextRef[]
  praxis: PraxisRef[]
  forarbeten: ForarbeteRef[]
  sammanfattning: string
  sourcing_status: SourcingStatus
}

export type RattsunderlagJob = Job & {
  result: Job["result"] & {
    result?: RattsunderlagResult
    underlag_id?: string
    report_id?: string
    sourcing_status?: SourcingStatus
  }
}

export function startRattsunderlagResearch(body: {
  fraga: string
  locale?: RattsunderlagLocale
}): Promise<RattsunderlagJob> {
  return api.post<RattsunderlagJob>("/rattsunderlag/research", body)
}

export function listRattsunderlagResearch(): Promise<RattsunderlagJob[]> {
  return api.get<RattsunderlagJob[]>("/rattsunderlag/research")
}

export function getRattsunderlagResearch(jobId: string): Promise<RattsunderlagJob> {
  return api.get<RattsunderlagJob>(`/rattsunderlag/research/${jobId}`)
}

export function resultFromJob(job: RattsunderlagJob): RattsunderlagResult | null {
  const payload = job.result?.result
  if (!payload || typeof payload !== "object") return null
  if (typeof payload.fraga !== "string") return null
  return payload
}
