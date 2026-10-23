import { api } from "@/lib/api"

export type ClassificationLevel = "document" | "clause" | "variant"
export type DecisionAnswer = "yes" | "no" | "skip" | "unsure"

export type ClauseClassification = {
  id: string
  slug: string
  version: number
  question: string
  level: ClassificationLevel
  category: string
  active: boolean
  scope_key: string
}

export type QueueCard = {
  unit_id: string
  document_id: string
  document_version_id: string
  text: string
  locator: string | null
  ordinal: number
  section_title: string | null
  content_hash: string
  classification: ClauseClassification
  similarity: number | null
  similarity_kind: "cosine" | null
}

export type ReviewSession = {
  id: string
  reviewer_id: string
  classification_id: string
  document_id: string | null
  last_unit_id: string | null
  last_verification_id: string | null
  decided_yes: number
  decided_no: number
  skipped: number
  unsure: number
  answered: number
  scope_key: string
}

export type QueuePage = {
  cards: QueueCard[]
  session: ReviewSession
  remaining: number
  total_eligible: number
}

export type DecisionResult = {
  verification: {
    id: string
    answer: DecisionAnswer
    polarity: "positive" | "negative" | null
    is_label: boolean
    revision: number
    status: string
  }
  session: ReviewSession
}

export function listClassifications(customerId?: number) {
  return api.get<{ items: ClauseClassification[] }>("/clause-ssr/classifications", {
    customer_id: customerId,
    active_only: true,
  })
}

export function createClassification(body: {
  slug: string
  question: string
  category: string
  level?: ClassificationLevel
  customer_id?: number
}) {
  return api.post<ClauseClassification>("/clause-ssr/classifications", body)
}

export function fetchQueue(input: {
  classificationId: string
  documentId?: string
  customerId?: number
  limit?: number
}) {
  return api.get<QueuePage>("/clause-ssr/queue", {
    classification_id: input.classificationId,
    document_id: input.documentId,
    customer_id: input.customerId,
    limit: input.limit ?? 5,
  })
}

export function recordDecision(body: {
  classification_id: string
  unit_id: string
  answer: DecisionAnswer
  document_id?: string
  customer_id?: number
}) {
  return api.post<DecisionResult>("/clause-ssr/decisions", body)
}

export function undoDecision(body: {
  classification_id: string
  document_id?: string
  customer_id?: number
}) {
  return api.post<{ session: ReviewSession; unit_id: string | null }>(
    "/clause-ssr/decisions/undo",
    body,
  )
}
