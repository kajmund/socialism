import { useEffect, useRef, useState } from "react"
import { workspaces, type WorkspaceArtifact, type SourceReference } from "@/api/workspaces"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { workspaceErrorMessage } from "./workspaceChatLogic"
import { ApiError } from "@/lib/api"
import { WorkspaceReferences } from "./WorkspaceReferences"

const drafts = new Map<string, { draft: WorkspaceArtifact; dirty: boolean }>()

export function WorkspaceArtifactEditor({ workspaceId, artifact, references, onSaved, onSelect, onOpen, onReady }: { workspaceId: string; artifact: WorkspaceArtifact; references: SourceReference[]; onSaved: (artifact: WorkspaceArtifact) => void; onSelect: (blockId: string | null, revision: number) => void; onOpen: (id: string) => void; onReady: (revision: number) => void }) {
  const { t } = useLocale()
  const [draft, setDraft] = useState(() => drafts.get(artifact.id)?.draft ?? artifact)
  const [dirty, setDirty] = useState(() => drafts.get(artifact.id)?.dirty ?? false)
  const previousArtifact = useRef(artifact)
  const focusedBlock = useRef<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [latest, setLatest] = useState<WorkspaceArtifact | null>(null)
  useEffect(() => { drafts.set(artifact.id, { draft, dirty }) }, [artifact.id, draft, dirty])
  useEffect(() => { if (previousArtifact.current === artifact) return; const previous = previousArtifact.current; previousArtifact.current = artifact; if (!dirty && draft.revision === previous.revision) setDraft(artifact) }, [artifact, dirty, draft])
  useEffect(() => { if (!dirty) onReady(draft.revision) }, [dirty, draft.revision, onReady])
  async function save() {
    setBusy(true); setError(null)
    try { const saved = await workspaces.saveArtifact(workspaceId, draft); setDraft(saved); setDirty(false); setLatest(null); onSaved(saved) }
    catch (caught: unknown) { setError(caught instanceof ApiError && caught.status === 409 ? t("workspaceChat.conflict") : workspaceErrorMessage(caught, t, "workspaceChat.operationError")); if (caught instanceof ApiError && caught.status === 409) await workspaces.artifact(workspaceId, draft.id).then(setLatest).catch((error: unknown) => setError(workspaceErrorMessage(error, t, "workspaceChat.operationError"))) }
    finally { setBusy(false) }
  }
  async function exportFile(format: "docx" | "pdf") {
    setBusy(true); setError(null)
    try {
      const blob = await workspaces.export(workspaceId, artifact.id, format, draft.revision)
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a"); link.href = url; link.download = `${draft.title}.${format}`; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (caught: unknown) { setError(workspaceErrorMessage(caught, t, "workspaceChat.operationError")) }
    finally { setBusy(false) }
  }
  return <div className="h-full overflow-auto bg-white p-4 sm:p-6">
    <div className="mb-4 flex flex-wrap items-center gap-2"><span className="mr-auto text-xs text-muted-foreground">{t("workspaceChat.revision", { revision: draft.revision })}{dirty ? <> · {t("workspaceChat.unsavedChanges")}</> : null}</span><label className="text-xs">{t("workspaceChat.chooseRevision")} <select className="ml-1 rounded border bg-white p-1" value={draft.revision} disabled={dirty || busy} onChange={(event) => { void workspaces.artifact(workspaceId, draft.id, Number(event.target.value)).then((revision) => { setDraft(revision); onSelect(revision.content.blocks?.some((block) => block.id === focusedBlock.current) ? focusedBlock.current : null, revision.revision) }).catch((caught: unknown) => setError(workspaceErrorMessage(caught, t, "workspaceChat.operationError"))) }}>{Array.from({ length: artifact.revision }, (_, i) => i + 1).map((revision) => <option key={revision} value={revision}>{revision}</option>)}</select></label><AdminButton size="sm" disabled={busy || !dirty || latest !== null} onClick={() => void save()}>{busy ? t("workspaceChat.saving") : t("workspaceChat.save")}</AdminButton><AdminButton variant="secondary" size="sm" disabled={busy || dirty} onClick={() => void exportFile("docx")}>{t("workspaceChat.exportDocx")}</AdminButton><AdminButton variant="secondary" size="sm" disabled={busy || dirty} onClick={() => void exportFile("pdf")}>{t("workspaceChat.exportPdf")}</AdminButton></div>
    {error ? <p className="mb-3 rounded border border-destructive p-3 text-sm text-destructive" role="alert">{error}</p> : null}
    {latest ? <div className="mb-4 rounded border border-db-gold-500 bg-db-gold-100 p-3"><strong>{t("workspaceChat.revision", { revision: latest.revision })}</strong><div className="mt-2 space-y-2 text-sm">{latest.content.blocks?.map((block) => <p key={block.id}>{block.text}</p>)}</div><AdminButton variant="secondary" size="sm" className="mt-3" onClick={() => { setDraft((current) => ({ ...current, revision: latest.revision })); setLatest(null); setError(null) }}>{t("workspaceChat.resolveConflict")}</AdminButton></div> : null}
    <input className="mb-6 w-full border-b bg-transparent pb-2 font-[var(--font-display)] text-xl font-semibold outline-none focus:border-db-gold-500" aria-label={t("workspaceChat.titleLabel")} value={draft.title} onChange={(event) => { setDraft({ ...draft, title: event.target.value }); setDirty(true) }} />
    <div className="space-y-4">{draft.content.blocks?.map((block, i) => <div key={block.id}><textarea className={`w-full resize-y rounded border border-transparent p-2 outline-none hover:border-db-ink-200 focus:border-db-gold-500 ${block.type === "heading" ? "text-lg font-semibold" : "text-sm leading-relaxed"}`} rows={block.type === "heading" ? 1 : Math.max(3, Math.ceil(block.text.length / 90))} aria-label={t("workspaceChat.blockLabel", { number: i + 1 })} value={block.text} onFocus={() => { focusedBlock.current = block.id; onSelect(block.id, draft.revision) }} onChange={(event) => { setDraft({ ...draft, content: { ...draft.content, blocks: draft.content.blocks?.map((row) => row.id === block.id ? { ...row, text: event.target.value } : row) } }); setDirty(true) }} /><WorkspaceReferences ids={block.source_refs} references={references} onOpen={onOpen} /></div>)}</div>
  </div>
}
