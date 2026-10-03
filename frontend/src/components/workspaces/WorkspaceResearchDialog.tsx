import { useEffect, useRef, useState } from "react"
import type { Workspace, WorkspaceFile } from "@/api/workspaces"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale } from "@/i18n"
import { selectedFilesBlocked, workspaceFileState } from "./workspaceChatState"

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspace: Workspace | null
  files: WorkspaceFile[]
  busy: boolean
  error: string | null
  onStart: (question: string, sourceObjectIds: string[]) => Promise<boolean>
}

export function WorkspaceResearchDialog({ open, onOpenChange, workspace, files, busy, error, onStart }: Props) {
  const { t } = useLocale()
  const [question, setQuestion] = useState("")
  const [selected, setSelected] = useState<string[]>([])
  const filesRef = useRef(files)
  filesRef.current = files

  useEffect(() => {
    if (open) {
      setQuestion("")
      setSelected(filesRef.current.map((file) => file.id))
    }
    // Keep the user's selection while readiness polling updates files.
  }, [open])

  const blocked = selectedFilesBlocked(files, selected)
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!busy) onOpenChange(next) }}>
      <DialogContent showCloseButton={false} style={{ minHeight: 0 }} className="theme-admin max-h-[85dvh] overflow-auto sm:max-w-xl">
        <form onSubmit={(event) => {
          event.preventDefault()
          if (!question.trim() || blocked || busy) return
          void onStart(question.trim(), selected).then((started) => { if (started) onOpenChange(false) })
        }} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{t("workspaceChat.startResearch")}</DialogTitle>
            <DialogDescription>{t("workspaceChat.researchIntro")}</DialogDescription>
          </DialogHeader>
          <p className="rounded border border-[color:var(--border-hairline)] bg-db-ink-50 px-3 py-2 text-sm">
            {t("workspaceChat.workspace")}: <strong>{workspace?.name}</strong>
          </p>
          <label className="grid gap-1.5 text-sm">
            <span>{t("workspaceChat.question")}</span>
            <textarea autoFocus required maxLength={4000} rows={4} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={t("workspaceChat.questionPlaceholder")} className="w-full resize-y rounded border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 py-2 outline-none focus:border-db-gold-500" />
          </label>
          <fieldset className="grid gap-2">
            <legend className="mb-2 text-sm font-medium">{t("workspaceChat.selectDocuments")}</legend>
            {files.length === 0 ? <p className="text-xs text-[color:var(--text-muted)]">{t("workspaceChat.noFiles")}</p> : null}
            {files.map((file) => (
              <label key={file.id} className="flex items-start gap-2 rounded border border-[color:var(--border-hairline)] p-2 text-sm">
                <input type="checkbox" checked={selected.includes(file.id)} onChange={(event) => setSelected((ids) => event.target.checked ? [...ids, file.id] : ids.filter((id) => id !== file.id))} className="mt-1 accent-db-gold-500" />
                <span className="min-w-0 flex-1">
                  <span className="block break-words">{file.filename}</span>
                  <span className="text-xs text-[color:var(--text-muted)]">{t(`workspaceChat.${workspaceFileState(file)}`)}{file.workspace_id !== workspace?.id ? ` · ${t("workspaceChat.companyFile")}` : ""}</span>
                </span>
              </label>
            ))}
          </fieldset>
          {blocked ? <p role="status" className="rounded bg-db-gold-500/10 p-3 text-sm">{t("workspaceChat.pendingDocuments")}</p> : null}
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
          <DialogFooter>
            <AdminButton type="button" variant="secondary" disabled={busy} onClick={() => onOpenChange(false)}>{t("workspaceChat.cancel")}</AdminButton>
            <AdminButton type="submit" disabled={!workspace || !question.trim() || blocked || busy}>{t("workspaceChat.startResearch")}</AdminButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
