import { useCallback, useEffect, useRef, useState } from "react"
import { Plus } from "lucide-react"
import { listPersonaMessages } from "@/api/personas"
import { listSmeInbox, markSmeThreadRead, type SmeInboxFilter, type SmeInboxItem } from "@/api/sme"
import { voiceWorkspaces, type KnowledgeScope, type WorkspaceMessage } from "@/api/voiceWorkspaces"
import { ExpertVoiceButton } from "@/components/chat/ExpertVoiceButton"
import { LocaleSwitcher } from "@/components/layout/LocaleSwitcher"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale } from "@/i18n"
import { SmePanelPane } from "./SmePanelPane"
import { SmeChatPane } from "./SmeChatPane"
import { SmeConversationList } from "./SmeConversationList"
import { SmeExpertEditorModal } from "./SmeExpertEditorModal"
import { SmeExpertInterviewButton } from "./SmeExpertInterviewButton"
import { SmeIngestDialog } from "./SmeIngestDialog"
import { SmeJobsButton } from "./SmeJobsButton"
import { SmeExpertPanelsButton } from "./SmeExpertPanelsButton"
import { SmeGraphButton } from "./SmeGraphButton"
import { SmeResearchJobsButton } from "./SmeResearchJobsButton"
import { SmeUserMenu } from "./SmeUserMenu"
import { SmeResearchDialog } from "./SmeResearchDialog"
import { SmeWorkspaceSelector, type SmeWorkspaceParent } from "./SmeWorkspaceSelector"
import { WorkspaceResearch } from "./WorkspaceResearch"
import { WorkspaceCanvas } from "./WorkspaceCanvas"
import { WorkspaceSourceButtons } from "./WorkspaceSourceButtons"
import { useWorkspace } from "./useWorkspace"
import { useExpertTextChat } from "./useExpertTextChat"
import { useLiveSpeechConversation } from "./useLiveSpeechConversation"
import { useVoiceWorkspaceInbox } from "./useVoiceWorkspaceInbox"
import { resolveDocumentMentions } from "./documentMentions"
import { acceptModelTraceWorkspace, appendModelTrace, type ModelTraceEntry } from "./modelTrace"
import { interviewTranscriptMessage, mergeTranscript, upsertTranscript, workspaceErrorMessage } from "./workspaceChatLogic"

