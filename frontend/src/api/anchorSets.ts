import { api } from "@/lib/api"

export type AnchorKind = "tone" | "style"
export type AnchorLocale = "sv" | "en"
export type AnchorStatus = "draft" | "published"

export type SsrAnchorSet = {
  id: number
  name: string
  kind: AnchorKind
  locale: AnchorLocale
  version: string
  labels: string[]
  statements: string[]
  status: AnchorStatus
  created_at: string
  updated_at: string
}

export type SsrAnchorSetWrite = {
  name: string
  kind: AnchorKind
  locale: AnchorLocale
  version?: string
  labels: string[]
  statements: string[]
  status?: AnchorStatus
}

export type SsrAnchorCalibrationItem = {
  id: number
  text: string
  human_label: string
  sort_order: number
  created_at: string
}

export type ConfigurationAnchorRef = {
  tone: number
  style: number
}

export type ConfigurationAnchorSets = {
  sv: ConfigurationAnchorRef
  en: ConfigurationAnchorRef
}

export type AnchorTestRequest = {
  texts: string[]
  temperature?: number
  use_calibration?: boolean
}

export type AnchorTestPerText = {
  text: string
  pmf: Record<string, number>
  predicted_label: string
}

export type AnchorTestResponse = {
  anchor_set_id?: number
  anchor_set_name: string
  anchor_set_version: string
  labels: string[]
  shares: Record<string, number>
  per_text: AnchorTestPerText[]
  human_labels?: string[]
  accuracy?: number
  confusion?: Record<string, Record<string, number>>
}

export function listAnchorSets(params?: {
  kind?: AnchorKind
  locale?: AnchorLocale
  status?: AnchorStatus
}): Promise<SsrAnchorSet[]> {
  return api.get<SsrAnchorSet[]>("/anchor-sets", params)
}

export function getAnchorSet(id: number): Promise<SsrAnchorSet> {
  return api.get<SsrAnchorSet>(`/anchor-sets/${id}`)
}

export function createAnchorSet(body: SsrAnchorSetWrite): Promise<SsrAnchorSet> {
  return api.post<SsrAnchorSet>("/anchor-sets", body)
}

export function updateAnchorSet(
  id: number,
  body: Partial<Pick<SsrAnchorSetWrite, "name" | "version" | "labels" | "statements">>,
): Promise<SsrAnchorSet> {
  return api.patch<SsrAnchorSet>(`/anchor-sets/${id}`, body)
}

export function publishAnchorSet(id: number): Promise<SsrAnchorSet> {
  return api.post<SsrAnchorSet>(`/anchor-sets/${id}/publish`, {})
}

export function duplicateAnchorSet(id: number): Promise<SsrAnchorSet> {
  return api.post<SsrAnchorSet>(`/anchor-sets/${id}/duplicate`, {})
}

export function deleteAnchorSet(id: number): Promise<void> {
  return api.delete(`/anchor-sets/${id}`)
}

export function listCalibrationItems(anchorSetId: number): Promise<SsrAnchorCalibrationItem[]> {
  return api.get<SsrAnchorCalibrationItem[]>(`/anchor-sets/${anchorSetId}/calibration`)
}

export function createCalibrationItem(
  anchorSetId: number,
  body: { text: string; human_label: string; sort_order?: number },
): Promise<SsrAnchorCalibrationItem> {
  return api.post<SsrAnchorCalibrationItem>(`/anchor-sets/${anchorSetId}/calibration`, body)
}

export function deleteCalibrationItem(anchorSetId: number, itemId: number): Promise<void> {
  return api.delete(`/anchor-sets/${anchorSetId}/calibration/${itemId}`)
}

export function testAnchorSet(
  anchorSetId: number,
  body: AnchorTestRequest,
): Promise<AnchorTestResponse> {
  return api.post<AnchorTestResponse>(`/anchor-sets/${anchorSetId}/test`, body)
}
