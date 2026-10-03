import { useEffect, useState } from "react"
import { getWorkspacePassage, type WorkspaceCitation, type WorkspacePassage } from "@/api/workspaces"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export function WorkspaceSourceDialog({ chatId, citation, customerId, onClose }: {
  chatId: string
  citation: WorkspaceCitation | null
  customerId?: number
  onClose: () => void
}) {
  const { t } = useLocale()
  const [passage, setPassage] = useState<WorkspacePassage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    setPassage(null)
    setError(null)
    setLoading(Boolean(citation?.source_object_id))
    if (citation?.source_object_id) {
      void getWorkspacePassage(chatId, citation, customerId)
        .then((row) => { if (!cancelled) setPassage(row) })
        .catch((err: unknown) => { if (!cancelled) setError(err instanceof ApiError ? err.message : t("workspaceChat.sourceError")) })
        .finally(() => { if (!cancelled) setLoading(false) })
    }
    return () => { cancelled = true }
  }, [chatId, citation, customerId, t])

  return (
    <Dialog open={Boolean(citation)} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent showCloseButton={false} style={{ minHeight: 0 }} className="theme-admin max-h-[85dvh] overflow-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("workspaceChat.originalPassage")}</DialogTitle>
          <DialogDescription>{passage?.filename ?? passage?.title ?? citation?.label}</DialogDescription>
        </DialogHeader>
        <p className="text-xs text-[color:var(--text-muted)]">{passage?.locator ?? citation?.locator}</p>
        <blockquote className="whitespace-pre-wrap break-words rounded border-l-2 border-db-gold-500 bg-db-ink-50 p-4 text-sm leading-relaxed">{passage?.text ?? passage?.excerpt ?? citation?.excerpt}</blockquote>
        {citation?.document_version_id ? <p className="break-all text-xs text-[color:var(--text-muted)]">{t("workspaceChat.version")}: {citation.document_version_id}</p> : null}
        {loading ? <p role="status" className="text-xs text-[color:var(--text-muted)]">{t("workspaceChat.loadingPassage")}</p> : null}
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
        <DialogFooter><AdminButton variant="secondary" onClick={onClose}>{t("workspaceChat.close")}</AdminButton></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
