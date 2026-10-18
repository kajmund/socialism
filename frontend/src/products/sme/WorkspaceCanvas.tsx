import { useEffect, useRef } from "react"
import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import type { Comparison, KnowledgeResult, PassageComment, Relations, Workspace, WorkspaceArtifact, WorkspaceChart, WorkspaceSelection, WorkspaceState, WorkspaceView } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { WorkspaceArtifactEditor } from "./WorkspaceArtifactEditor"
import { WorkspaceComparison } from "./WorkspaceComparison"
import { WorkspaceChartView } from "./WorkspaceChartView"
import { WorkspaceRelations } from "./WorkspaceRelations"
import { ModelTraceButton } from "./ModelTraceButton"
import { WorkspaceDocumentTabs } from "./WorkspaceDocumentTabs"
import { WorkspaceDocumentSetPane } from "./WorkspaceDocumentSetPane"
import { WorkspaceSourcePane } from "./WorkspaceSourcePane"
import type { ModelTraceEntry } from "./modelTrace"
import { activeWorkspaceSourceId, artifactPresentationKey, navigateWorkspaceDocument, openWorkspaceDocument } from "./workspaceChatLogic"
import type { LocalDocumentSelection } from "./workspaceLocalSelection"

function visiblePane(view: WorkspaceView, kind: string | undefined): "comparison" | "document_set" | "documents" | "relations" {
  if (view === "comparison" || (view === "evidence" && kind === "comparison")) return "comparison"
  if (view === "relations" || (view === "evidence" && kind === "relations")) return "relations"
  if (view === "document_set") return "document_set"
  return "documents"
}

