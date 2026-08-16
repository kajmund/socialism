import { api } from "@/lib/api"

export type AnchorKind = "tone" | "style"
export type AnchorLocale = "sv" | "en"
export type AnchorStatus = "draft" | "published"

export type AnchorValidationStatus = "untested" | "ok" | "stale" | "low"

export type SsrAnchorSet = {
  id: number
  name: string
  kind: AnchorKind
  locale: AnchorLocale
  version: string
  labels: string[]
  statements: string[]
  status: AnchorStatus
  pool_revision: number
  calibration_accuracy: number | null
  calibration_tested_at: string | null
  calibration_pool_revision: number | null
  calibration_n_at_test: number | null
  calibration_publish_override: boolean
  calibration_item_count: number
  validation_status: AnchorValidationStatus
  created_at: string
  updated_at: string
}

export type AnchorPublishGateDetail = {
  code: string
  detail: string
  accuracy: number | null
  missing_labels: string[]
  calibration_count: number
  requires_acknowledgement: boolean
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
  macro_accuracy?: number
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

export function publishAnchorSet(
  id: number,
  body: { acknowledge_warnings?: boolean } = {},
): Promise<SsrAnchorSet> {
  return api.post<SsrAnchorSet>(`/anchor-sets/${id}/publish`, body)
}

export function runAnchorCalibration(anchorSetId: number): Promise<AnchorTestResponse> {
  return api.post<AnchorTestResponse>(`/anchor-sets/${anchorSetId}/calibration/run`, {})
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

export type SsrAnchorPoolItem = {
  id: number
  anchor_set_id: number
  label: string
  text: string
  source_type: "comment" | "tick_interview" | "posthoc_interview"
  source_run_id: number | null
  source_attempt_id: string | null
  source_variant_id: string | null
  source_ref: Record<string, unknown>
  created_at: string
}

export function listPoolItems(anchorSetId: number): Promise<SsrAnchorPoolItem[]> {
  return api.get<SsrAnchorPoolItem[]>(`/anchor-sets/${anchorSetId}/pool`)
}

export function deleteAnchorPoolItem(anchorSetId: number, itemId: number): Promise<void> {
  return api.delete(`/anchor-sets/${anchorSetId}/pool/${itemId}`)
}

export type MisclassificationFlagStatus = "open" | "dismissed" | "resolved"

export type SsrMisclassificationFlag = {
  id: number
  anchor_set_id: number
  kind: AnchorKind
  text: string
  predicted_label: string
  expected_label: string
  source_type: SsrAnchorPoolItem["source_type"]
  source_ref: Record<string, unknown>
  source_run_id: number | null
  source_attempt_id: string | null
  source_variant_id: string | null
  status: MisclassificationFlagStatus
  pool_item_id: number | null
  created_at: string
  resolved_at: string | null
}

export type SsrMisclassificationFlagUpdate = {
  status: "dismissed" | "resolved"
  add_to_calibration?: boolean
}

export function listMisclassificationFlags(
  anchorSetId: number,
  status?: MisclassificationFlagStatus,
): Promise<SsrMisclassificationFlag[]> {
  return api.get<SsrMisclassificationFlag[]>(
    `/anchor-sets/${anchorSetId}/misclassification-flags`,
    status ? { status } : undefined,
  )
}

export function updateMisclassificationFlag(
  anchorSetId: number,
  flagId: number,
  body: SsrMisclassificationFlagUpdate,
): Promise<SsrMisclassificationFlag> {
  return api.patch<SsrMisclassificationFlag>(
    `/anchor-sets/${anchorSetId}/misclassification-flags/${flagId}`,
    body,
  )
}
