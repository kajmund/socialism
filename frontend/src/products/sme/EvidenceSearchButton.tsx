import { useState } from "react"
import { Search } from "lucide-react"
import type { KnowledgeResult, Workspace } from "@/api/voiceWorkspaces"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale } from "@/i18n"
import { WorkspaceKnowledge } from "./WorkspaceKnowledge"

export function EvidenceSearchButton({
  workspace,
  knowledge,
  openFromWorkspace,
  onSearch,
  onOpen,
  onLeaveEvidence,
  className,
}: {
  workspace: Workspace
  knowledge: KnowledgeResult
  openFromWorkspace: boolean
  onSearch: (query: string) => void
  onOpen: (id: string) => void
  onLeaveEvidence: () => void
  className?: string
}) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const shown = open || openFromWorkspace
  const sourceNames = Object.fromEntries(workspace.sources.map((source) => [source.id, source.filename]))

  function close() {
    setOpen(false)
    if (openFromWorkspace) onLeaveEvidence()
  }

  function openReference(id: string) {
    setOpen(false)
    onOpen(id)
  }

  return <>
    <button type="button" className={className ?? "flex h-9 shrink-0 items-center gap-1.5 rounded-lg border px-3 text-sm"} onClick={() => setOpen(true)}>
      <Search size={15} />
      {t("voiceWorkspaceChat.evidence")}
    </button>
    <Dialog open={shown} onOpenChange={(next) => { if (!next) close() }}>
      <DialogContent className="theme-admin flex max-h-[80vh] max-w-2xl flex-col gap-3">
        <DialogHeader>
          <DialogTitle>{t("voiceWorkspaceChat.evidence")}</DialogTitle>
        </DialogHeader>
        <form className="flex rounded-lg border bg-white px-3" onSubmit={(event) => { event.preventDefault(); const query = String(new FormData(event.currentTarget).get("query") ?? "").trim(); if (query) onSearch(query) }}>
          <input name="query" className="min-w-0 flex-1 bg-transparent py-3 text-sm outline-none" placeholder={t("voiceWorkspaceChat.searchPlaceholder")} aria-label={t("voiceWorkspaceChat.search")} />
          <button type="submit" aria-label={t("voiceWorkspaceChat.search")}><Search size={18} /></button>
        </form>
        <div className="min-h-0 flex-1 overflow-auto">
          <WorkspaceKnowledge result={knowledge} sourceNames={sourceNames} onOpen={openReference} />
        </div>
      </DialogContent>
    </Dialog>
  </>
}
