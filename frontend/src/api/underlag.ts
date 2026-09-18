import { api } from "@/lib/api"

export type UnderlagExtractionStatus =
  | "pending"
  | "ok"
  | "failed"
  | "empty"
  | "unsupported"
  | "needs_ocr"

export type UnderlagKnowledgeStatus =
  | "pending"
  | "running"
  | "ready"
  | "partial"
  | "failed"
  | "empty"
  | "needs_ocr"

export type DocumentKnowledgeKind = "fact" | "qa" | "bookmark" | "note"

export type DocumentAnchorRect = {
  x: number
  y: number
  width: number
  height: number
}

export type DocumentKnowledgeAnchor = {
  id?: string
  ordinal?: number
  anchor_type: "text" | "image" | "chart" | "table"
  page_number: number | null
  locator: string | null
  exact_text: string | null
  prefix_text: string | null
  suffix_text: string | null
  rects: DocumentAnchorRect[]
  asset_id: string | null
}

export type DocumentKnowledgeItem = {
  id: string
  source_object_id: string
  kind: DocumentKnowledgeKind
  origin: "generated" | "manual"
  status: "active" | "needs_review" | "archived"
  title: string
  question: string | null
  content: string | null
  retrieval_queries: string[]
  anchors: DocumentKnowledgeAnchor[]
  revision: number
  created_by_user_id: string | null
  updated_by_user_id: string | null
  created_at: string
  updated_at: string
}

export type DocumentKnowledgeWrite = {
  kind: DocumentKnowledgeKind
  title: string
  question?: string | null
  content?: string | null
  anchors: DocumentKnowledgeAnchor[]
}

export type UnderlagFile = {
  id: string
  kind: string
  filename: string
  content_type: string
  size_bytes: number
  module: string
  owner_user_id: string | null
  folder_id: string | null
  extraction_status: UnderlagExtractionStatus | null
  extracted_text?: string | null
  knowledge_status?: UnderlagKnowledgeStatus | null
  knowledge_error?: string | null
  knowledge_job_id?: string | null
  created_at: string
}

export type UnderlagFolder = {
  id: string
  name: string
  parent_id: string | null
  created_at: string
}

export type UnderlagListing = {
  folder_id: string | null
  folders: UnderlagFolder[]
  files: UnderlagFile[]
}

export function listUnderlag(
  module?: string | null,
  folderId?: string | null,
): Promise<UnderlagListing> {
  return api.get<UnderlagListing>("/underlag", {
    module: module ?? undefined,
    folder_id: module ? (folderId ?? undefined) : undefined,
  })
}

export function listUnderlagFolders(module: string): Promise<UnderlagFolder[]> {
  return api.get<UnderlagFolder[]>("/underlag/folders", { module })
}

export function createUnderlagFolder(body: {
  module: string
  name: string
  parent_id?: string | null
}): Promise<UnderlagFolder> {
  return api.post<UnderlagFolder>("/underlag/folders", {
    module: body.module,
    name: body.name,
    parent_id: body.parent_id ?? null,
  })
}

export function uploadUnderlag(
  file: File,
  module: string,
  folderId?: string | null,
): Promise<UnderlagFile> {
  const form = new FormData()
  form.append("file", file)
  const folderQuery = folderId ? `&folder_id=${encodeURIComponent(folderId)}` : ""
  return api.postForm<UnderlagFile>(
    `/underlag?module=${encodeURIComponent(module)}${folderQuery}`,
    form,
    {
      timeoutMs: 120_000,
    },
  )
}

export function getUnderlag(id: string): Promise<UnderlagFile> {
  return api.get<UnderlagFile>(`/underlag/${id}`)
}

export function getUnderlagFile(id: string): Promise<Blob> {
  return api.getBlob(`/underlag/${id}/file`)
}

export function moveUnderlag(id: string, folderId: string | null): Promise<UnderlagFile> {
  return api.patch<UnderlagFile>(`/underlag/${id}`, { folder_id: folderId })
}

export function deleteUnderlag(id: string): Promise<void> {
  return api.delete(`/underlag/${id}`)
}

export function listDocumentKnowledge(id: string): Promise<DocumentKnowledgeItem[]> {
  return api.get<DocumentKnowledgeItem[]>(`/underlag/${id}/knowledge`)
}

export function createDocumentKnowledge(
  id: string,
  body: DocumentKnowledgeWrite,
): Promise<DocumentKnowledgeItem> {
  return api.post<DocumentKnowledgeItem>(`/underlag/${id}/knowledge`, body)
}

export function updateDocumentKnowledge(
  id: string,
  itemId: string,
  body: DocumentKnowledgeWrite,
): Promise<DocumentKnowledgeItem> {
  return api.put<DocumentKnowledgeItem>(`/underlag/${id}/knowledge/${itemId}`, body)
}

export function deleteDocumentKnowledge(id: string, itemId: string): Promise<void> {
  return api.delete(`/underlag/${id}/knowledge/${itemId}`)
}
