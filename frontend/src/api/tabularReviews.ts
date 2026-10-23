import { api } from "@/lib/api"

export type CellStatus = "hit" | "no_hit" | "unknown" | "negative_hit"
export type CellPolarity = "positive" | "negative"
export type ReviewState = "pending" | "approved" | "rejected"

export type TabularReviewSource = {
  text_unit_id?: string
  document_id?: string
  document_version_id?: string
  exact_text?: string
  page_start?: number
  page_end?: number
  locator?: string
  section_id?: string
  rects?: Array<{ x: number; y: number; width: number; height: number }>
}

export type TabularReviewCandidate = {
  rank: number
  text_unit_id: string
  exact_text: string
  similarity: number
  polarity: CellPolarity
  source: TabularReviewSource
}

export type TabularReviewCell = {
  id: number
  row_id: number
  column_id: number
  status: CellStatus
  similarity: number | null
  text_unit_id: string | null
  exact_text: string | null
  source: TabularReviewSource
  locked: boolean
  flagged: boolean
  review_state: ReviewState
  note: string | null
  candidate_count: number
  candidates: TabularReviewCandidate[]
}

export type TabularReviewColumn = {
  id: number
  title: string
  anchor_set_id: number
  label: string
  polarity: CellPolarity
  allow_abstain: boolean
  abstain_margin: number | null
  sort_order: number
}

export type TabularReviewRow = {
  id: number
  document_id: string
  document_version_id: string
  title: string
  source_object_id: string | null
  cells: TabularReviewCell[]
}

export type TabularReviewSummary = {
  id: number
  name: string
  document_count: number
  column_count: number
  score_threshold: number
  computed_at: string | null
  updated_at: string
  created_at: string
}

export type TabularReview = {
  id: number
  name: string
  customer_id: number
  score_threshold: number
  sort_key: string
  sort_dir: "asc" | "desc"
  filter_json: Record<string, unknown>
  computed_at: string | null
  updated_at: string
  created_at: string
  columns: TabularReviewColumn[]
  rows: TabularReviewRow[]
}

export type TabularReviewDocument = {
  document_id: string
  title: string
  document_version_id: string
  source_object_id: string | null
  mime_type: string
}

export type TabularReviewClauseAnchor = {
  id: number
  name: string
  labels: string[]
  version: string
}

export type TabularReviewColumnWrite = {
  title: string
  anchor_set_id: number
  label: string
  polarity?: CellPolarity
  allow_abstain?: boolean
  abstain_margin?: number | null
}

export type TabularReviewEvent = {
  id: number
  action: string
  actor_user_id: string
  payload: Record<string, unknown>
  created_at: string
}

export function listTabularReviews(): Promise<TabularReviewSummary[]> {
  return api.get<TabularReviewSummary[]>("/tabular-reviews")
}

export function getTabularReview(id: number): Promise<TabularReview> {
  return api.get<TabularReview>(`/tabular-reviews/${id}`)
}

export function createTabularReview(body: {
  name: string
  document_ids?: string[]
  columns?: TabularReviewColumnWrite[]
  score_threshold?: number
}): Promise<TabularReview> {
  return api.post<TabularReview>("/tabular-reviews", body)
}

export function updateTabularReview(
  id: number,
  body: {
    name?: string
    document_ids?: string[]
    score_threshold?: number
    sort_key?: string
    sort_dir?: "asc" | "desc"
    filter_json?: Record<string, unknown>
  },
): Promise<TabularReview> {
  return api.patch<TabularReview>(`/tabular-reviews/${id}`, body)
}

export function deleteTabularReview(id: number): Promise<void> {
  return api.delete(`/tabular-reviews/${id}`)
}

export function addTabularReviewColumn(id: number, body: TabularReviewColumnWrite): Promise<TabularReview> {
  return api.post<TabularReview>(`/tabular-reviews/${id}/columns`, body)
}

export function deleteTabularReviewColumn(id: number, columnId: number): Promise<void> {
  return api.delete(`/tabular-reviews/${id}/columns/${columnId}`)
}

export function runTabularReview(id: number): Promise<TabularReview> {
  return api.post<TabularReview>(`/tabular-reviews/${id}/run`, {})
}

export function listTabularReviewDocuments(): Promise<TabularReviewDocument[]> {
  return api.get<TabularReviewDocument[]>("/tabular-reviews/documents")
}

export function listTabularReviewClauseAnchors(): Promise<TabularReviewClauseAnchor[]> {
  return api.get<TabularReviewClauseAnchor[]>("/tabular-reviews/clause-anchors")
}

export function approveTabularReviewCell(id: number, cellId: number): Promise<TabularReviewCell> {
  return api.post<TabularReviewCell>(`/tabular-reviews/${id}/cells/${cellId}/approve`, {})
}

export function rejectTabularReviewCell(id: number, cellId: number): Promise<TabularReviewCell> {
  return api.post<TabularReviewCell>(`/tabular-reviews/${id}/cells/${cellId}/reject`, {})
}

export function flagTabularReviewCell(id: number, cellId: number): Promise<TabularReviewCell> {
  return api.post<TabularReviewCell>(`/tabular-reviews/${id}/cells/${cellId}/flag`, {})
}

export function lockTabularReviewCell(id: number, cellId: number): Promise<TabularReviewCell> {
  return api.post<TabularReviewCell>(`/tabular-reviews/${id}/cells/${cellId}/lock`, {})
}

export function noteTabularReviewCell(id: number, cellId: number, note: string): Promise<TabularReviewCell> {
  return api.post<TabularReviewCell>(`/tabular-reviews/${id}/cells/${cellId}/note`, { note })
}

export function tabularReviewCellHistory(id: number, cellId: number): Promise<TabularReviewEvent[]> {
  return api.get<TabularReviewEvent[]>(`/tabular-reviews/${id}/cells/${cellId}/history`)
}
