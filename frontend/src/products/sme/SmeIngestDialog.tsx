import { useEffect, useState } from "react"
import { listWorkspaceFiles, type WorkspaceFile } from "@/api/workspaces"
import { voiceWorkspaces, type Workspace } from "@/api/voiceWorkspaces"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { workspaceFileState } from "@/components/workspaces/workspaceChatState"
import { useLocale } from "@/i18n"
import { workspaceErrorMessage } from "./workspaceChatLogic"

export function SmeIngestDialog({ workspace, open, onOpenChange, onChanged, onError, onReady }: { workspace: Workspace; open: boolean; onOpenChange: (open: boolean) => void; onChanged: () => Promise<unknown>; onError: (error: unknown) => void; onReady: () => void }) {
  const { t } = useLocale()
  const [library, setLibrary] = useState(false)
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (!open) setLibrary(false) }, [open])
  useEffect(() => {
    if (!open || !library) return
    let cancelled = false
    setLoading(true); setFiles([]); setError(null)
    void listWorkspaceFiles(workspace.chat_id, workspace.customer_id).then((rows) => { if (!cancelled) setFiles(rows) }).catch((caught: unknown) => { if (!cancelled) setError(workspaceErrorMessage(caught, t)) }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [library, open, workspace.chat_id, workspace.customer_id, t])
  async function ingest(action: () => Promise<unknown>) {
    setBusy(true)
    try { await action(); await onChanged(); onOpenChange(false) }
    catch (caught) { onError(caught); setError(workspaceErrorMessage(caught, t)) }
    finally { setBusy(false) }
  }
  return <Dialog open={open} onOpenChange={(value) => { if (!busy) onOpenChange(value) }}><DialogContent ref={(element) => { if (element) onReady() }} className="theme-admin max-h-[85dvh] max-w-lg overflow-auto"><DialogHeader><DialogTitle>{t("voiceWorkspaceChat.addSource")}</DialogTitle></DialogHeader>
    <label className="grid gap-2 text-sm">{t("voiceWorkspaceChat.uploadFile")}<input type="file" accept=".txt,.md,.markdown,.pdf,.docx" disabled={busy} className="rounded border p-3 text-sm file:mr-3 file:rounded file:border-0 file:bg-db-ink-100 file:px-3 file:py-2" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void ingest(() => voiceWorkspaces.upload(workspace.id, file)) }} /></label>
    <AdminButton variant="secondary" disabled={busy} onClick={() => setLibrary((value) => !value)} aria-expanded={library}>{t("voiceWorkspaceChat.library")}</AdminButton>
    {library ? <div className="grid max-h-60 gap-2 overflow-auto rounded border p-3">{loading ? <p className="text-sm text-muted-foreground">{t("sme.loading")}</p> : !files.length ? <p className="text-sm text-muted-foreground">{t("workspaceChat.noFiles")}</p> : files.map((file) => <button type="button" key={file.id} disabled={busy || workspace.sources.some((source) => source.id === file.id)} className="rounded border p-3 text-left text-sm disabled:opacity-50" onClick={() => { void ingest(() => voiceWorkspaces.attach(workspace.id, file.id)) }}><strong className="block break-words">{file.filename}</strong><span className="text-xs text-muted-foreground">{t(`workspaceChat.${workspaceFileState(file)}`)} · {t(file.workspace_id === workspace.workspace_id ? "workspaceChat.files" : "workspaceChat.companyFile")}</span></button>)}</div> : null}
    <form className="mt-2 grid gap-2" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); const url = String(data.get("url") ?? "").trim(); if (url) void ingest(() => voiceWorkspaces.tool(workspace.id, "ingest_source", { url })) }}><label htmlFor="workspace-ingest-url" className="text-sm">{t("voiceWorkspaceChat.url")}</label><input id="workspace-ingest-url" name="url" type="url" required placeholder={t("voiceWorkspaceChat.urlPlaceholder")} disabled={busy} className="rounded border p-3 text-sm" /><AdminButton type="submit" disabled={busy}>{busy ? t("voiceWorkspaceChat.uploading") : t("voiceWorkspaceChat.ingest")}</AdminButton></form>
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
  </DialogContent></Dialog>
}
