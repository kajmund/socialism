import { useState } from "react"
import { workspaces } from "@/api/workspaces"
import { UnderlagPickerModal } from "@/components/underlag/UnderlagPickerModal"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale } from "@/i18n"

export function SmeIngestDialog({ workspaceId, open, onOpenChange, onChanged, onError, onReady }: { workspaceId: string; open: boolean; onOpenChange: (open: boolean) => void; onChanged: () => Promise<unknown>; onError: (error: unknown) => void; onReady: () => void }) {
  const { t } = useLocale()
  const [library, setLibrary] = useState(false)
  const [busy, setBusy] = useState(false)
  async function ingest(action: () => Promise<unknown>) {
    setBusy(true)
    try { await action(); await onChanged(); onOpenChange(false) }
    catch (error) { onError(error) }
    finally { setBusy(false) }
  }
  return <>
    <Dialog open={open} onOpenChange={onOpenChange}><DialogContent ref={(element) => { if (element) onReady() }} className="theme-admin max-w-lg"><DialogHeader><DialogTitle>{t("workspaceChat.addSource")}</DialogTitle></DialogHeader><label className="grid gap-2 text-sm">{t("workspaceChat.uploadFile")}<input type="file" accept=".txt,.md,.markdown,.pdf,.docx" disabled={busy} className="rounded border p-3 text-sm file:mr-3 file:rounded file:border-0 file:bg-db-ink-100 file:px-3 file:py-2" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void ingest(() => workspaces.upload(workspaceId, file)) }} /></label><AdminButton variant="secondary" disabled={busy} onClick={() => { onOpenChange(false); setLibrary(true) }}>{t("workspaceChat.library")}</AdminButton><form className="mt-2 grid gap-2" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); const url = String(data.get("url") ?? "").trim(); if (url) void ingest(() => workspaces.tool(workspaceId, "ingest_source", { url })) }}><label htmlFor="workspace-ingest-url" className="text-sm">{t("workspaceChat.url")}</label><input id="workspace-ingest-url" name="url" type="url" required placeholder={t("workspaceChat.urlPlaceholder")} disabled={busy} className="rounded border p-3 text-sm" /><AdminButton type="submit" disabled={busy}>{busy ? t("workspaceChat.uploading") : t("workspaceChat.ingest")}</AdminButton></form></DialogContent></Dialog>
    <UnderlagPickerModal open={library} module="dd" onOpenChange={setLibrary} onSelect={(source) => { setLibrary(false); void ingest(() => workspaces.attach(workspaceId, source.id)) }} />
  </>
}