export function WorkspaceCanvas({ workspace, knowledge, localSelection, reader = null, trace, onState, onSelection, onClearSelection, onCommentSaved = () => undefined, onCommentRemoved = () => undefined, onOpen, onReady, onError, onSaved }: {
  workspace: Workspace; knowledge: KnowledgeResult; localSelection: LocalDocumentSelection | null; reader?: { id: string; name: string } | null; trace: ModelTraceEntry[]
  onState: (change: (state: WorkspaceState) => WorkspaceState) => void
  onSelection: (sourceId: string, value: WorkspaceSelection) => void
  onClearSelection: (sourceId: string) => void
  onCommentSaved?: (comment: PassageComment) => void
  onCommentRemoved?: (id: string, removedReferenceIds: string[]) => void
  onOpen: (id: string) => void; onReady: (key: string) => void; onError: (key: string, message: string) => void
  onSaved: (artifact: WorkspaceArtifact) => void
}) {
  const { t } = useLocale()
  const { state } = workspace
  const artifact = workspace.artifacts.find((row) => row.id === state.active_artifact_id)
  const reference = workspace.references.find((row) => row.reference_id === state.selection?.reference_id)
  useEffect(() => { const key = artifactPresentationKey(artifact, state.view); if (key) onReady(key) }, [artifact, onReady, state.view])
  useEffect(() => { if (state.view === "evidence") onReady("evidence") }, [knowledge, onReady, state.view])
  useEffect(() => {
    if (state.view === "document_set" && state.active_document_set_id) onReady(`document-set:${state.active_document_set_id}`)
  }, [onReady, state.active_document_set_id, state.view])
  const excerptReference = reference?.source_kind !== "underlag" ? reference : undefined
  const selection = (value: WorkspaceSelection | null) => onState((current) => ({ ...current, selection: value ? { artifact_id: artifact?.id, artifact_revision: artifact?.revision, ...value } : null }))
  const clearSelection = (sourceId: string) => onClearSelection(sourceId)
  const pane = visiblePane(state.view, artifact?.kind)
  const documentSet = (state.document_sets ?? []).find((row) => row.id === state.active_document_set_id)
  const activeSourceId = activeWorkspaceSourceId(state)
  const documentIds = state.split_source_ids.length === 2
    ? state.split_source_ids
    : activeSourceId ? [activeSourceId] : []
  const retainedWorkspace = useRef(workspace.id)
  const retainDocuments = useRef(pane === "documents")
  const retainDocumentSet = useRef(pane === "document_set")
  if (retainedWorkspace.current !== workspace.id) {
    retainedWorkspace.current = workspace.id
    retainDocuments.current = pane === "documents"
    retainDocumentSet.current = pane === "document_set"
  }
  if (pane === "documents") retainDocuments.current = true
  if (pane === "document_set") retainDocumentSet.current = true
  const showExcerpt = Boolean(excerptReference && !state.active_artifact_id)
  const showEditor = !showExcerpt && artifact?.kind === "document" && artifact.status === "ready"
  const showChart = !showExcerpt && !showEditor && artifact?.kind === "chart" && artifact.status === "ready"
  const showSources = !showExcerpt && !showEditor && !showChart
  return <section className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-db-ink-50">
    <div className="flex shrink-0 items-center border-b border-[color:var(--border-hairline)] bg-white"><WorkspaceDocumentTabs workspace={workspace} onState={onState} /><div className="flex shrink-0 items-center pr-1"><ModelTraceButton entries={trace} /></div></div>
    {pane === "comparison" ? artifact?.kind === "comparison" && artifact.status === "ready" ? <WorkspaceComparison comparison={artifact.content as Comparison} references={workspace.references} onOpen={onOpen} /> : <p className="p-6 text-sm text-muted-foreground">{t("voiceWorkspaceChat.emptyComparison")}</p> : null}
    {pane === "relations" ? artifact?.kind === "relations" && artifact.status === "ready" ? <WorkspaceRelations relations={artifact.content as Relations} references={workspace.references} selection={state.selection} onSelect={selection} onOpen={onOpen} /> : <p className="p-6 text-sm text-muted-foreground">{t("voiceWorkspaceChat.emptyRelations")}</p> : null}
    {(retainDocumentSet.current || pane === "document_set") ? <div className={pane === "document_set" ? "flex min-h-0 min-w-0 flex-1 flex-col" : "hidden"} hidden={pane !== "document_set"}>
      {documentSet ? <WorkspaceDocumentSetPane workspace={workspace} documentSet={documentSet} onOpen={(sourceId) => onState((current) => openWorkspaceDocument(current, sourceId))} onReady={onReady} /> : <p className="p-6 text-sm text-muted-foreground">{t("voiceWorkspaceChat.emptyDocumentSet")}</p>}
    </div> : null}
    {retainDocuments.current ? <div className={pane === "documents" ? "flex min-h-0 min-w-0 flex-1 flex-col" : "hidden"} hidden={pane !== "documents"}>
      <div className="flex min-h-0 flex-1 overflow-hidden">{showExcerpt && excerptReference ? <WorkspaceSourcePane workspace={workspace} localSelection={localSelection} reader={reader} sourceId={excerptReference.source_id} page={1} zoom={1} reference={excerptReference} onNavigate={() => undefined} onSelection={(anchor, sourceVersion, sourceFileSha256) => onSelection(excerptReference.source_id, { reference_id: excerptReference.reference_id, source_version: sourceVersion, ...(sourceFileSha256 ? { source_file_sha256: sourceFileSha256 } : {}), anchor })} onClearSelection={() => clearSelection(excerptReference.source_id)} onCommentSaved={onCommentSaved} onCommentRemoved={onCommentRemoved} onReady={() => onReady(`source:${excerptReference.source_id}:${excerptReference.reference_id}`)} onError={(_, message) => onError(`source:${excerptReference.source_id}:${excerptReference.reference_id}`, message)} /> : null}{showEditor && artifact ? <div className="min-w-0 flex-1"><WorkspaceArtifactEditor key={artifact.id} workspaceId={workspace.id} artifact={artifact} references={workspace.references} onSaved={onSaved} onReady={(revision) => onReady(`artifact:${artifact.id}:${revision}`)} onSelect={(block_id, revision) => selection({ block_id: block_id ?? undefined, artifact_revision: revision })} onOpen={onOpen} /></div> : null}{showChart && artifact ? <div className="min-w-0 flex-1 overflow-auto"><WorkspaceChartView chart={artifact.content as WorkspaceChart} references={workspace.references} onOpen={onOpen} /></div> : null}{state.documents.map((document) => { const sourceId = document.source_id; const visible = showSources && documentIds.includes(sourceId); const documentReference = (reference?.source_id === sourceId ? reference : undefined) ?? workspace.references.find((row) => row.reference_id === document.reference_id); return <div key={sourceId} className={visible ? "contents" : "hidden"} hidden={!visible}><WorkspaceSourcePane workspace={workspace} localSelection={localSelection} reader={reader} sourceId={sourceId} page={document.page} zoom={document.zoom} reference={documentReference} onNavigate={(page, zoom) => onState((current) => navigateWorkspaceDocument(current, sourceId, page, zoom))} onSelection={(anchor: DocumentKnowledgeAnchor, sourceVersion: string, sourceFileSha256?: string) => onSelection(sourceId, { source_id: sourceId, source_version: sourceVersion, ...(sourceFileSha256 ? { source_file_sha256: sourceFileSha256 } : {}), anchor })} onClearSelection={() => clearSelection(sourceId)} onCommentSaved={onCommentSaved} onCommentRemoved={onCommentRemoved} onReady={() => onReady(`source:${sourceId}:${documentReference?.reference_id ?? ""}`)} onError={(_, message) => onError(`source:${sourceId}:${documentReference?.reference_id ?? ""}`, message)} /></div> })}{showSources && !documentIds.length ? <p className="p-6 text-sm text-muted-foreground">{t("voiceWorkspaceChat.emptyDocuments")}</p> : null}</div>
    </div> : null}
  </section>
}
