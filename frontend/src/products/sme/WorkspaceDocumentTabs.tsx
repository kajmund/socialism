import { X } from "lucide-react"
import type { Workspace, WorkspaceArtifact, WorkspaceState } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { activeWorkspaceSourceId, artifactWorkspaceView, withArtifactTab } from "./workspaceChatLogic"

function artifactTabs(workspace: Workspace): WorkspaceArtifact[] {
  const ids = [...(workspace.state.open_artifact_ids ?? [])]
  const active = workspace.state.active_artifact_id
  if (active && !ids.includes(active)) ids.push(active)
  return ids.flatMap((id) => {
    const artifact = workspace.artifacts.find((row) => row.id === id)
    return artifact ? [artifact] : []
  })
}

function sourceTitle(workspace: Workspace, sourceId: string): string {
  return workspace.sources.find((row) => row.id === sourceId)?.filename
    ?? workspace.references.find((row) => row.source_id === sourceId)?.title
    ?? ""
}

export function WorkspaceDocumentTabs({ workspace, onState }: {
  workspace: Workspace
  onState: (change: (state: WorkspaceState) => WorkspaceState) => void
}) {
  const { t } = useLocale()
  const { state } = workspace
  const artifacts = artifactTabs(workspace)
  const split = state.split_source_ids.length === 2
  const showingSources = state.view === "documents" && !state.active_artifact_id

  function showSource(sourceId: string) {
    onState((current) => {
      if (!current.documents.some((row) => row.source_id === sourceId)) return current
      return {
        ...current,
        view: "documents",
        active_artifact_id: null,
        active_document_set_id: null,
        active_source_id: sourceId,
        split_source_ids: [],
      }
    })
  }

  function closeSource(sourceId: string) {
    onState((current) => {
      const documents = current.documents.filter((row) => row.source_id !== sourceId)
      const active = current.active_source_id === sourceId
        ? documents[0]?.source_id ?? null
        : current.active_source_id
      return { ...current, documents, active_source_id: active, split_source_ids: [] }
    })
  }

  function showArtifact(artifact: WorkspaceArtifact) {
    onState((current) => ({
      ...withArtifactTab(current, artifact.id),
      view: artifactWorkspaceView(artifact.kind),
      active_artifact_id: artifact.id,
      active_document_set_id: null,
      split_source_ids: [],
      selection: { artifact_id: artifact.id, artifact_revision: artifact.revision },
    }))
  }

  function closeArtifact(id: string) {
    onState((current) => {
      const open = (current.open_artifact_ids ?? []).filter((row) => row !== id)
      if (current.active_artifact_id !== id) return { ...current, open_artifact_ids: open }
      return { ...current, open_artifact_ids: open, active_artifact_id: null, view: "documents", split_source_ids: [] }
    })
  }

  function showDocumentSet(id: string) {
    onState((current) => ({
      ...current,
      view: "document_set",
      active_document_set_id: id,
      active_artifact_id: null,
      split_source_ids: [],
      selection: null,
    }))
  }

  function closeDocumentSet(id: string) {
    onState((current) => {
      const documentSets = (current.document_sets ?? []).filter((row) => row.id !== id)
      if (current.active_document_set_id !== id) return { ...current, document_sets: documentSets }
      return {
        ...current,
        document_sets: documentSets,
        active_document_set_id: null,
        view: "documents",
        split_source_ids: [],
      }
    })
  }

  return <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto px-2 py-2">
    {state.documents.map((document) => {
      const activeId = activeWorkspaceSourceId(state)
      const current = showingSources && (split ? state.split_source_ids.includes(document.source_id) : document.source_id === activeId)
      return <span key={document.source_id} className={`flex shrink-0 items-center rounded-lg border text-xs ${current ? "border-db-gold-500 bg-white font-semibold" : "bg-db-ink-50"}`}>
        <button type="button" className="max-w-44 truncate px-3 py-2" aria-current={current ? "true" : undefined} onClick={() => showSource(document.source_id)}>{sourceTitle(workspace, document.source_id)}</button>
        <button type="button" className="grid size-7 shrink-0 place-items-center" aria-label={t("voiceWorkspaceChat.closeDocument")} onClick={() => closeSource(document.source_id)}><X size={14} /></button>
      </span>
    })}
    {(state.document_sets ?? []).map((documentSet) => {
      const current = state.view === "document_set" && state.active_document_set_id === documentSet.id
      return <span key={documentSet.id} className={`flex shrink-0 items-center rounded-lg border text-xs ${current ? "border-db-gold-500 bg-white font-semibold" : "bg-db-ink-50"}`}>
        <button type="button" className="max-w-44 truncate px-3 py-2" aria-current={current ? "true" : undefined} onClick={() => showDocumentSet(documentSet.id)}>{documentSet.title}</button>
        <button type="button" className="grid size-7 shrink-0 place-items-center" aria-label={t("voiceWorkspaceChat.closeDocumentSet")} onClick={() => closeDocumentSet(documentSet.id)}><X size={14} /></button>
      </span>
    })}
    {artifacts.map((artifact) => {
      const current = state.active_artifact_id === artifact.id && state.view === artifactWorkspaceView(artifact.kind)
      return <span key={artifact.id} className={`flex shrink-0 items-center rounded-lg border text-xs ${current ? "border-db-gold-500 bg-white font-semibold" : "bg-db-ink-50"}`}>
        <button type="button" className="max-w-44 truncate px-3 py-2" aria-current={current ? "true" : undefined} onClick={() => showArtifact(artifact)}>{artifact.title}</button>
        <button type="button" className="grid size-7 shrink-0 place-items-center" aria-label={t("voiceWorkspaceChat.closeTab")} onClick={() => closeArtifact(artifact.id)}><X size={14} /></button>
      </span>
    })}
    {state.documents.length >= 2 ? <button type="button" className="ml-auto shrink-0 whitespace-nowrap rounded border px-3 py-2 text-xs" onClick={() => onState((current) => {
      const activeId = activeWorkspaceSourceId(current)
      const ordered = activeId
        ? [activeId, ...current.documents.map((row) => row.source_id).filter((id) => id !== activeId)]
        : current.documents.map((row) => row.source_id)
      return {
        ...current,
        view: "documents",
        active_artifact_id: null,
        active_document_set_id: null,
        split_source_ids: current.split_source_ids.length === 2 ? [] : ordered.slice(0, 2),
      }
    })}>{t(state.split_source_ids.length === 2 ? "voiceWorkspaceChat.single" : "voiceWorkspaceChat.split")}</button> : null}
  </div>
}
