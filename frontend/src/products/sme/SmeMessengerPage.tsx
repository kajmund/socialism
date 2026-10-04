import { useCallback, useEffect, useRef, useState } from "react"
import { Plus } from "lucide-react"
import { listSmeInbox, markSmeThreadRead, type SmeInboxFilter, type SmeInboxItem } from "@/api/sme"
import { voiceWorkspaces, type KnowledgeScope, type WorkspaceMessage } from "@/api/voiceWorkspaces"
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
import { SmeResearchJobsButton } from "./SmeResearchJobsButton"
import { SmeUserMenu } from "./SmeUserMenu"
import { SmeResearchDialog } from "./SmeResearchDialog"
import { SmeWorkspaceSelector, type SmeWorkspaceParent } from "./SmeWorkspaceSelector"
import { WorkspaceResearch } from "./WorkspaceResearch"
import { WorkspaceCanvas } from "./WorkspaceCanvas"
import { WorkspaceSourceButtons } from "./WorkspaceSourceButtons"
import { useWorkspace } from "./useWorkspace"
import { useWorkspaceConversation } from "./useWorkspaceConversation"
import { useVoiceWorkspaceInbox } from "./useVoiceWorkspaceInbox"
import { upsertTranscript, workspaceErrorMessage } from "./workspaceChatLogic"

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
  const selectionWorkspace = useRef<string | null>(null)
  const selectedId = selected?.thread_type === "expert" ? selected.thread_id : null
  const nativeInbox = useVoiceWorkspaceInbox(workspaceId, selectedId, metadata)
  const { items: inbox, selection: inboxSelection, historyLoaded: inboxHistoryLoaded, report: reportInbox } = nativeInbox
  const loadInbox = useCallback(async () => { const rows = await listSmeInbox("all"); setMetadata(rows) }, [])
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
    setMessages([]); setPreview(null); setChatError(null); setLoading(false)
    if (!workspaceId || !selectedId) return
    let cancelled = false
    const selection = inboxSelection()
    setLoading(true)
    void voiceWorkspaces.messages(workspaceId, selectedId).then((result) => { if (!cancelled) { setMessages(result.messages); void inboxHistoryLoaded(selection).catch(reportInbox) } }).catch((error: unknown) => { if (!cancelled) setChatError(workspaceErrorMessage(error, t, "voiceWorkspaceChat.sessionError")) }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [workspaceId, selectedId, t, inboxSelection, inboxHistoryLoaded, reportInbox])
  useEffect(() => { if (workspaceId && workspaceCurrent.current?.state.language !== locale) void changeWorkspace((state) => ({ ...state, language: locale })).catch(reportWorkspace) }, [workspaceId, locale, changeWorkspace, workspaceCurrent, reportWorkspace])
  const conversation = useWorkspaceConversation({ workspaceId: workspace?.id ?? null, expertId: selected?.thread_type === "expert" ? selected.thread_id : null, snapshot: () => model.turnSnapshot.current ? structuredClone(model.turnSnapshot.current) : null, onMessage: (message) => { setMessages((current) => upsertTranscript(current, message)); void nativeInbox.persisted(message).catch(nativeInbox.report) }, onPreview: setPreview, onTool: (name, args, isCurrent) => { if (name !== "open_ingest_picker") setMobileView("workspace"); return model.tool(name, args, isCurrent) }, onServerResult: (name, result) => { if (name === "search_knowledge" && result.items && result.gaps) model.setKnowledge({ items: result.items, gaps: result.gaps }); void model.refresh().catch(model.report) }, onError: setChatError })
  model.onContext.current = conversation.contextualUpdate
  async function selectExpert(item: SmeInboxItem) { await conversation.stop(); setSelected(item); if (item.thread_type === "panel") { setVisitedPanels((ids) => ids.includes(item.thread_id) ? ids : [...ids, item.thread_id]); await markSmeThreadRead("panel", item.thread_id); await loadInbox() } else await model.change((state) => ({ ...state, expert_id: item.thread_id })) }
  async function send(text: string) {
    setSending(true); setChatError(null)
    try { await model.queue.current; if (selected && model.current.current?.state.expert_id !== selected.thread_id) await model.change((state) => ({ ...state, expert_id: selected.thread_id })); await conversation.send(text) }
    catch (error) { setChatError(workspaceErrorMessage(error, t, "voiceWorkspaceChat.sessionError")); throw error }
    finally { setSending(false) }
  }
  async function voice() { setChatError(null); try { if (conversation.voice) await conversation.stop(); else { if (selected && model.current.current?.state.expert_id !== selected.thread_id) await model.change((state) => ({ ...state, expert_id: selected.thread_id })); await conversation.start("voice") } } catch (error) { setChatError(workspaceErrorMessage(error, t, "voiceWorkspaceChat.sessionError")) } }
  const sourceStatus = (status: string | null | undefined) => status === "ready" ? t("voiceWorkspaceChat.completed") : status === "partial" ? t("underlag.knowledge.partial") : status === "failed" ? t("voiceWorkspaceChat.failed") : status === "needs_ocr" ? t("voiceWorkspaceChat.readability") : status === "empty" ? t("underlag.status.empty") : t("voiceWorkspaceChat.processing")
  const openReference = (id: string) => { setMobileView("workspace"); void model.open(id).catch(model.report) }
  return <div className="theme-admin flex h-dvh min-h-0 flex-col bg-db-ink-50 font-sans text-[color:var(--text-body)]">
    <header className="flex h-16 shrink-0 items-center bg-db-ink-950 px-4 text-white sm:px-6"><img src="/devbrains-logo-white.png" alt="Devbrains" className="h-6 w-auto sm:h-8" /><span className="mx-4 hidden h-6 w-px bg-white/20 sm:block" aria-hidden="true" /><span className="hidden text-sm text-white/80 sm:block">{t("sme.productName")}</span><div className="ml-auto flex items-center gap-1 sm:gap-2"><SmeResearchJobsButton /><SmeJobsButton /><LocaleSwitcher locale={locale} setLocale={setLocale} t={t} /><SmeUserMenu /></div></header>
    <SmeWorkspaceSelector parent={parent} onChange={setParent} beforeChange={conversation.stop} />
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-white px-4 py-3"><select className="max-w-52 rounded-lg border bg-white px-3 py-2 text-sm font-medium" aria-label={t("voiceWorkspaceChat.select")} value={workspace?.id ?? ""} onChange={(event) => { void conversation.stop(); void model.select(event.target.value).catch(model.report) }}><option value="" disabled>{t("voiceWorkspaceChat.select")}</option>{model.list.map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}</select><button type="button" className="grid size-9 place-items-center rounded-lg border" aria-label={t("voiceWorkspaceChat.new")} disabled={!parent} onClick={() => setNewOpen(true)}><Plus size={17} /></button>{workspace ? <><span className="hidden text-xs text-muted-foreground sm:block">{t("voiceWorkspaceChat.sourceCount", { count: workspace.sources.length })}</span><AdminButton size="sm" variant="secondary" onClick={() => model.setPicker(true)}>{t("voiceWorkspaceChat.addSource")}</AdminButton>{parent ? <SmeResearchDialog key={workspace.id} workspace={workspace} parent={parent.workspace} onChanged={model.refresh} /> : null}<div className="ml-auto flex gap-1 rounded-lg bg-db-ink-100 p-1" role="group" aria-label={t("voiceWorkspaceChat.knowledge")}>{(["workspace", "general", "research"] as KnowledgeScope[]).map((scope) => <button key={scope} type="button" aria-pressed={workspace.state.knowledge_scope === scope} className={`rounded-md px-3 py-1.5 text-xs ${workspace.state.knowledge_scope === scope ? "bg-db-ink-950 font-medium text-db-gold-500" : "hover:bg-white"}`} onClick={() => { void model.change((state) => ({ ...state, knowledge_scope: scope })).catch(model.report) }}>{t(`voiceWorkspaceChat.${scope}`)}</button>)}</div></> : null}</div>
    {model.error ? <div className="shrink-0 border-b border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive" role="alert">{model.error}</div> : null}
    {workspace ? <><div className="flex shrink-0 gap-2 overflow-x-auto border-b bg-white px-4 py-2"><WorkspaceSourceButtons sources={workspace.sources} sourceStatus={sourceStatus} onOpen={(sourceId) => { setMobileView("workspace"); void model.tool("show_document", { source_id: sourceId }).catch(model.report) }} onRetry={async (sourceId) => { await voiceWorkspaces.tool(workspace.id, "ingest_source", { source_id: sourceId }); await model.refresh() }} onError={model.report} />{workspace.artifacts.map((artifact) => <button key={artifact.id} type="button" className="shrink-0 rounded-lg border border-db-gold-300 bg-db-gold-100 px-3 py-1.5 text-xs" title={artifact.error ?? artifact.title} disabled={artifact.status !== "ready"} onClick={() => { setMobileView("workspace"); void model.tool("show_artifact", { artifact_id: artifact.id }).catch(model.report) }}>{artifact.title} · {artifact.status === "ready" ? t("voiceWorkspaceChat.revision", { revision: artifact.revision }) : artifact.status === "failed" ? t("voiceWorkspaceChat.failed") : t("voiceWorkspaceChat.processing")}</button>)}</div><WorkspaceResearch workspace={workspace} onState={(change) => { void model.change(change).catch(model.report) }} /><div className="flex shrink-0 border-b bg-white p-1 md:hidden">{(["chat", "workspace"] as const).map((view) => <button key={view} type="button" className={`flex-1 rounded px-3 py-2 text-sm ${mobileView === view ? "bg-db-ink-950 text-white" : ""}`} onClick={() => setMobileView(view)}>{t(view === "chat" ? "voiceWorkspaceChat.showChat" : "voiceWorkspaceChat.showWorkspace")}</button>)}</div>
      <main className="flex min-h-0 flex-1"><SmeConversationList compact scopeLabel={parent?.workspace.name} filter={filter} items={inbox} selected={selected} search={search} loading={nativeInbox.loading} error={nativeInbox.error} onFilterChange={setFilter} onSearchChange={setSearch} onSelect={(item) => { void selectExpert(item).catch(model.report) }} onOpenExpertEditor={setExpertEditor} /><div className={`${mobileView === "chat" ? "flex" : "hidden"} min-h-0 min-w-0 flex-1 border-r md:flex md:w-[34%] md:min-w-[310px] md:max-w-[470px] md:flex-none`}>{visitedPanels.map((id) => { const panel = inbox.find((row) => row.thread_id === id && row.thread_type === "panel"); return panel ? <div key={id} className={selected?.thread_type === "panel" && selected.thread_id === id ? "flex min-h-0 min-w-0 flex-1" : "hidden"}><SmePanelPane thread={panel} /></div> : null })}<div className={selected?.thread_type === "panel" ? "hidden" : "flex min-h-0 min-w-0 flex-1"}><SmeChatPane workspaceId={workspace.id} parentWorkspaceId={workspace.workspace_id} headerAction={parent && selected?.thread_type === "expert" ? <SmeExpertInterviewButton expertId={selected.thread_id} expertName={selected.name} workspaceKind={parent.workspace.kind} customerId={workspace.customer_id} beforeOpen={conversation.stop} onSaved={() => { void loadInbox().catch(model.report) }} /> : undefined} thread={selected?.thread_type === "panel" ? null : selected} messages={messages} references={workspace.references} loading={loading} sending={sending} preview={preview} error={chatError} status={conversation.status} voice={conversation.voice} muted={conversation.muted} onSend={send} onVoice={() => void voice()} onMute={conversation.toggleMute} onIngest={() => model.setPicker(true)} onOpen={openReference} onEdit={() => setExpertEditor(selected)} onActivity={conversation.userActivity} notice={workspace.sources.some((source) => source.knowledge_status !== "ready") ? <span className="block text-xs text-muted-foreground">{workspace.sources.filter((source) => source.knowledge_status !== "ready").map((source) => `${source.filename}: ${sourceStatus(source.knowledge_status)}`).join(" · ")}</span> : undefined} /></div></div><div className={`${mobileView === "workspace" ? "flex" : "hidden"} min-h-0 min-w-0 flex-1 md:flex`}><WorkspaceCanvas workspace={workspace} knowledge={model.knowledge} onState={(change) => { void model.change(change).catch(model.report) }} onOpen={openReference} onReady={model.markReady} onError={model.presentationError} onSaved={model.saved} onSearch={(query) => { void model.search(query).catch(model.report) }} /></div></main><SmeIngestDialog workspace={workspace} open={model.picker} onOpenChange={model.setPicker} onChanged={model.refresh} onError={model.report} onReady={() => model.markReady("ingest-picker")} /></> : <main className="grid min-h-0 flex-1 place-items-center p-6 text-sm text-muted-foreground">{t("voiceWorkspaceChat.empty")}</main>}
    <Dialog open={newOpen} onOpenChange={setNewOpen}><DialogContent className="theme-admin max-w-md"><DialogHeader><DialogTitle>{t("voiceWorkspaceChat.new")}</DialogTitle></DialogHeader><form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); const title = String(new FormData(event.currentTarget).get("title") ?? "").trim(); if (title) void model.create(title).then(() => setNewOpen(false)).catch(model.report) }}><input className="rounded border p-3 text-sm" name="title" required maxLength={255} aria-label={t("voiceWorkspaceChat.name")} placeholder={t("voiceWorkspaceChat.name")} /><AdminButton type="submit">{t("voiceWorkspaceChat.create")}</AdminButton></form></DialogContent></Dialog>
    {expertEditor ? <SmeExpertEditorModal open expertId={expertEditor.thread_id} expertName={expertEditor.name} onClose={() => setExpertEditor(null)} onSaved={() => { void loadInbox().catch(model.report) }} /> : null}
  </div>
}
