import { useCallback, lazy, Suspense, useEffect, useRef, useState } from "react"
import { ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react"
import { getUnderlag, getUnderlagFile, type DocumentKnowledgeAnchor } from "@/api/underlag"
import { workspaces, type SourceReference, type Workspace } from "@/api/workspaces"
const PdfKnowledgeViewer = lazy(() => import("@/components/underlag/PdfKnowledgeViewer").then((module) => ({ default: module.PdfKnowledgeViewer })))
import { useLocale } from "@/i18n"
import { workspaceErrorMessage } from "./workspaceChatLogic"

export function WorkspaceSourcePane({ workspace, sourceId, page, zoom, reference, onNavigate, onSelection, onReady, onError }: {
  workspace: Workspace
  sourceId: string
  page: number
  zoom: number
  reference?: SourceReference
  onNavigate: (page: number, zoom: number) => void
  onSelection: (anchor: DocumentKnowledgeAnchor) => void
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
  const [focus, setFocus] = useState<DocumentKnowledgeAnchor[]>([])
  useEffect(() => { setFocus(reference?.anchor ? [reference.anchor] : []) }, [reference])
  const callbacks = useRef({ onError, onReady })
  callbacks.current = { onError, onReady }
  const reportError = useCallback((message: string) => { setError(message); callbacks.current.onError(sourceId, message) }, [sourceId])
  const reportReady = useCallback(() => callbacks.current.onReady(sourceId), [sourceId])
  const remoteReferenceId = localSource ? undefined : reference?.reference_id
  const stale = reference?.stale === true
  const reportCount = useCallback((pages: number) => setCount(pages), [])
  useEffect(() => {
    let cancelled = false
    let objectUrl: string | null = null
    setError(null); setUrl(null); setText(null)
    if (stale) { reportError(t("workspaceChat.stale")); return }
    const load = async () => {
      if (source?.content_type === "application/pdf") {
        const blob = await getUnderlagFile(sourceId)
        if (!cancelled) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl) }
      } else {
        const result = localSource ? await getUnderlag(sourceId) : await workspaces.tool(workspace.id, "read_source", { reference_id: remoteReferenceId, source_id: sourceId })
        if ("stale" in result && result.stale) throw new Error(t("workspaceChat.stale"))
        const content = "extracted_text" in result ? result.extracted_text : "text" in result && result.text ? result.text : "snapshot" in result ? result.snapshot?.excerpt : null
        if (!content) throw new Error(t("workspaceChat.notReady"))
        if (!cancelled) setText(content)
      }
    }
    void load().catch((caught: unknown) => { if (!cancelled) reportError(workspaceErrorMessage(caught, t, "workspaceChat.presentationError")) })
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [remoteReferenceId, stale, reportError, localSource, source?.content_type, sourceId, t, workspace.id])
  useEffect(() => {
    if (text === null) return
    const exact = reference?.anchor?.exact_text ?? reference?.excerpt
    if (exact && !text.includes(exact)) { reportError(t("workspaceChat.presentationError")); return }
    reportReady()
  }, [reference, reportError, reportReady, t, text])
  const label = source?.filename ?? reference?.title ?? sourceId
  const exact = reference?.anchor?.exact_text ?? reference?.excerpt
  const index = exact && text ? text.indexOf(exact) : -1
  return <section className="flex min-h-0 min-w-0 flex-1 flex-col border-r border-[color:var(--border-hairline)] last:border-0">
    <header className="flex min-h-12 shrink-0 flex-wrap items-center gap-2 border-b border-[color:var(--border-hairline)] bg-white px-3 py-2 text-xs">
      <strong className="min-w-0 flex-1 truncate">{label}</strong>
      {url ? <><button type="button" aria-label={t("workspaceChat.previousPage")} disabled={page <= 1} onClick={() => onNavigate(page - 1, zoom)}><ChevronLeft size={15} /></button><span>{t("workspaceChat.page")} {page}/{count}</span><button type="button" aria-label={t("workspaceChat.nextPage")} disabled={page >= count} onClick={() => onNavigate(page + 1, zoom)}><ChevronRight size={15} /></button><button type="button" aria-label={t("workspaceChat.zoomOut")} disabled={zoom <= 0.5} onClick={() => onNavigate(page, zoom - 0.1)}><Minus size={15} /></button><span>{new Intl.NumberFormat(intl, { style: "percent" }).format(zoom)}</span><button type="button" aria-label={t("workspaceChat.zoomIn")} disabled={zoom >= 2} onClick={() => onNavigate(page, zoom + 0.1)}><Plus size={15} /></button></> : null}
    </header>
    {error ? <p className="p-4 text-sm text-destructive" role="alert">{error}</p> : url ? <div className="min-h-0 flex-1"><Suspense fallback={<p className="p-4 text-sm">{t("underlag.previewPdfLoading")}</p>}><PdfKnowledgeViewer url={url} pageNumber={page} zoom={zoom} focusAnchors={focus} selectionActive onPageCount={reportCount} onReady={reportReady} onError={reportError} onSelection={(anchor) => { setFocus([anchor]); onSelection(anchor) }} /></Suspense></div> : text !== null ? <div ref={textRef} className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap bg-white p-6 text-sm leading-relaxed" onMouseUp={() => { const selection = window.getSelection(); if (selection?.anchorNode && selection.focusNode && textRef.current?.contains(selection.anchorNode) && textRef.current.contains(selection.focusNode) && selection.toString().trim()) onSelection({ anchor_type: "text", page_number: null, locator: null, rects: [], prefix_text: null, suffix_text: null, asset_id: null, ...reference?.anchor, exact_text: selection.toString() }) }}>{index < 0 ? text : <>{text?.slice(0, index)}<mark className="rounded bg-db-gold-300/70">{exact}</mark>{text?.slice(index + (exact?.length ?? 0))}</>}</div> : <p className="p-4 text-sm text-muted-foreground">{t("sme.loading")}</p>}
  </section>
}
