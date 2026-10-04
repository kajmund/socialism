import { useCallback, lazy, Suspense, useEffect, useMemo, useRef, useState } from "react"
import { ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react"
import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import { voiceWorkspaces, type SourceReference, type Workspace } from "@/api/voiceWorkspaces"
const PdfKnowledgeViewer = lazy(() => import("@/components/underlag/PdfKnowledgeViewer").then((module) => ({ default: module.PdfKnowledgeViewer })))
import { useLocale } from "@/i18n"
import { workspaceErrorMessage } from "./workspaceChatLogic"

export function WorkspaceSourcePane({ workspace, sourceId, page, zoom, reference, onNavigate, onSelection, onClearSelection, onReady, onError }: {
  workspace: Workspace
  sourceId: string
  page: number
  zoom: number
  reference?: SourceReference
  onNavigate: (page: number, zoom: number) => void
  onSelection: (anchor: DocumentKnowledgeAnchor) => void
  onClearSelection: () => void
  onReady: (sourceId: string) => void
  onError: (sourceId: string, message: string) => void
}) {
  const { t, intl } = useLocale()
  const textRef = useRef<HTMLDivElement>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [count, setCount] = useState(1)
  const source = workspace.sources.find((row) => row.id === sourceId)
  const localSource = source !== undefined
  const referenceId = reference?.reference_id
  const [selectedFocus, setSelectedFocus] = useState<{ referenceId: string | undefined; page: number; revision: number; anchor: DocumentKnowledgeAnchor | null } | null>(null)
  const localFocus = selectedFocus?.referenceId === referenceId && selectedFocus?.page === page && (selectedFocus.anchor === null || selectedFocus.revision === workspace.revision) ? selectedFocus : null
  const dismissed = localFocus !== null && localFocus.anchor === null
  const savedAnchor = workspace.state.selection?.source_id === sourceId ? workspace.state.selection.anchor : undefined
  const suppressReferenceReady = referenceId !== undefined && (localFocus !== null || savedAnchor !== undefined)
  const focus = useMemo(() => localFocus ? localFocus.anchor ? [localFocus.anchor] : [] : savedAnchor?.page_number === page ? [savedAnchor] : reference?.anchor ? [reference.anchor] : [], [localFocus, page, reference, savedAnchor])
  useEffect(() => { setSelectedFocus(null) }, [referenceId, sourceId])
  const callbacks = useRef({ onError, onReady, suppressReferenceReady })
  callbacks.current = { onError, onReady, suppressReferenceReady }
  const reportError = useCallback((message: string) => { setError(message); callbacks.current.onError(sourceId, message) }, [sourceId])
  const reportReady = useCallback(() => { setError(null); if (!callbacks.current.suppressReferenceReady) callbacks.current.onReady(sourceId) }, [sourceId])
  const remoteReferenceId = localSource ? undefined : reference?.reference_id
  const stale = reference?.stale === true
  const reportCount = useCallback((pages: number) => setCount(pages), [])
  useEffect(() => {
    let cancelled = false
    let objectUrl: string | null = null
    setError(null); setUrl(null); setText(null)
    if (stale) { reportError(t("voiceWorkspaceChat.stale")); return }
    const load = async () => {
      if (source?.content_type === "application/pdf") {
        const blob = await voiceWorkspaces.sourceFile(workspace.id, sourceId)
        if (!cancelled) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) }
      } else {
        const result = localSource ? await voiceWorkspaces.source(workspace.id, sourceId) : await voiceWorkspaces.tool(workspace.id, "read_source", { reference_id: remoteReferenceId, source_id: sourceId })
        if ("stale" in result && result.stale) throw new Error(t("voiceWorkspaceChat.stale"))
        const content = "extracted_text" in result ? result.extracted_text : "text" in result && result.text ? result.text : "snapshot" in result ? result.snapshot?.excerpt : null
        if (!content) throw new Error(t("voiceWorkspaceChat.notReady"))
        if (!cancelled) setText(content)
      }
    }
    void load().catch((caught: unknown) => { if (!cancelled) reportError(workspaceErrorMessage(caught, t, "voiceWorkspaceChat.presentationError")) })
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [remoteReferenceId, stale, reportError, localSource, source?.content_type, sourceId, t, workspace.id])
  useEffect(() => {
    if (text === null) return
    const exact = reference?.anchor?.exact_text ?? reference?.excerpt
    if (exact && !text.includes(exact)) { reportError(t("voiceWorkspaceChat.presentationError")); return }
    reportReady()
  }, [reference, reportError, reportReady, t, text, workspace.revision])
  const label = source?.filename ?? reference?.title ?? sourceId
  const exact = reference?.anchor?.exact_text ?? reference?.excerpt
  const index = exact && text ? text.indexOf(exact) : -1
  return <section className="flex min-h-0 min-w-0 flex-1 flex-col border-r border-[color:var(--border-hairline)] last:border-0">
    <header className="flex min-h-12 shrink-0 flex-wrap items-center gap-2 border-b border-[color:var(--border-hairline)] bg-white px-3 py-2 text-xs">
      <strong className="min-w-0 flex-1 truncate">{label}</strong>
      {url ? <><button type="button" aria-label={t("voiceWorkspaceChat.previousPage")} disabled={page <= 1} onClick={() => onNavigate(page - 1, zoom)}><ChevronLeft size={15} /></button><span>{t("voiceWorkspaceChat.page")} {page}/{count}</span><button type="button" aria-label={t("voiceWorkspaceChat.nextPage")} disabled={page >= count} onClick={() => onNavigate(page + 1, zoom)}><ChevronRight size={15} /></button><button type="button" aria-label={t("voiceWorkspaceChat.zoomOut")} disabled={zoom <= 0.5} onClick={() => onNavigate(page, zoom - 0.1)}><Minus size={15} /></button><span>{new Intl.NumberFormat(intl, { style: "percent" }).format(zoom)}</span><button type="button" aria-label={t("voiceWorkspaceChat.zoomIn")} disabled={zoom >= 2} onClick={() => onNavigate(page, zoom + 0.1)}><Plus size={15} /></button></> : null}
    </header>
    {error ? <p className="shrink-0 p-4 text-sm text-destructive" role="alert">{error}</p> : null}
    {url ? <div className="min-h-0 flex-1"><Suspense fallback={<p className="p-4 text-sm">{t("underlag.previewPdfLoading")}</p>}><PdfKnowledgeViewer url={url} pageNumber={page} zoom={zoom} focusAnchors={focus} presentationRevision={workspace.revision} selectionActive onPageCount={reportCount} onReady={reportReady} onError={reportError} onSelection={(anchor) => { setSelectedFocus({ referenceId, page, revision: workspace.revision, anchor }); onSelection(anchor) }} onClearSelection={() => { if (dismissed || focus.length === 0) return; setSelectedFocus({ referenceId, page, revision: workspace.revision, anchor: null }); onClearSelection() }} /></Suspense></div> : text !== null ? <div ref={textRef} className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap bg-white p-6 text-sm leading-relaxed" onMouseUp={() => { const selection = window.getSelection(); if (selection?.anchorNode && selection.focusNode && textRef.current?.contains(selection.anchorNode) && textRef.current.contains(selection.focusNode) && selection.toString().trim()) onSelection({ anchor_type: "text", page_number: null, locator: null, rects: [], prefix_text: null, suffix_text: null, asset_id: null, ...reference?.anchor, exact_text: selection.toString() }) }}>{index < 0 ? text : <>{text?.slice(0, index)}<mark className="rounded bg-db-gold-300/70">{exact}</mark>{text?.slice(index + (exact?.length ?? 0))}</>}</div> : !error ? <p className="p-4 text-sm text-muted-foreground">{t("sme.loading")}</p> : null}
  </section>
}
