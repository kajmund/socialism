import { describe, expect, it } from "vitest"
import { activeBatch, mergeBatchRows, rowIngestPercent, rowStillRunning, rowUploadPercent, shownPercent } from "./documentBatch"
import type { DocumentBatchItem, DocumentIngestBatch } from "@/api/documentIngestBatches"

function item(patch: Partial<DocumentBatchItem> = {}): DocumentBatchItem {
  return {
    id: "item-1",
    client_key: "k1",
    filename: "avtal.docx",
    content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    size_bytes: 10,
    upload_progress: 0,
    ingest_progress: 0,
    stage: "waiting",
    status: "pending",
    searchable: false,
    stored_object_id: null,
    document_id: null,
    document_version_id: null,
    job_id: null,
    error: null,
    created_at: "2026-10-12T00:00:00Z",
    ...patch,
  }
}

function batch(items: DocumentBatchItem[], status: DocumentIngestBatch["status"] = "processing"): DocumentIngestBatch {
  return { id: "b1", voice_workspace_id: "ws", status, created_at: "2026-10-12T00:00:00Z", items }
}

describe("document batch progress", () => {
  it("never shows 100 until that side is done", () => {
    expect(shownPercent(100, { complete: false })).toBe(99)
    expect(shownPercent(100, { complete: true })).toBe(100)
    expect(rowUploadPercent({ clientKey: "k1", filename: "a.docx", uploadLocal: 80, item: item({ upload_progress: 40 }) })).toBe(80)
    expect(rowUploadPercent({
      clientKey: "k1", filename: "a.docx", uploadLocal: 99,
      item: item({ upload_progress: 100, stored_object_id: "doc" }),
    })).toBe(100)
    expect(rowIngestPercent({
      clientKey: "k1", filename: "a.docx", uploadLocal: 100,
      item: item({ ingest_progress: 100, searchable: false, stage: "indexing" }),
    })).toBe(99)
    expect(rowIngestPercent({
      clientKey: "k1", filename: "a.docx", uploadLocal: 100,
      item: item({ ingest_progress: 100, searchable: true, stage: "ready" }),
    })).toBe(100)
  })

  it("keeps local waiting rows and merges server items", () => {
    const rows = mergeBatchRows(
      [{ clientKey: "local", filename: "ny.docx", uploadLocal: 12, item: null }],
      batch([item({ client_key: "server", filename: "gammal.pdf" })]),
    )
    expect(rows.map((row) => row.filename)).toEqual(["ny.docx", "gammal.pdf"])
    expect(activeBatch([batch([], "completed"), batch([], "processing")])?.status).toBe("processing")
  })

  it("stops polling skipped rows", () => {
    expect(rowStillRunning({ clientKey: "k1", filename: "a.docx", uploadLocal: 0, item: item({ stage: "skipped", status: "skipped" }) })).toBe(false)
    expect(rowStillRunning({ clientKey: "k1", filename: "a.docx", uploadLocal: 0, item: item({ stage: "extracting", status: "processing" }) })).toBe(true)
    expect(rowStillRunning({ clientKey: "local", filename: "ny.docx", uploadLocal: 12, file: new File(["x"], "ny.docx"), item: null })).toBe(true)
  })
})