export function SmeMessengerPage() {
  const { locale, setLocale, t } = useLocale()
  const [parent, setParent] = useState<SmeWorkspaceParent | null>(null)
  const model = useWorkspace(parent)
  const { workspace, change: changeWorkspace, current: workspaceCurrent, report: reportWorkspace } = model
  const workspaceId = workspace?.id ?? null, savedExpertId = workspace?.state.expert_id ?? null
  const [metadata, setMetadata] = useState<SmeInboxItem[]>([])
  const [filter, setFilter] = useState<SmeInboxFilter>("all"), [search, setSearch] = useState("")
  const [selected, setSelected] = useState<SmeInboxItem | null>(null)
  const [messages, setMessages] = useState<WorkspaceMessage[]>([])
  const [preview, setPreview] = useState<string | null>(null)
  const [loading, setLoading] = useState(false), [sending, setSending] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)
  const [newOpen, setNewOpen] = useState(false), [mobileView, setMobileView] = useState<"chat" | "workspace">("chat")
  const [visitedPanels, setVisitedPanels] = useState<string[]>([])
  const [expertEditor, setExpertEditor] = useState<SmeInboxItem | null>(null)
  const [traces, setTraces] = useState<Record<string, ModelTraceEntry[]>>({})
  const selectionWorkspace = useRef<string | null>(null)
  const transcriptEpoch = useRef(0)
  const selectedId = selected?.thread_type === "expert" ? selected.thread_id : null
  const selectedExpert = useRef(selectedId)
  selectedExpert.current = selectedId
  const nativeInbox = useVoiceWorkspaceInbox(workspaceId, selectedId, metadata)
  const { items: inbox, selection: inboxSelection, historyLoaded: inboxHistoryLoaded, report: reportInbox } = nativeInbox
  const loadInbox = useCallback(async () => { const rows = await listSmeInbox("all"); setMetadata(rows); return rows }, [])
  useEffect(() => { void loadInbox().catch(model.report) }, [loadInbox, model.report])
  useEffect(() => {
    if (!workspaceId) return
    const sameWorkspace = selectionWorkspace.current === workspaceId
    selectionWorkspace.current = workspaceId
    setSelected((previous) => sameWorkspace && previous
      ? inbox.find((row) => row.thread_type === previous.thread_type && row.thread_id === previous.thread_id) ?? null
      : inbox.find((row) => row.thread_type === "expert" && row.thread_id === savedExpertId) ?? inbox.find((row) => row.thread_type === "expert") ?? null)
  }, [workspaceId, savedExpertId, inbox])
  useEffect(() => {
    const epoch = ++transcriptEpoch.current
    setMessages([]); setPreview(null); setChatError(null); setLoading(false)
    if (!workspaceId || !selectedId) return
    let cancelled = false
    const selection = inboxSelection()
    setLoading(true)
    void Promise.all([voiceWorkspaces.messages(workspaceId, selectedId), listPersonaMessages(selectedId, "character")]).then(([result, interview]) => { if (!cancelled && transcriptEpoch.current === epoch) { setMessages(mergeTranscript(result.messages, interview.map((row) => interviewTranscriptMessage(row)))); void inboxHistoryLoaded(selection).catch(reportInbox) } }).catch((error: unknown) => { if (!cancelled && transcriptEpoch.current === epoch) setChatError(workspaceErrorMessage(error, t, "voiceWorkspaceChat.sessionError")) }).finally(() => { if (!cancelled && transcriptEpoch.current === epoch) setLoading(false) })
    return () => { cancelled = true }
  }, [workspaceId, selectedId, t, inboxSelection, inboxHistoryLoaded, reportInbox])
  useEffect(() => { if (workspaceId && workspaceCurrent.current?.state.language !== locale) void changeWorkspace((state) => ({ ...state, language: locale })).catch(reportWorkspace) }, [workspaceId, locale, changeWorkspace, workspaceCurrent, reportWorkspace])
  const conversation = useLiveSpeechConversation({ workspaceId: workspace?.id ?? null, expertId: selected?.thread_type === "expert" ? selected.thread_id : null, onMessage: (message) => { setMessages((current) => upsertTranscript(current, message)); void nativeInbox.persisted(message).catch(nativeInbox.report) }, onPreview: setPreview, onTool: (name, args, isCurrent) => { if (name !== "open_ingest_picker") setMobileView("workspace"); return model.tool(name, args, isCurrent) }, onError: setChatError, onModelTrace: (entry) => { const threadId = selectedExpert.current; if (threadId) setTraces((current) => ({ ...current, [threadId]: appendModelTrace(current[threadId] ?? [], entry) })) } })
  const stopConversation = conversation.stop
  useEffect(() => {
    if (selected?.live_voice_provider !== "socialism") void stopConversation()
  }, [stopConversation, selected?.live_voice_provider])
  model.onContext.current = conversation.contextualUpdate
  const textChat = useExpertTextChat({
    onMessages: (threadId, incoming) => { if (selectedExpert.current === threadId) setMessages((current) => mergeTranscript(current, incoming)) },
    onPreview: (threadId, text) => { if (selectedExpert.current === threadId) setPreview(text) },
    onError: setChatError,
    onWorkspaceTool: (threadId, name, args) => {
      if (selectedExpert.current !== threadId) return
      void model.tool(name, args).catch((error: unknown) => setChatError(workspaceErrorMessage(error, t, "voiceWorkspaceChat.presentationError")))
    },
    onModelTrace: (threadId, traceWorkspaceId, entry) => {
      if (!acceptModelTraceWorkspace(traceWorkspaceId, workspaceCurrent.current?.id)) return
      setTraces((current) => ({ ...current, [threadId]: appendModelTrace(current[threadId] ?? [], entry) }))
    },
  })
  async function selectExpert(item: SmeInboxItem) { await conversation.stop(); setSelected(item); if (item.thread_type === "panel") { setVisitedPanels((ids) => ids.includes(item.thread_id) ? ids : [...ids, item.thread_id]); await markSmeThreadRead("panel", item.thread_id); await loadInbox() } else await model.change((state) => ({ ...state, expert_id: item.thread_id })) }
  async function send(text: string) {
    if (!selectedId || !workspace) return
    if (conversation.voice) conversation.cancelForText()
    const snapshot = await model.snapshot()
    if (!snapshot || snapshot.workspaceId !== workspace.id) throw new Error(t("voiceWorkspaceChat.sessionError"))
    if (model.current.current?.state.expert_id !== selectedId) void model.change((state) => ({ ...state, expert_id: selectedId }))
    const local: WorkspaceMessage = { id: -Date.now(), role: "user", content: text, created_at: new Date().toISOString(), event_key: `local:${crypto.randomUUID()}`, session_id: "local" }
    setMessages((current) => [...current, local])
    setSending(true); setChatError(null); setPreview(null)
    const document_mentions = resolveDocumentMentions(text, workspace.sources)
    try { await textChat.send(selectedId, text, { id: snapshot.workspaceId, state: { ...snapshot.state, document_mentions } }) }
    catch (error) { setMessages((current) => current.filter((row) => row.id !== local.id)); setPreview(null); setChatError(workspaceErrorMessage(error, t, "sme.chatError")); throw error }
    finally { setSending(false) }
  }
  async function clearChat() {
    if (!selectedId || !workspace) return
    const scope = { workspaceId: workspace.id, expertId: selectedId }
    const epoch = ++transcriptEpoch.current
    await conversation.stop()
    await voiceWorkspaces.clearMessages(scope.workspaceId, scope.expertId)
    if (transcriptEpoch.current !== epoch || selectedExpert.current !== scope.expertId) return
    setMessages([]); setPreview(null); setChatError(null)
    await nativeInbox.refresh(scope.workspaceId)
  }
  async function voice() { setChatError(null); try { if (selected?.live_voice_provider !== "socialism") return; if (conversation.voice) await conversation.stop(); else { if (model.current.current?.state.expert_id !== selected.thread_id) await model.change((state) => ({ ...state, expert_id: selected.thread_id })); await conversation.start("voice") } } catch (error) { setChatError(workspaceErrorMessage(error, t, "voiceWorkspaceChat.sessionError")) } }
  const voiceControl = selected?.thread_type === "expert" && selected.live_voice_provider !== "socialism"
    ? <ExpertVoiceButton personaId={selected.thread_id} expertName={selected.name} avatarUrl={selected.avatar_url} onErrorMessage={setChatError} onTranscript={(personaId, incoming) => { if (selectedExpert.current === personaId) setMessages((current) => mergeTranscript(current, incoming.map(interviewTranscriptMessage))) }} />
    : undefined
  const sourceStatus = (status: string | null | undefined) => status === "ready" ? t("voiceWorkspaceChat.completed") : status === "partial" ? t("underlag.knowledge.partial") : status === "failed" ? t("voiceWorkspaceChat.failed") : status === "needs_ocr" ? t("voiceWorkspaceChat.readability") : status === "empty" ? t("underlag.status.empty") : t("voiceWorkspaceChat.processing")
  const openReference = (id: string) => { setMobileView("workspace"); void model.open(id).catch(model.report) }
  const openDraft = (draft: { artifactId: string; workspaceId: string }) => {
    setMobileView("workspace")
    void (async () => {
      if (model.current.current?.id !== draft.workspaceId) await model.select(draft.workspaceId)
      await model.tool("show_artifact", { artifact_id: draft.artifactId })
    })().catch(model.report)
  }
  const seenArtifact = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    const id = workspace?.state.active_artifact_id ?? null
    if (seenArtifact.current === undefined) { seenArtifact.current = id; return }
    if (id && id !== seenArtifact.current) setMobileView("workspace")
    seenArtifact.current = id
  }, [workspace?.state.active_artifact_id])
  return <div className="theme-admin flex h-dvh min-h-0 flex-col bg-db-ink-50 font-sans text-[color:var(--text-body)]">
    <header className="flex h-16 shrink-0 items-center bg-db-ink-950 px-4 text-white sm:px-6"><img src="/devbrains-logo-white.png" alt="Devbrains" className="h-6 w-auto sm:h-8" /><span className="mx-4 hidden h-6 w-px bg-white/20 sm:block" aria-hidden="true" /><span className="hidden text-sm text-white/80 sm:block">{t("sme.productName")}</span><div className="ml-auto flex items-center gap-1 sm:gap-2"><SmeExpertPanelsButton onClosed={() => { void loadInbox().catch(model.report) }} onStarted={(panelId) => { void loadInbox().then((rows) => { const panel = rows.find((row) => row.thread_type === "panel" && row.thread_id === String(panelId)); if (panel) return selectExpert(panel) }).catch(model.report) }} /><SmeGraphButton /><SmeResearchJobsButton /><SmeJobsButton onOpenWorkspaceArtifact={openDraft} /><LocaleSwitcher locale={locale} setLocale={setLocale} t={t} /><SmeUserMenu /></div></header>
    <SmeWorkspaceSelector parent={parent} onChange={setParent} beforeChange={conversation.stop} />
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-white px-4 py-3"><select className="max-w-52 rounded-lg border bg-white px-3 py-2 text-sm font-medium" aria-label={t("voiceWorkspaceChat.select")} value={workspace?.id ?? ""} onChange={(event) => { void conversation.stop(); void model.select(event.target.value).catch(model.report) }}><option value="" disabled>{t("voiceWorkspaceChat.select")}</option>{model.list.map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}</select><button type="button" className="grid size-9 place-items-center rounded-lg border" aria-label={t("voiceWorkspaceChat.new")} disabled={!parent} onClick={() => setNewOpen(true)}><Plus size={17} /></button>{workspace ? <><span className="hidden text-xs text-muted-foreground sm:block">{t("voiceWorkspaceChat.sourceCount", { count: workspace.sources.length })}</span><AdminButton size="sm" variant="secondary" onClick={() => model.setPicker(true)}>{t("voiceWorkspaceChat.addSource")}</AdminButton>{parent ? <SmeResearchDialog key={workspace.id} workspace={workspace} parent={parent.workspace} onChanged={model.refresh} /> : null}<div className="ml-auto flex gap-1 rounded-lg bg-db-ink-100 p-1" role="group" aria-label={t("voiceWorkspaceChat.knowledge")}>{(["workspace", "general", "research"] as KnowledgeScope[]).map((scope) => <button key={scope} type="button" aria-pressed={workspace.state.knowledge_scope === scope} className={`rounded-md px-3 py-1.5 text-xs ${workspace.state.knowledge_scope === scope ? "bg-db-ink-950 font-medium text-db-gold-500" : "hover:bg-white"}`} onClick={() => { void model.change((state) => ({ ...state, knowledge_scope: scope })).catch(model.report) }}>{t(`voiceWorkspaceChat.${scope}`)}</button>)}</div></> : null}</div>
    {model.error ? <div className="shrink-0 border-b border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive" role="alert">{model.error}</div> : null}
    {workspace ? <><div className="flex shrink-0 gap-2 overflow-x-auto border-b bg-white px-4 py-2"><WorkspaceSourceButtons sources={workspace.sources} sourceStatus={sourceStatus} onOpen={(sourceId) => { setMobileView("workspace"); void model.tool("show_document", { source_id: sourceId }).catch(model.report) }} onRetry={async (sourceId) => { await voiceWorkspaces.tool(workspace.id, "ingest_source", { source_id: sourceId }); await model.refresh() }} onError={model.report} />{workspace.artifacts.map((artifact) => <button key={artifact.id} type="button" className="shrink-0 rounded-lg border border-db-gold-300 bg-db-gold-100 px-3 py-1.5 text-xs" title={artifact.error ?? artifact.title} disabled={artifact.status !== "ready"} onClick={() => { setMobileView("workspace"); void model.tool("show_artifact", { artifact_id: artifact.id }).catch(model.report) }}>{artifact.title} · {artifact.status === "ready" ? t("voiceWorkspaceChat.revision", { revision: artifact.revision }) : artifact.status === "failed" ? t("voiceWorkspaceChat.failed") : t("voiceWorkspaceChat.processing")}</button>)}</div><WorkspaceResearch workspace={workspace} onState={(change) => { void model.change(change).catch(model.report) }} /><div className="flex shrink-0 border-b bg-white p-1 md:hidden">{(["chat", "workspace"] as const).map((view) => <button key={view} type="button" className={`flex-1 rounded px-3 py-2 text-sm ${mobileView === view ? "bg-db-ink-950 text-white" : ""}`} onClick={() => setMobileView(view)}>{t(view === "chat" ? "voiceWorkspaceChat.showChat" : "voiceWorkspaceChat.showWorkspace")}</button>)}</div>
      <main className="flex min-h-0 flex-1"><SmeConversationList compact scopeLabel={parent?.workspace.name} filter={filter} items={inbox} selected={selected} search={search} loading={nativeInbox.loading} error={nativeInbox.error} onFilterChange={setFilter} onSearchChange={setSearch} onSelect={(item) => { void selectExpert(item).catch(model.report) }} onOpenExpertEditor={setExpertEditor} /><div className={`${mobileView === "chat" ? "flex" : "hidden"} min-h-0 min-w-0 flex-1 border-r md:flex md:w-[34%] md:min-w-[310px] md:max-w-[470px] md:flex-none`}>{visitedPanels.map((id) => { const panel = inbox.find((row) => row.thread_id === id && row.thread_type === "panel"); return panel ? <div key={id} className={selected?.thread_type === "panel" && selected.thread_id === id ? "flex min-h-0 min-w-0 flex-1" : "hidden"}><SmePanelPane thread={panel} onCleared={() => { void loadInbox().catch(model.report) }} /></div> : null })}<div className={selected?.thread_type === "panel" ? "hidden" : "flex min-h-0 min-w-0 flex-1"}><SmeChatPane workspaceId={workspace.id} parentWorkspaceId={workspace.workspace_id} headerAction={parent && selected?.thread_type === "expert" ? <SmeExpertInterviewButton expertId={selected.thread_id} expertName={selected.name} workspaceKind={parent.workspace.kind} customerId={workspace.customer_id} beforeOpen={conversation.stop} onSaved={() => { void loadInbox().catch(model.report) }} /> : undefined} thread={selected?.thread_type === "panel" ? null : selected} messages={messages} references={workspace.references} sources={workspace.sources} loading={loading} sending={sending} preview={preview} error={chatError} status={conversation.status} voice={conversation.voice} muted={conversation.muted} onSend={send} onVoice={() => void voice()} onMute={conversation.toggleMute} onCancel={() => conversation.cancel()} onIngest={() => model.setPicker(true)} onOpen={openReference} onEdit={() => setExpertEditor(selected)} onActivity={conversation.userActivity} onClear={clearChat} voiceControl={voiceControl} notice={workspace.sources.some((source) => source.knowledge_status !== "ready") ? <span className="block text-xs text-muted-foreground">{workspace.sources.filter((source) => source.knowledge_status !== "ready").map((source) => `${source.filename}: ${sourceStatus(source.knowledge_status)}`).join(" · ")}</span> : undefined} /></div></div><div className={`${mobileView === "workspace" ? "flex" : "hidden"} min-h-0 min-w-0 flex-1 md:flex`}><WorkspaceCanvas workspace={workspace} knowledge={model.knowledge} localSelection={model.localSelection} trace={selectedId ? traces[selectedId] ?? [] : []} onSelection={model.selectDocument} onClearSelection={(sourceId) => model.selectDocument(sourceId, null)} onState={(change) => { void model.change(change).catch(model.report) }} onOpen={openReference} onReady={model.markReady} onError={model.presentationError} onSaved={model.saved} onSearch={(query) => { void model.search(query).catch(model.report) }} /></div></main><SmeIngestDialog workspace={workspace} open={model.picker} onOpenChange={model.setPicker} onChanged={model.refresh} onError={model.report} onReady={() => model.markReady("ingest-picker")} /></> : <main className="grid min-h-0 flex-1 place-items-center p-6 text-sm text-muted-foreground">{t("voiceWorkspaceChat.empty")}</main>}
    <Dialog open={newOpen} onOpenChange={setNewOpen}><DialogContent className="theme-admin max-w-md"><DialogHeader><DialogTitle>{t("voiceWorkspaceChat.new")}</DialogTitle></DialogHeader><form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); const title = String(new FormData(event.currentTarget).get("title") ?? "").trim(); if (title) void model.create(title).then(() => setNewOpen(false)).catch(model.report) }}><input className="rounded border p-3 text-sm" name="title" required maxLength={255} aria-label={t("voiceWorkspaceChat.name")} placeholder={t("voiceWorkspaceChat.name")} /><AdminButton type="submit">{t("voiceWorkspaceChat.create")}</AdminButton></form></DialogContent></Dialog>
    {expertEditor ? <SmeExpertEditorModal open expertId={expertEditor.thread_id} expertName={expertEditor.name} onClose={() => setExpertEditor(null)} onSaved={() => { void loadInbox().catch(model.report) }} /> : null}
  </div>
}
