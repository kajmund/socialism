import { useCallback, useEffect, useRef, useState } from "react"
import { voiceWorkspaces, type KnowledgeResult, type VoiceWorkspaceParent, type Workspace, type WorkspaceArtifact, type WorkspaceState, type WorkspaceSummary } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"
import { openWorkspaceDocument, requiredString, workspaceErrorMessage } from "./workspaceChatLogic"
import { workspaceFocusReference } from "./workspaceDocumentFocus"

export function useWorkspace(parent: VoiceWorkspaceParent | null) {
  const { t, locale } = useLocale()
  const { jobs } = useJobsRealtime()
  const [list, setList] = useState<WorkspaceSummary[]>([])
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [knowledge, setKnowledge] = useState<KnowledgeResult>({ items: [], gaps: [] })
  const [picker, setPicker] = useState(false)
  const current = useRef<Workspace | null>(null)
  const turnSnapshot = useRef<{ revision: number; state: WorkspaceState } | null>(null)
  const pendingChanges = useRef(0)
  const generation = useRef(0)
  const queue = useRef(Promise.resolve())
  const ready = useRef(new Set<string>())
  const pending = useRef(new Map<string, { resolve: () => void; reject: (error: Error) => void; timer: number }>())
  const onContext = useRef<(text: string) => void>(() => undefined)
  const report = useCallback((caught: unknown) => setError(workspaceErrorMessage(caught, t, "voiceWorkspaceChat.operationError")), [t])
  const labels = useRef(t), errors = useRef(report)
  labels.current = t; errors.current = report
  const apply = useCallback((value: Workspace) => { current.current = value; turnSnapshot.current = { revision: value.revision, state: pendingChanges.current && turnSnapshot.current ? turnSnapshot.current.state : value.state }; setWorkspace(value) }, [])
  const select = useCallback(async (id: string) => {
    const request = ++generation.current
    current.current = null; turnSnapshot.current = null; pendingChanges.current = 0; setWorkspace(null); ready.current.clear(); setKnowledge({ items: [], gaps: [] }); setError(null)
    for (const waiter of pending.current.values()) { window.clearTimeout(waiter.timer); waiter.reject(new Error(labels.current("voiceWorkspaceChat.presentationError"))) }
    pending.current.clear()
    const value = await voiceWorkspaces.get(id)
    if (request === generation.current) apply(value)
  }, [apply])
  const parentId = parent?.workspaceId, customerId = parent?.customerId
  useEffect(() => {
    let cancelled = false
    generation.current += 1
    current.current = null; turnSnapshot.current = null; pendingChanges.current = 0
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
    if (current.current?.id !== value.id || value.revision < current.current.revision) return null
    apply(value)
    return value
  }, [apply])
  const change = useCallback((update: (state: WorkspaceState) => WorkspaceState, isCurrent: () => boolean = () => true): Promise<Workspace> => {
    const id = current.current?.id, epoch = generation.current
    if (current.current && isCurrent()) { const previous = turnSnapshot.current?.state ?? current.current.state; turnSnapshot.current = { revision: current.current.revision, state: update(previous) }; pendingChanges.current += 1 }
    const task = queue.current.then(async () => {
      const previous = current.current
      if (!previous || previous.id !== id || epoch !== generation.current || !isCurrent()) throw new Error(t("voiceWorkspaceChat.loadError"))
      const value = await voiceWorkspaces.update(previous.id, previous.revision, update(previous.state))
      if (epoch !== generation.current) throw new Error(t("voiceWorkspaceChat.presentationError"))
      if (!isCurrent()) { if (current.current?.id === value.id) apply({ ...value, state: current.current.state }); throw new Error(t("voiceWorkspaceChat.presentationError")) }
      apply(value); setError(null); onContext.current(`Workspace state updated: ${JSON.stringify(value.state)}`)
      return value
    })
    const settled = task.finally(() => { if (epoch === generation.current) { pendingChanges.current = Math.max(0, pendingChanges.current - 1); if (!pendingChanges.current && current.current) turnSnapshot.current = { revision: current.current.revision, state: current.current.state } } })
    queue.current = settled.then(() => undefined, report)
    return settled
  }, [apply, report, t])
  const create = useCallback(async (title: string) => { if (!parentId) throw new Error(t("voiceWorkspaceChat.loadError")); const epoch = generation.current; const value = await voiceWorkspaces.create(title, locale, { workspaceId: parentId, customerId }); if (epoch !== generation.current) return; setList((rows) => [value, ...rows]); await select(value.id) }, [locale, parentId, customerId, select, t])
  const markReady = useCallback((key: string) => { ready.current.add(key); const waiter = pending.current.get(key); if (waiter) { window.clearTimeout(waiter.timer); pending.current.delete(key); waiter.resolve() } }, [])
  const presentationError = useCallback((key: string, message: string) => { ready.current.delete(key); setError(message); const waiter = pending.current.get(key); if (waiter) { window.clearTimeout(waiter.timer); pending.current.delete(key); waiter.reject(new Error(message)) } }, [])
  const wait = useCallback((key: string) => ready.current.has(key) ? Promise.resolve() : new Promise<void>((resolve, reject) => { const existing = pending.current.get(key); if (existing) { window.clearTimeout(existing.timer); existing.reject(new Error(t("voiceWorkspaceChat.presentationError"))) } const timer = window.setTimeout(() => { pending.current.delete(key); reject(new Error(t("voiceWorkspaceChat.presentationError"))) }, 20_000); pending.current.set(key, { resolve, reject, timer }) }), [t])
  useEffect(() => () => { for (const waiter of pending.current.values()) { window.clearTimeout(waiter.timer); waiter.reject(new Error(t("voiceWorkspaceChat.presentationError"))) } }, [t])
  const open = useCallback(async (referenceId: string, isCurrent: () => boolean = () => true) => {
    const value = await refresh()
    if (!isCurrent()) throw new Error(t("voiceWorkspaceChat.presentationError"))
    const reference = value?.references.find((row) => row.reference_id === referenceId)
    if (!reference) throw new Error(t("voiceWorkspaceChat.referenceUnavailable"))
    const verified = await voiceWorkspaces.reference(value!.id, referenceId)
    if (verified.stale) throw new Error(t("voiceWorkspaceChat.stale"))
    if (!isCurrent()) throw new Error(t("voiceWorkspaceChat.presentationError"))
    setError(null)
    const key = `source:${reference.source_id}:${reference.reference_id}`
    if (reference.source_kind !== "underlag") { ready.current.delete(key); await change((state) => ({ ...state, view: "documents", active_artifact_id: null, selection: { reference_id: referenceId } }), isCurrent); await wait(key); return }
    ready.current.delete(key)
    await change((state) => ({ ...openWorkspaceDocument(state, reference.source_id, reference.anchor?.page_number ?? 1), documents: openWorkspaceDocument(state, reference.source_id, reference.anchor?.page_number ?? 1).documents.map((row) => row.source_id === reference.source_id ? { ...row, reference_id: referenceId } : row), active_artifact_id: null, selection: { reference_id: referenceId } }), isCurrent)
    await wait(key)
  }, [change, refresh, t, wait])
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
      if (name === "focus_anchor") {
        try { workspaceFocusReference(value, args.reference_id) }
        catch { const message = t("voiceWorkspaceChat.anchorPositionRequired"); setError(message); throw new Error(message) }
      }
      setError(null)
      if (typeof args.reference_id === "string") await open(args.reference_id, isCurrent)
      else {
        const sourceId = requiredString(args, "source_id")
        ready.current.delete(`source:${sourceId}:`)
        await change((state) => ({ ...openWorkspaceDocument(state, sourceId, typeof args.page === "number" ? args.page : 1), active_artifact_id: null, selection: null }), isCurrent)
        await wait(`source:${sourceId}:`)
      }
    } else if (name === "show_evidence" || name === "show_knowledge") {
      const ids = Array.isArray(args.reference_ids) ? args.reference_ids.filter((id): id is string => typeof id === "string") : value.references.map((row) => row.reference_id)
      const items = ids.map((id) => { const reference = value.references.find((row) => row.reference_id === id); if (!reference) throw new Error(t("voiceWorkspaceChat.referenceUnavailable")); return reference })
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
  }, [change, open, picker, refresh, t, wait])
  const saved = useCallback((artifact: WorkspaceArtifact) => { const value = current.current; if (value) { apply({ ...value, artifacts: value.artifacts.map((row) => row.id === artifact.id ? artifact : row) }); if (value.state.selection?.artifact_id === artifact.id) void change((state) => ({ ...state, selection: { ...state.selection, artifact_revision: artifact.revision } })).catch(report) } }, [apply, change, report])
  const relevantJobs = jobs.filter((job) => job.request.voice_workspace_id === workspace?.id || workspace?.sources.some((source) => source.knowledge_job_id === job.id) || workspace?.research.some((research) => research.run_id === job.id || research.attempt_id === job.request.attempt_id))
  const jobContext = JSON.stringify(relevantJobs.map((job) => ({ id: job.id, status: job.status, error: job.error })))
  useEffect(() => { if (jobContext === "[]" || !current.current) return; void refresh().then((value) => { if (value) onContext.current(`Workspace background jobs updated: ${jobContext}`) }).catch(report) }, [jobContext, refresh, report])
  return { workspace, list, knowledge, setKnowledge, error, picker, setPicker, setError, current, turnSnapshot, select, create, refresh, change, markReady, presentationError, open, search, tool, saved, report, onContext, queue }
}
