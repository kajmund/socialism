import { useEffect, useRef, useState } from "react"
import { ArrowLeft, Building2, FileCheck2, FileClock, FileWarning, LoaderCircle, Microscope, Paperclip, Plus } from "lucide-react"
import { listKunder, type Kund } from "@/api/kunder"
import { createClientWorkspace, sendWorkspaceMessage, startWorkspaceResearch, uploadWorkspaceFile, type WorkspaceCitation } from "@/api/workspaces"
import { useAuth } from "@/auth/AuthProvider"
import { MessengerChat } from "@/components/chat/MessengerChat"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Markdown } from "@/components/ui/markdown"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { WorkspaceResearchDialog } from "./WorkspaceResearchDialog"
import { WorkspaceSourceDialog } from "./WorkspaceSourceDialog"
import { useWorkspaceChat } from "./useWorkspaceChat"
import { safeSourceUrl, workspaceFileState } from "./workspaceChatState"
import { linkWorkspaceCitations } from "./workspaceCitations"

const jobStatusKeys = {
  pending: "workspaceChat.researchPending",
  running: "workspaceChat.researchRunning",
  succeeded: "workspaceChat.researchSucceeded",
  failed: "workspaceChat.researchFailed",
} as const

export function WorkspaceChatPanel({ personaId, personaName, onBack, className = "" }: {
  personaId?: string
  personaName?: string
  onBack?: () => void
  className?: string
}) {
  const { user, isAdmin } = useAuth()
  const { t } = useLocale()
  const requiresCustomer = isAdmin && user?.kundId == null
  const [customers, setCustomers] = useState<Kund[]>([])
  const [customerId, setCustomerId] = useState<number | undefined>(undefined)
  const model = useWorkspaceChat(customerId, !requiresCustomer || customerId != null, personaId)
  const setError = model.setError
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState<string | null>(null)
  const [workspaceOpen, setWorkspaceOpen] = useState(false)
  const [workspaceName, setWorkspaceName] = useState("")
  const [researchOpen, setResearchOpen] = useState(false)
  const [citation, setCitation] = useState<WorkspaceCitation | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const workspace = model.workspaces.find((row) => row.id === model.workspaceId) ?? null

  useEffect(() => {
    if (!requiresCustomer) return
    let cancelled = false
    void listKunder().then((rows) => { if (!cancelled) setCustomers(rows) }).catch((err: unknown) => {
      if (!cancelled) setError(err instanceof ApiError ? err.message : t("workspaceChat.loadError"))
    })
    return () => { cancelled = true }
  }, [requiresCustomer, setError, t])

  useEffect(() => {
    setDraft("")
    setResearchOpen(false)
    setCitation(null)
  }, [model.workspaceId, customerId, personaId, model.chat?.id])

  function fail(err: unknown, key: "workspaceChat.actionError" | "workspaceChat.uploadError" = "workspaceChat.actionError") {
    model.setError(err instanceof ApiError ? err.message : t(key))
  }

  async function ensureChat() {
    return model.chat ?? await model.newChat()
  }

  async function send() {
    if (!draft.trim() || busy || !workspace) return
    const content = draft.trim()
    let submitted = false
    setBusy(true)
    model.setError(null)
    try {
      const current = await ensureChat()
      setDraft("")
      const updated = await sendWorkspaceMessage(current.id, content, customerId)
      submitted = true
      model.replaceChat(updated)
      await model.refresh(current.id)
    } catch (err) {
      if (!submitted) setDraft(content)
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  async function upload(files: File[]) {
    if (busy || !workspace || files.length === 0) return
    if (files.some((file) => !/\.(pdf|docx|txt|md)$/i.test(file.name))) {
      model.setError(t("workspaceChat.unsupportedFile"))
      return
    }
    setBusy(true)
    model.setError(null)
    try {
      const current = await ensureChat()
      for (const file of files) {
        setUploading(file.name)
        const uploaded = await uploadWorkspaceFile(current.id, file, customerId)
        model.addFile(uploaded)
        await model.refresh(current.id)
      }
    } catch (err) {
      fail(err, "workspaceChat.uploadError")
    } finally {
      setUploading(null)
      setBusy(false)
    }
  }

  async function openResearch() {
    if (busy || !workspace) return
    setBusy(true)
    model.setError(null)
    try {
      const current = await ensureChat()
      await model.refresh(current.id)
      setResearchOpen(true)
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  async function startResearch(question: string, ids: string[]): Promise<boolean> {
    if (busy || !workspace) return false
    setBusy(true)
    model.setError(null)
    try {
      const current = await ensureChat()
      await startWorkspaceResearch(current.id, question, ids, customerId)
      await model.refresh(current.id)
      return true
    } catch (err) {
      fail(err)
      return false
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={`flex h-full min-h-0 min-w-0 flex-1 flex-col bg-db-ink-0 ${className}`} onClick={(event) => {
      const target = event.target instanceof Element ? event.target.closest("a[href]") : null
      if (!target || !model.chat) return
      let url: URL
      try {
        url = new URL(target.getAttribute("href") ?? "", window.location.origin)
      } catch {
        return
      }
      const prefix = `/workspace-chats/${model.chat.id}/sources/`
      if (!url.pathname.startsWith(prefix)) return
      event.preventDefault()
      const objectId = decodeURIComponent(url.pathname.slice(prefix.length))
      const versionId = url.searchParams.get("document_version_id")
      const unitId = url.searchParams.get("text_unit_id")
      const known = model.jobs.flatMap((job) => job.result?.citations ?? []).find((source) => source.source_object_id === objectId && source.document_version_id === versionId && source.text_unit_id === unitId)
      setCitation(known ?? { label: target.textContent ?? "", source_object_id: objectId, document_version_id: versionId, text_unit_id: unitId, excerpt: "" })
    }}>
      <header className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[color:var(--border-hairline)] px-4 py-3">
        {onBack ? <button type="button" className="grid size-8 place-items-center rounded hover:bg-db-ink-100 md:hidden" aria-label={t("sme.back")} onClick={onBack}><ArrowLeft size={18} aria-hidden="true" /></button> : null}
        <Building2 size={18} className="shrink-0 text-db-gold-500" aria-hidden="true" />
        {requiresCustomer ? (
          <label className="min-w-0">
            <span className="sr-only">{t("workspaceChat.organization")}</span>
            <select value={customerId ?? ""} disabled={busy} onChange={(event) => setCustomerId(event.target.value ? Number(event.target.value) : undefined)} className="max-w-48 rounded border border-[color:var(--border-hairline)] bg-db-ink-50 p-2 text-sm">
              <option value="">{t("workspaceChat.chooseOrganization")}</option>
              {customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}
            </select>
          </label>
        ) : null}
        <label className="min-w-0 flex-1">
          <span className="sr-only">{t("workspaceChat.workspace")}</span>
          <select value={model.workspaceId ?? ""} disabled={busy || model.loading || !model.workspaces.length} onChange={(event) => model.setWorkspaceId(event.target.value)} className="w-full rounded border border-[color:var(--border-hairline)] bg-db-ink-50 p-2 text-sm">
            {!model.workspaces.length ? <option value="">{t("workspaceChat.company")}</option> : null}
            {model.workspaces.map((row) => <option key={row.id} value={row.id}>{row.name}{row.kind === "company" ? ` · ${t("workspaceChat.company")}` : ""}</option>)}
          </select>
        </label>
        <AdminButton variant="secondary" size="sm" disabled={busy || !workspace} onClick={() => { setWorkspaceName(""); setWorkspaceOpen(true) }} aria-label={t("workspaceChat.newWorkspace")}><Plus size={16} aria-hidden="true" /><span className="hidden sm:inline">{t("workspaceChat.newWorkspace")}</span></AdminButton>
      </header>
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[color:var(--border-hairline)] px-4 py-2">
        <label className="min-w-0 flex-1">
          <span className="sr-only">{t("workspaceChat.conversation")}</span>
          <select value={model.chat?.id ?? ""} disabled={busy || model.loading} onChange={(event) => model.selectChat(event.target.value)} className="w-full bg-transparent text-sm outline-none">
            {!model.chat ? <option value="">{t("workspaceChat.untitledChat")}</option> : null}
            {model.chats.map((row) => <option key={row.id} value={row.id}>{row.title || t("workspaceChat.untitledChat")}</option>)}
          </select>
        </label>
        {personaName ? <span className="text-xs text-[color:var(--text-muted)]">{personaName}</span> : null}
        <AdminButton variant="secondary" size="sm" disabled={busy || !workspace} onClick={() => {
          setBusy(true)
          model.setError(null)
          void model.newChat().catch(fail).finally(() => setBusy(false))
        }}>{t("workspaceChat.newChat")}</AdminButton>
      </div>
      <p className="shrink-0 border-b border-[color:var(--border-hairline)] bg-db-ink-50 px-4 py-2 text-xs text-[color:var(--text-muted)]">{t(workspace?.kind === "client" ? "workspaceChat.clientIntro" : "workspaceChat.companyIntro")}</p>
      <MessengerChat
        messages={(model.chat?.messages ?? []).map((message) => ({
          ...message,
          content: message.role === "assistant" && message.job_id && model.chat
            ? linkWorkspaceCitations(message.content, model.chat.id, model.jobs.find((job) => job.id === message.job_id)?.result?.citations ?? [])
            : message.content,
        }))}
        draft={draft}
        renderMessageContent={(message) => message.role === "assistant" ? <Markdown content={message.content} /> : undefined}
        onDraftChange={setDraft}
        onSend={() => void send()}
        busy={busy}
        disabled={!workspace || model.loading}
        typing={busy && !uploading && !researchOpen}
        placeholder={t("workspaceChat.placeholder")}
        empty={<p className="bub them">{t("workspaceChat.empty")}</p>}
        notice={<>
          {uploading ? <span role="status">{t("workspaceChat.uploading", { name: uploading })}</span> : null}
          {model.error ? <span role="alert" className="text-destructive">{model.error}</span> : null}
        </>}
        inputAction={<>
          <input ref={inputRef} type="file" multiple accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown" className="hidden" onChange={(event) => {
            const files = Array.from(event.target.files ?? [])
            event.target.value = ""
            void upload(files)
          }} />
          <AdminButton variant="secondary" size="sm" disabled={busy || !workspace || model.loading} aria-label={t("workspaceChat.attach")} title={t("workspaceChat.attach")} onClick={() => inputRef.current?.click()}><Paperclip size={18} aria-hidden="true" /></AdminButton>
          <AdminButton variant="secondary" size="sm" disabled={busy || !workspace || model.loading} aria-label={t("workspaceChat.startResearch")} title={t("workspaceChat.startResearch")} onClick={() => void openResearch()}><Microscope size={18} aria-hidden="true" /></AdminButton>
        </>}
        threadContent={<>
          {model.files.length ? <div className="my-3 rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-50 p-3">
            <h3 className="mb-2 text-xs font-medium text-[color:var(--text-muted)]">{t("workspaceChat.files")}</h3>
            <ul className="grid gap-2">{model.files.map((file) => {
              const status = workspaceFileState(file)
              return <li key={file.id} className="flex items-start gap-2 text-sm">
                {status === "ready" ? <FileCheck2 size={17} className="mt-0.5 text-db-gold-500" /> : status === "failed" ? <FileWarning size={17} className="mt-0.5 text-destructive" /> : <FileClock size={17} className="mt-0.5 text-[color:var(--text-muted)]" />}
                <span className="min-w-0"><span className="block break-words">{file.filename}</span><span className="block text-xs text-[color:var(--text-muted)]">{t(`workspaceChat.${status}`)}{file.workspace_id !== workspace?.id ? ` · ${t("workspaceChat.companyFile")}` : ""}</span>{file.knowledge_error ? <span className="block text-xs text-destructive">{file.knowledge_error}</span> : null}</span>
              </li>
            })}</ul>
          </div> : null}
          {model.jobs.map((job) => <article key={job.id} className="my-3 rounded-lg border border-[color:var(--border-hairline)] p-3">
            <div className="flex items-start gap-2">
              {job.status === "running" || job.status === "pending" ? <LoaderCircle size={17} className="mt-0.5 animate-spin text-db-gold-500" /> : <Microscope size={17} className="mt-0.5 text-db-gold-500" />}
              <div className="min-w-0"><h3 className="break-words text-sm font-medium">{job.label}</h3><p role="status" className="text-xs text-[color:var(--text-muted)]">{t(jobStatusKeys[job.status])}</p></div>
            </div>
            {job.error ? <p className="mt-2 break-words text-xs text-destructive">{job.error}</p> : null}
            {job.result?.citations?.length ? <div className="mt-3 border-t border-[color:var(--border-hairline)] pt-2"><h4 className="mb-1 text-xs font-medium">{t("workspaceChat.sources")}</h4><ul className="grid gap-1">{job.result.citations.map((source, index) => {
              const url = safeSourceUrl(source.source_url)
              const document = model.files.find((file) => file.id === source.source_object_id)
              const title = source.title ?? document?.filename ?? (url ? new URL(url).hostname : source.label)
              const label = title === source.label ? source.label : `${source.label} · ${title}`
              const sourceWorkspace = model.workspaces.find((row) => row.id === (source.workspace_id ?? document?.workspace_id))
              const origin = !source.source_object_id ? "workspaceChat.globalSource" : sourceWorkspace?.kind === "company" ? "workspaceChat.companyFile" : sourceWorkspace?.kind === "client" ? "workspaceChat.clientFile" : "workspaceChat.privateFile"
              return <li key={`${source.source_object_id ?? source.source_url}:${index}`}>
                {source.source_object_id ? <button type="button" className="text-left text-xs text-db-gold-700 underline underline-offset-2" aria-label={t("workspaceChat.openSource", { name: label })} onClick={() => setCitation(source)}>{label}</button> : url ? <a className="text-xs text-db-gold-700 underline underline-offset-2" href={url} target="_blank" rel="noreferrer">{label}</a> : <span className="text-xs">{label}</span>}
                <span className="ml-2 text-[10px] text-[color:var(--text-muted)]">{t(origin)}</span>
              </li>
            })}</ul></div> : null}
          </article>)}
        </>}
      />
      <WorkspaceResearchDialog open={researchOpen} onOpenChange={setResearchOpen} workspace={workspace} files={model.files} busy={busy} error={model.error} onStart={startResearch} />
      {model.chat ? <WorkspaceSourceDialog chatId={model.chat.id} citation={citation} customerId={customerId} onClose={() => setCitation(null)} /> : null}
      <Dialog open={workspaceOpen} onOpenChange={(next) => { if (!busy) setWorkspaceOpen(next) }}>
        <DialogContent showCloseButton={false} style={{ minHeight: 0 }} className="theme-admin sm:max-w-md">
          <form className="grid gap-4" onSubmit={(event) => {
            event.preventDefault()
            if (!workspaceName.trim() || busy) return
            setBusy(true)
            void createClientWorkspace(workspaceName.trim(), customerId).then((created) => {
              model.setWorkspaces((rows) => [...rows, created])
              model.setWorkspaceId(created.id)
              setWorkspaceOpen(false)
            }).catch(fail).finally(() => setBusy(false))
          }}>
            <DialogHeader><DialogTitle>{t("workspaceChat.newWorkspace")}</DialogTitle><DialogDescription>{t("workspaceChat.workspaceIntro")}</DialogDescription></DialogHeader>
            <label className="grid gap-2 text-sm"><span>{t("workspaceChat.workspaceName")}</span><input autoFocus required maxLength={200} value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} className="rounded border border-[color:var(--border-hairline)] bg-db-ink-0 p-2" /></label>
            {model.error ? <p role="alert" className="text-sm text-destructive">{model.error}</p> : null}
            <DialogFooter><AdminButton type="button" variant="secondary" disabled={busy} onClick={() => setWorkspaceOpen(false)}>{t("workspaceChat.cancel")}</AdminButton><AdminButton type="submit" disabled={busy || !workspaceName.trim()}>{t("workspaceChat.create")}</AdminButton></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  )
}
