import { useEffect } from "react"
import type { Workspace, WorkspaceDocumentSet } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { DocumentThumbnail } from "./DocumentThumbnail"

export function WorkspaceDocumentSetPane({ workspace, documentSet, onOpen, onReady }: {
  workspace: Workspace
  documentSet: WorkspaceDocumentSet
  onOpen: (sourceId: string) => void
  onReady: (key: string) => void
}) {
  const { t } = useLocale()
  const sources = documentSet.source_ids.flatMap((id) => {
    const source = workspace.sources.find((row) => row.id === id)
    return source ? [source] : []
  })

  useEffect(() => { onReady(`document-set:${documentSet.id}`) }, [documentSet.id, onReady])

  return <div className="min-h-0 flex-1 overflow-auto p-5 sm:p-7">
    <div className="mx-auto max-w-5xl">
      <header className="mb-5">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-db-gold-700">{t("voiceWorkspaceChat.documentSet")}</p>
        <h2 className="mt-1 text-xl font-semibold text-db-ink-900">{documentSet.title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("voiceWorkspaceChat.documentSetCount", { count: sources.length })}</p>
      </header>
      {sources.length ? <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {sources.map((source) => <button
          key={source.id}
          type="button"
          className="group min-w-0 overflow-hidden rounded-lg border border-[color:var(--border-hairline)] bg-white text-left shadow-sm transition hover:border-db-gold-500 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-db-gold-500"
          onClick={() => onOpen(source.id)}
        >
          <div className="aspect-[3/4] overflow-hidden border-b border-[color:var(--border-hairline)] bg-db-ink-100">
            <DocumentThumbnail workspaceId={workspace.id} source={source} />
          </div>
          <div className="p-3">
            <span className="block truncate text-sm font-medium text-db-ink-900 group-hover:text-db-gold-800">{source.filename}</span>
          </div>
        </button>)}
      </div> : <p className="text-sm text-muted-foreground">{t("voiceWorkspaceChat.emptyDocumentSet")}</p>}
    </div>
  </div>
}
