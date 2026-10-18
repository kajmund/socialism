import type { DocumentBatchItem, DocumentBatchStage, DocumentIngestBatch } from "@/api/documentIngestBatches"

export const BATCH_ACCEPT = ".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
export const BATCH_UPLOAD_LIMIT = 3

export type LocalBatchRow = {
  clientKey: string
  file?: File
  filename: string
  uploadLocal: number
  item: DocumentBatchItem | null
}

const NAME = /\.(pdf|docx|txt|md|markdown)$/i

export function acceptedBatchFile(file: File): boolean {
  return NAME.test(file.name)
}

export function shownPercent(value: number, options: { complete: boolean }): number {
  if (options.complete) return 100
  if (value <= 0) return 0
  return Math.min(99, Math.floor(value))
}

export function rowUploadPercent(row: LocalBatchRow): number {
  const stored = Boolean(row.item?.stored_object_id) && (row.item?.upload_progress ?? 0) >= 100
  if (stored) return 100
  return shownPercent(Math.max(row.uploadLocal, row.item?.upload_progress ?? 0), { complete: false })
}

export function rowIngestPercent(row: LocalBatchRow): number {
  return shownPercent(row.item?.ingest_progress ?? 0, { complete: Boolean(row.item?.searchable) })
}

export function mergeBatchRows(locals: LocalBatchRow[], batch: DocumentIngestBatch | null): LocalBatchRow[] {
  const server = new Map((batch?.items ?? []).map((item) => [item.client_key, item]))
  const seen = new Set<string>()
  const merged = locals.map((row) => {
    const item = server.get(row.clientKey) ?? row.item
    if (item) seen.add(item.client_key)
    return { ...row, filename: item?.filename ?? row.filename, item }
  })
  for (const item of batch?.items ?? []) {
    if (seen.has(item.client_key)) continue
    merged.push({ clientKey: item.client_key, filename: item.filename, uploadLocal: item.upload_progress, item })
  }
  return merged
}

export function activeBatch(batches: DocumentIngestBatch[]): DocumentIngestBatch | null {
  return batches.find((batch) => batch.status === "processing") ?? batches[0] ?? null
}

export function stageKey(stage: DocumentBatchStage | undefined): `documentBatch.stage.${DocumentBatchStage}` {
  return `documentBatch.stage.${stage ?? "waiting"}`
}

const DONE: ReadonlySet<DocumentBatchStage> = new Set(["ready", "failed", "skipped"])

export function rowStillRunning(row: LocalBatchRow): boolean {
  const stage = row.item?.stage
  if (stage == null) return row.file != null
  return !DONE.has(stage)
}
