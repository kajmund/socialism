import { useEffect, useRef, useState } from "react"
import { listWorkspaceFiles, type WorkspaceFile } from "@/api/workspaces"
import { documentIngestBatches, type DocumentIngestBatch } from "@/api/documentIngestBatches"
import { voiceWorkspaces, type Workspace } from "@/api/voiceWorkspaces"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { workspaceFileState } from "@/components/workspaces/workspaceChatState"
import { useLocale } from "@/i18n"
import { DocumentBatchDropzone } from "./DocumentBatchDropzone"
import { DocumentBatchTable } from "./DocumentBatchTable"
import { BATCH_UPLOAD_LIMIT, acceptedBatchFile, activeBatch, mergeBatchRows, rowStillRunning, type LocalBatchRow } from "./documentBatch"
import { workspaceErrorMessage } from "./workspaceChatLogic"

export function SmeIngestDialog({
  workspace,
  open,
  onOpenChange,
  onChanged,
  onError,
  onReady,
  onOpenDocument,
}: {
  workspace: Workspace
  open: boolean
  onOpenChange: (open: boolean) => void
  onChanged: () => Promise<unknown>
  onError: (error: unknown) => void
  onReady: () => void
  onOpenDocument: (sourceId: string) => void
}) {
  const { t } = useLocale()
  const [library, setLibrary] = useState(false)
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rejected, setRejected] = useState<string | null>(null)
  const [batch, setBatch] = useState<DocumentIngestBatch | null>(null)
  const [rows, setRows] = useState<LocalBatchRow[]>([])
  const inflight = useRef(new Set<string>())
  const batchRef = useRef<DocumentIngestBatch | null>(null)
  const rowsRef = useRef<LocalBatchRow[]>([])
  batchRef.current = batch
  rowsRef.current = rows

  useEffect(() => {
    if (!open) setLibrary(false)
  }, [open])
  useEffect(() => {
    setBatch(null)
    setRows([])
    batchRef.current = null
    rowsRef.current = []
    inflight.current.clear()
  }, [workspace.id])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void documentIngestBatches.list(workspace.id).then((listed) => {
      if (cancelled) return
      const current = activeBatch(listed)
      setBatch(current)
      setRows((currentRows) => mergeBatchRows(currentRows, current))
    }).catch((caught: unknown) => {
      if (!cancelled) setError(workspaceErrorMessage(caught, t))
    })
    return () => { cancelled = true }
  }, [open, workspace.id, t])

  useEffect(() => {
    if (!open || !library) return
    let cancelled = false
    setLoading(true); setFiles([]); setError(null)
    void listWorkspaceFiles(workspace.chat_id, workspace.customer_id)
      .then((listed) => { if (!cancelled) setFiles(listed) })
      .catch((caught: unknown) => { if (!cancelled) setError(workspaceErrorMessage(caught, t)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [library, open, workspace.chat_id, workspace.customer_id, t])

  const polling = rows.some(rowStillRunning)
  useEffect(() => {
    if (!open || !polling || !batch) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const next = await documentIngestBatches.get(workspace.id, batch.id)
        if (cancelled) return
        setBatch(next)
        setRows((current) => mergeBatchRows(current, next))
      } catch (caught) {
        if (!cancelled) setError(workspaceErrorMessage(caught, t))
      }
      if (!cancelled) timer = setTimeout(() => { void poll() }, 2500)
    }
    timer = setTimeout(() => { void poll() }, 2500)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [open, polling, batch, workspace.id, t])

  async function ensureBatch(): Promise<DocumentIngestBatch> {
    if (batchRef.current?.status === "processing") return batchRef.current
    const created = await documentIngestBatches.create(workspace.id)
    batchRef.current = created
    setBatch(created)
    return created
  }

  async function uploadRow(target: DocumentIngestBatch, row: LocalBatchRow) {
    if (!row.file || inflight.current.has(row.clientKey)) return
    inflight.current.add(row.clientKey)
    try {
      const next = await documentIngestBatches.upload(
        workspace.id, target.id, row.file, row.clientKey,
        (percent) => setRows((current) => current.map((item) => (
          item.clientKey === row.clientKey ? { ...item, uploadLocal: percent } : item
        ))),
      )
      batchRef.current = next
      setBatch(next)
      setRows((current) => {
        const merged = mergeBatchRows(current, next)
        rowsRef.current = merged
        return merged
      })
      await onChanged()
    } catch (caught) {
      onError(caught)
      setError(workspaceErrorMessage(caught, t))
    } finally {
      inflight.current.delete(row.clientKey)
      pump()
    }
  }

  function pump() {
    const target = batchRef.current
    if (!target) return
    const waiting = rowsRef.current.filter((row) => row.file && !row.item && !inflight.current.has(row.clientKey))
    const slots = BATCH_UPLOAD_LIMIT - inflight.current.size
    for (const row of waiting.slice(0, Math.max(0, slots))) void uploadRow(target, row)
  }

  async function addFiles(selected: File[]) {
    const allowed = selected.filter(acceptedBatchFile)
    const skipped = selected.filter((file) => !acceptedBatchFile(file)).map((file) => file.name)
    setRejected(skipped.length ? t("documentBatch.rejected", { names: skipped.join(", ") }) : null)
    if (!allowed.length) return
    try {
      await ensureBatch()
      const added = allowed.map((file) => ({
        clientKey: crypto.randomUUID(),
        file,
        filename: file.name,
        uploadLocal: 0,
        item: null,
      }))
      setRows((current) => {
        const next = [...current, ...added]
        rowsRef.current = next
        return next
      })
      pump()
    } catch (caught) {
      onError(caught)
      setError(workspaceErrorMessage(caught, t))
    }
  }

  async function ingest(action: () => Promise<unknown>) {
    setBusy(true)
    try { await action(); await onChanged() }
    catch (caught) { onError(caught); setError(workspaceErrorMessage(caught, t)) }
    finally { setBusy(false) }
  }

  async function retry(row: LocalBatchRow) {
    if (!batch) return
    if (row.item?.stored_object_id) {
      try {
        const next = await documentIngestBatches.retry(workspace.id, batch.id, row.item.id)
        setBatch(next)
        setRows((current) => mergeBatchRows(current, next))
        await onChanged()
      } catch (caught) {
        onError(caught)
        setError(workspaceErrorMessage(caught, t))
      }
      return
    }
    if (row.file) {
      setRows((current) => current.map((item) => (
        item.clientKey === row.clientKey ? { ...item, item: null, uploadLocal: 0 } : item
      )))
      void uploadRow(batch, { ...row, item: null, uploadLocal: 0 })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent ref={(element) => { if (element) onReady() }} className="theme-admin flex h-[min(90dvh,800px)] w-full flex-col overflow-hidden sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{t("documentBatch.title")}</DialogTitle>
          <DialogDescription>{t("documentBatch.moreHint")}</DialogDescription>
        </DialogHeader>
        <DocumentBatchDropzone disabled={busy} onFiles={(selected) => { void addFiles(selected) }} />
        {rejected ? <p role="status" className="text-sm text-muted-foreground">{rejected}</p> : null}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <DocumentBatchTable
            rows={rows}
            onOpen={(sourceId) => { onOpenChange(false); onOpenDocument(sourceId) }}
            onRetry={(row) => { void retry(row) }}
          />
        </div>
        <AdminButton variant="secondary" disabled={busy} onClick={() => setLibrary((value) => !value)} aria-expanded={library}>
          {t("voiceWorkspaceChat.library")}
        </AdminButton>
        {library ? (
          <div className="grid max-h-40 gap-2 overflow-auto rounded border p-3">
            {loading ? <p className="text-sm text-muted-foreground">{t("sme.loading")}</p>
              : !files.length ? <p className="text-sm text-muted-foreground">{t("workspaceChat.noFiles")}</p>
              : files.map((file) => (
                <button type="button" key={file.id} disabled={busy || workspace.sources.some((source) => source.id === file.id)} className="rounded border p-3 text-left text-sm disabled:opacity-50" onClick={() => { void ingest(() => voiceWorkspaces.attach(workspace.id, file.id)) }}>
                  <strong className="block break-words">{file.filename}</strong>
                  <span className="text-xs text-muted-foreground">{t(`workspaceChat.${workspaceFileState(file)}`)} · {t(file.workspace_id === workspace.workspace_id ? "workspaceChat.files" : "workspaceChat.companyFile")}</span>
                </button>
              ))}
          </div>
        ) : null}
        <form className="grid gap-2" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); const url = String(data.get("url") ?? "").trim(); if (url) void ingest(() => voiceWorkspaces.tool(workspace.id, "ingest_source", { url })) }}>
          <label htmlFor="workspace-ingest-url" className="text-sm">{t("voiceWorkspaceChat.url")}</label>
          <input id="workspace-ingest-url" name="url" type="url" required placeholder={t("voiceWorkspaceChat.urlPlaceholder")} disabled={busy} className="rounded border p-3 text-sm" />
          <AdminButton type="submit" disabled={busy}>{busy ? t("voiceWorkspaceChat.uploading") : t("voiceWorkspaceChat.ingest")}</AdminButton>
        </form>
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      </DialogContent>
    </Dialog>
  )
}
