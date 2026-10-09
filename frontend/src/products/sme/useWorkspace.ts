import { useCallback, useEffect, useRef, useState } from "react"
import { voiceWorkspaces, type KnowledgeResult, type SourceReference, type VoiceWorkspaceParent, type Workspace, type WorkspaceArtifact, type WorkspaceSelection, type WorkspaceState, type WorkspaceSummary } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"
import { commitWorkspaceState, openWorkspaceDocument, requiredString, sameWorkspaceState, takeReadyGenerationArtifact, workspaceErrorMessage } from "./workspaceChatLogic"
import { workspaceFocusReference } from "./workspaceDocumentFocus"
import { captureWorkspaceTurn, type WorkspaceTurnSnapshot } from "./workspaceTurnSnapshot"
import { captureDocumentTurn, clearLocalDocumentSelection, localSelectionMatchesReference, mergeMaterializedSelection, type LocalDocumentSelection } from "./workspaceLocalSelection"

export function useWorkspace(parent: VoiceWorkspaceParent | null) {
  const { t, locale } = useLocale()
  const { jobs } = useJobsRealtime()
  const [list, setList] = useState<WorkspaceSummary[]>([])
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [knowledge, setKnowledge] = useState<KnowledgeResult>({ items: [], gaps: [] })
  const [picker, setPicker] = useState(false)
  const [localSelection, setLocalSelection] = useState<LocalDocumentSelection | null>(null)
  const localSelectionRef = useRef<LocalDocumentSelection | null>(null)
  const current = useRef<Workspace | null>(null)
  const persisted = useRef<Workspace | null>(null)
  const turnSnapshot = useRef<Promise<WorkspaceTurnSnapshot | null>>(Promise.resolve(null))
  const pendingTurn = useRef(false)
  const pendingChanges = useRef(0)
  const generation = useRef(0)
  const queue = useRef(Promise.resolve())
  const ready = useRef(new Set<string>())
  const pending = useRef(new Map<string, { resolve: () => void; reject: (error: Error) => void; timer: number; selectionSensitive: boolean }>())
  const generationStatus = useRef(new Map<string, string>())
  const pendingGeneration = useRef(new Set<string>())
  const openedGeneration = useRef(new Set<string>())
  const onContext = useRef<(text: string) => void>(() => undefined)
  const report = useCallback((caught: unknown) => setError(workspaceErrorMessage(caught, t, "voiceWorkspaceChat.operationError")), [t])
  const labels = useRef(t), errors = useRef(report)
  labels.current = t; errors.current = report
  const apply = useCallback((value: Workspace) => { persisted.current = value; current.current = value; if (!pendingTurn.current) turnSnapshot.current = captureWorkspaceTurn(value); setWorkspace(value) }, [])
  const selectDocument = useCallback((sourceId: string, selection: WorkspaceSelection | null) => {
    if (!current.current) return
    localSelectionRef.current = selection ? { sourceId, selection: structuredClone(selection), clearedSourceIds: localSelectionRef.current?.clearedSourceIds?.filter((id) => id !== sourceId) }
      : clearLocalDocumentSelection(current.current.state, current.current.references, localSelectionRef.current, sourceId)
    setLocalSelection(localSelectionRef.current)
    for (const [key, waiter] of pending.current) if (waiter.selectionSensitive) { window.clearTimeout(waiter.timer); pending.current.delete(key); waiter.reject(new Error(labels.current("voiceWorkspaceChat.selectionChanged"))) }
  }, [])
  const snapshot = useCallback(() => captureDocumentTurn(turnSnapshot.current, localSelectionRef.current), [])
  const select = useCallback(async (id: string) => {
    const request = ++generation.current
    current.current = null; persisted.current = null; turnSnapshot.current = Promise.resolve(null); pendingTurn.current = false; pendingChanges.current = 0; setWorkspace(null); ready.current.clear(); setKnowledge({ items: [], gaps: [] }); setError(null)
    localSelectionRef.current = null; setLocalSelection(null)
    for (const waiter of pending.current.values()) { window.clearTimeout(waiter.timer); waiter.reject(new Error(labels.current("voiceWorkspaceChat.presentationError"))) }
    pending.current.clear()
    const value = await voiceWorkspaces.get(id)
    if (request === generation.current) apply(value)
  }, [apply])
  const parentId = parent?.workspaceId, customerId = parent?.customerId
  useEffect(() => {
    let cancelled = false
    generation.current += 1
    current.current = null; persisted.current = null; turnSnapshot.current = Promise.resolve(null); pendingTurn.current = false; pendingChanges.current = 0
    localSelectionRef.current = null; setLocalSelection(null)
    setWorkspace(null); setList([]); setKnowledge({ items: [], gaps: [] }); setPicker(false); setError(null); ready.current.clear()
    for (const waiter of pending.current.values()) { window.clearTimeout(waiter.timer); waiter.reject(new Error(labels.current("voiceWorkspaceChat.presentationError"))) }
    pending.current.clear()
    if (parentId) void voiceWorkspaces.list({ workspaceId: parentId, customerId }).then((rows) => { if (cancelled) return; setList(rows); if (rows[0]) void select(rows[0].id).catch(errors.current) }).catch((error: unknown) => { if (!cancelled) errors.current(error) })
    return () => { cancelled = true }
  }, [parentId, customerId, select])
  const refresh = useCallback(async () => {
    await queue.current
    const previous = current.current
    if (!previous) return null
    const value = await voiceWorkspaces.get(previous.id)
    if (current.current?.id !== value.id || value.revision < (persisted.current?.revision ?? current.current.revision)) return null
    if (pendingChanges.current) return current.current
    apply(value)
    return value
  }, [apply])
  const change = useCallback((update: (state: WorkspaceState) => WorkspaceState, isCurrent: () => boolean = () => true): Promise<Workspace> => {
    if (!current.current || !isCurrent()) return Promise.reject(new Error(t("voiceWorkspaceChat.loadError")))
    const id = current.current.id, epoch = generation.current
    const previous = current.current.state, next = update(previous)
    pendingChanges.current += 1
    pendingTurn.current = true
    if (!sameWorkspaceState(previous, next)) { current.current = { ...current.current, state: next }; setWorkspace(current.current) }
    const task = queue.current.then(async () => {
      const previous = persisted.current
      if (!previous || previous.id !== id || epoch !== generation.current || !isCurrent()) throw new Error(t("voiceWorkspaceChat.loadError"))
      const value = await commitWorkspaceState(previous, update, { write: (revision, state) => voiceWorkspaces.update(previous.id, revision, state), read: () => voiceWorkspaces.get(previous.id) })
      if (value === previous || (value.revision === previous.revision && sameWorkspaceState(value.state, previous.state))) { if (pendingChanges.current === 1) apply(previous); return previous }
      if (epoch !== generation.current) throw new Error(t("voiceWorkspaceChat.presentationError"))
      if (!isCurrent()) {
        persisted.current = value
        if (current.current?.id === value.id) {
          const state = current.current.state.selection && value.state.selection
            ? { ...current.current.state, selection: mergeMaterializedSelection(current.current.state.selection, value.state.selection) }
            : current.current.state
          current.current = { ...value, state }
          setWorkspace(current.current)
        }
        throw new Error(t("voiceWorkspaceChat.presentationError"))
      }
      if (pendingChanges.current > 1 && current.current?.id === value.id) {
        persisted.current = value
        const state = current.current.state.selection && value.state.selection
          ? { ...current.current.state, selection: mergeMaterializedSelection(current.current.state.selection, value.state.selection) }
          : current.current.state
        current.current = { ...value, state }
        setWorkspace(current.current)
      }
      else apply(value)
      setError(null)
      try { onContext.current(`Workspace state updated: ${JSON.stringify(value.state)}`) } catch (error) { report(error) }
      return value
    }).catch((error: unknown) => { if (epoch === generation.current && pendingChanges.current === 1 && persisted.current?.id === id) apply(persisted.current); throw error })
    const settled = task.finally(() => { if (epoch === generation.current) pendingChanges.current = Math.max(0, pendingChanges.current - 1) })
    const snapshot = captureWorkspaceTurn(settled)
    turnSnapshot.current = snapshot
    void snapshot.then(() => { if (epoch === generation.current && turnSnapshot.current === snapshot) pendingTurn.current = false }, () => undefined)
    queue.current = settled.then(() => undefined, report)
    return settled
  }, [apply, report, t])
  const create = useCallback(async (title: string) => { if (!parentId) throw new Error(t("voiceWorkspaceChat.loadError")); const epoch = generation.current; const value = await voiceWorkspaces.create(title, locale, { workspaceId: parentId, customerId }); if (epoch !== generation.current) return; setList((rows) => [value, ...rows]); await select(value.id) }, [locale, parentId, customerId, select, t])
  const markReady = useCallback((key: string) => { ready.current.add(key); const waiter = pending.current.get(key); if (waiter) { window.clearTimeout(waiter.timer); pending.current.delete(key); waiter.resolve() } }, [])
  const presentationError = useCallback((key: string, message: string) => { ready.current.delete(key); setError(message); const waiter = pending.current.get(key); if (waiter) { window.clearTimeout(waiter.timer); pending.current.delete(key); waiter.reject(new Error(message)) } }, [])
  const wait = useCallback((key: string, selectionSensitive = false) => ready.current.has(key) ? Promise.resolve() : new Promise<void>((resolve, reject) => { const existing = pending.current.get(key); if (existing) { window.clearTimeout(existing.timer); existing.reject(new Error(t("voiceWorkspaceChat.presentationError"))) } const timer = window.setTimeout(() => { pending.current.delete(key); reject(new Error(t("voiceWorkspaceChat.presentationError"))) }, 20_000); pending.current.set(key, { resolve, reject, timer, selectionSensitive }) }), [t])
  useEffect(() => () => { for (const waiter of pending.current.values()) { window.clearTimeout(waiter.timer); waiter.reject(new Error(t("voiceWorkspaceChat.presentationError"))) } }, [t])
  const loadReference = useCallback(async (workspaceId: string, referenceId: string): Promise<SourceReference> => {
    const verified = await voiceWorkspaces.reference(workspaceId, referenceId)
    const workspaceNow = current.current
    if (workspaceNow?.id === workspaceId && !workspaceNow.references.some((row) => row.reference_id === verified.reference_id)) {
      const references = [...workspaceNow.references, verified]
      current.current = { ...workspaceNow, references }
      if (persisted.current?.id === workspaceId) persisted.current = { ...persisted.current, references }
      setWorkspace(current.current)
    }
    return verified
  }, [])
  const open = useCallback(async (referenceId: string, isCurrent: () => boolean = () => true, preserveLocal = false) => {
    if (!preserveLocal) { localSelectionRef.current = null; setLocalSelection(null) }
    const local = localSelectionRef.current
    const active = () => isCurrent() && localSelectionRef.current === local
    const value = await refresh()
    if (!active()) throw new Error(t("voiceWorkspaceChat.selectionChanged"))
    const workspaceId = value?.id ?? current.current?.id
    if (!workspaceId) throw new Error(t("voiceWorkspaceChat.referenceUnavailable"))
    const reference = await loadReference(workspaceId, referenceId)
    if (reference.stale) throw new Error(t("voiceWorkspaceChat.stale"))
    if (!active()) throw new Error(t("voiceWorkspaceChat.selectionChanged"))
    if (local && !localSelectionMatchesReference(local, reference)) throw new Error(t("voiceWorkspaceChat.selectionChanged"))
    setError(null)
    const key = `source:${reference.source_id}:${reference.reference_id}`
    if (reference.source_kind !== "underlag") { ready.current.delete(key); await change((state) => ({ ...state, view: "documents", active_artifact_id: null, selection: { reference_id: referenceId } }), active); if (!active()) throw new Error(t("voiceWorkspaceChat.selectionChanged")); await wait(key, true); return }
    ready.current.delete(key)
    await change((state) => ({ ...openWorkspaceDocument(state, reference.source_id, reference.anchor?.page_number ?? 1), documents: openWorkspaceDocument(state, reference.source_id, reference.anchor?.page_number ?? 1).documents.map((row) => row.source_id === reference.source_id ? { ...row, reference_id: referenceId } : row), active_artifact_id: null, selection: { reference_id: referenceId } }), active)
    if (!active()) throw new Error(t("voiceWorkspaceChat.selectionChanged"))
    await wait(key, true)
  }, [change, loadReference, refresh, t, wait])
  const search = useCallback(async (query: string) => {
    const value = current.current
    if (!value) return
    const result = await voiceWorkspaces.tool(value.id, "search_knowledge", { query, scope: value.state.knowledge_scope })
    if (current.current?.id !== value.id) return
    if (!result.items || !result.gaps) throw new Error(t("voiceWorkspaceChat.operationError"))
    setKnowledge({ items: result.items, gaps: result.gaps }); await refresh()
  }, [refresh, t])
  const tool = useCallback(async (name: string, args: Record<string, unknown>, isCurrent: () => boolean = () => true) => {
    const ensureCurrent = () => { if (!isCurrent()) throw new Error(t("voiceWorkspaceChat.presentationError")) }
    ensureCurrent()
    if (name === "open_ingest_picker") { if (!picker) ready.current.delete("ingest-picker"); setPicker(true); await wait("ingest-picker"); ensureCurrent(); return { status: "completed" } }
    const value = await refresh()
    if (!value) throw new Error(t("voiceWorkspaceChat.loadError"))
    ensureCurrent()
    if (name === "show_document" || name === "focus_anchor") {
      if (name === "focus_anchor" && typeof args.reference_id !== "string") {
        const marked = await voiceWorkspaces.tool(value.id, "focus_passage", { source_id: requiredString(args, "source_id"), quote: requiredString(args, "quote").slice(0, 4000) })
        ensureCurrent()
        if (typeof marked.reference_id !== "string") throw new Error(t("voiceWorkspaceChat.presentationError"))
        args = { reference_id: marked.reference_id }
        await refresh()
        ensureCurrent()
      }
      if (name === "focus_anchor") {
        if (typeof args.reference_id === "string" && !(current.current ?? value).references.some((row) => row.reference_id === args.reference_id)) await loadReference(value.id, args.reference_id)
        try { workspaceFocusReference(current.current ?? value, args.reference_id) }
        catch { const message = t("voiceWorkspaceChat.anchorPositionRequired"); setError(message); throw new Error(message) }
      }
      setError(null)
      if (typeof args.reference_id === "string") await open(args.reference_id, isCurrent, true)
      else {
        const sourceId = requiredString(args, "source_id")
        if (!(current.current ?? value).sources.some((source) => source.id === sourceId)) {
          await voiceWorkspaces.tool(value.id, "ingest_source", { source_id: sourceId })
          ensureCurrent()
          await refresh()
          ensureCurrent()
        }
        ready.current.delete(`source:${sourceId}:`)
        await change((state) => ({ ...openWorkspaceDocument(state, sourceId, typeof args.page === "number" ? args.page : 1), active_artifact_id: null, selection: null }), isCurrent)
        await wait(`source:${sourceId}:`)
      }
    } else if (name === "show_evidence" || name === "show_knowledge") {
      const ids = Array.isArray(args.reference_ids) ? args.reference_ids.filter((id): id is string => typeof id === "string") : value.references.map((row) => row.reference_id)
      const items: SourceReference[] = []
      for (const id of ids) {
        const known = value.references.find((row) => row.reference_id === id) ?? current.current?.references.find((row) => row.reference_id === id)
        items.push(known ?? await loadReference(value.id, id))
      }
      ready.current.delete("evidence"); setKnowledge((previous) => ({ items, gaps: previous.gaps })); await change((state) => ({ ...state, view: "evidence" }), isCurrent); await wait("evidence")
    } else {
      const artifactId = requiredString(args, "artifact_id")
      const artifact = value.artifacts.find((row) => row.id === artifactId)
      if (!artifact || artifact.status !== "ready") throw new Error(t("voiceWorkspaceChat.notReady"))
      const view = artifact.kind === "relations" ? "relations" : artifact.kind === "comparison" ? "comparison" : "documents"
      ready.current.delete(`artifact:${artifact.id}:${artifact.revision}`)
      await change((state) => ({ ...state, view, active_artifact_id: artifact.id, selection: { artifact_id: artifact.id, artifact_revision: artifact.revision, ...(typeof args.node_id === "string" ? { node_id: args.node_id } : {}), ...(typeof args.edge_id === "string" ? { edge_id: args.edge_id } : {}) } }), isCurrent); await wait(`artifact:${artifact.id}:${artifact.revision}`)
    }
    return { status: "completed", workspace_revision: current.current?.revision }
  }, [change, loadReference, open, picker, refresh, t, wait])
  const saved = useCallback((artifact: WorkspaceArtifact) => { const value = current.current; if (!value) return; const artifacts = value.artifacts.map((row) => row.id === artifact.id ? artifact : row); current.current = { ...value, artifacts }; if (persisted.current?.id === value.id) persisted.current = { ...persisted.current, artifacts }; setWorkspace(current.current); if (value.state.selection?.artifact_id === artifact.id) void change((state) => ({ ...state, selection: { ...state.selection, artifact_revision: artifact.revision } })).catch(report) }, [change, report])
  const relevantJobs = jobs.filter((job) => job.request.voice_workspace_id === workspace?.id || workspace?.sources.some((source) => source.knowledge_job_id === job.id) || workspace?.research.some((research) => research.run_id === job.id || research.attempt_id === job.request.attempt_id))
  const jobContext = JSON.stringify(relevantJobs.map((job) => ({ id: job.id, status: job.status, error: job.error })))
  useEffect(() => { if (jobContext === "[]" || !current.current) return; void refresh().then((value) => { if (value) onContext.current(`Workspace background jobs updated: ${jobContext}`) }).catch(report) }, [jobContext, refresh, report])
  useEffect(() => {
    const artifactId = takeReadyGenerationArtifact({
      jobs, artifacts: workspace?.artifacts ?? [], workspaceId: workspace?.id,
      previousStatus: generationStatus.current, pending: pendingGeneration.current, opened: openedGeneration.current,
    })
    if (artifactId) void tool("show_artifact", { artifact_id: artifactId }).catch(report)
  }, [jobs, workspace, tool, report])
  return { workspace, list, knowledge, setKnowledge, error, picker, setPicker, setError, current, turnSnapshot, localSelection, selectDocument, snapshot, select, create, refresh, change, markReady, presentationError, open, search, tool, saved, report, onContext, queue }
}
