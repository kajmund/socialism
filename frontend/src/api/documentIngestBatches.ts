import { api } from "@/lib/api"

export type DocumentBatchStage =
  | "waiting"
  | "uploading"
  | "extracting"
  | "indexing"
  | "classifying"
  | "enriching"
  | "ready"
  | "skipped"
  | "failed"

export type DocumentBatchItem = {
  id: string
  client_key: string
  filename: string
  content_type: string
  size_bytes: number
  upload_progress: number
  ingest_progress: number
  stage: DocumentBatchStage
  status: "pending" | "processing" | "ready" | "skipped" | "failed"
  searchable: boolean
  stored_object_id: string | null
  document_id: string | null
  document_version_id: string | null
  job_id: string | null
  error: string | null
  created_at: string
}

export type DocumentIngestBatch = {
  id: string
  voice_workspace_id: string
  status: "processing" | "completed"
  created_at: string
  items: DocumentBatchItem[]
}

export const documentIngestBatches = {
  create: (workspaceId: string) =>
    api.post<DocumentIngestBatch>(`/voice-workspaces/${workspaceId}/ingest-batches`),
  list: (workspaceId: string) =>
    api.get<DocumentIngestBatch[]>(`/voice-workspaces/${workspaceId}/ingest-batches`),
  get: (workspaceId: string, batchId: string) =>
    api.get<DocumentIngestBatch>(`/voice-workspaces/${workspaceId}/ingest-batches/${batchId}`),
  upload: (
    workspaceId: string,
    batchId: string,
    file: File,
    clientKey: string,
    onProgress?: (percent: number) => void,
  ) => {
    const form = new FormData()
    form.append("file", file)
    form.append("client_key", clientKey)
    form.append("idempotency_key", crypto.randomUUID())
    return api.postFormWithProgress<DocumentIngestBatch>(
      `/voice-workspaces/${workspaceId}/ingest-batches/${batchId}/files`,
      form,
      { timeoutMs: 120_000, onProgress },
    )
  },
  retry: (workspaceId: string, batchId: string, itemId: string) =>
    api.post<DocumentIngestBatch>(
      `/voice-workspaces/${workspaceId}/ingest-batches/${batchId}/items/${itemId}/retry`,
    ),
}
