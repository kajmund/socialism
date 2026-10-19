import { api } from "@/lib/api"
import type { Organization } from "@/api/profiles"

export type KundProjekt = {
  id: number
  customer_id: number
  name: string
  slug: string
}

export type Kund = Organization & {
  id: number
  name: string
  slug: string
  product: string | null
  available_modules: string[]
  projekt: KundProjekt[]
}

export function listKunder(): Promise<Kund[]> {
  return api.get<Kund[]>("/kunder")
}

export function createKund(body: {
  name: string
  slug: string
  available_modules?: string[]
}): Promise<Kund> {
  return api.post<Kund>("/kunder", body)
}

export function updateKundModules(id: number, available_modules: string[]): Promise<Kund> {
  return api.patch<Kund>(`/kunder/${id}`, { available_modules })
}

export function updateKundProduct(id: number, product: string | null): Promise<Kund> {
  return api.patch<Kund>(`/kunder/${id}`, { product })
}

export type KundDocumentCounts = {
  files: number
  knowledge_documents: number
  canonical_documents: number
  text_units: number
  document_knowledge_items: number
  claims: number
  entities: number
  relationships: number
  graph_events: number
  graph_facts: number
  graph_nodes: number
  ingest_batches: number
}

export type KundDocumentsBlockedReason = "document_ingest_active" | "graph_ingest_active"

export type KundDocumentSummary = {
  kund_id: number
  kund_name: string
  kund_slug: string
  counts: KundDocumentCounts
  blocked_reason: KundDocumentsBlockedReason | null
}

export type KundDocumentsDeleteResult = {
  kund_id: number
  deleted: KundDocumentCounts
  vector_documents: number
  stored_objects: number
}

export function getKundDocuments(kundId: number): Promise<KundDocumentSummary> {
  return api.get<KundDocumentSummary>(`/kunder/${kundId}/dokument`)
}

export function deleteKundDocuments(
  kundId: number,
  slug: string,
): Promise<KundDocumentsDeleteResult> {
  return api.delete<KundDocumentsDeleteResult>(`/kunder/${kundId}/dokument`, { confirm: slug })
}
