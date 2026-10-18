import { useCallback, lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react"
import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import { markColor } from "@/components/underlag/documentMarkColor"
import { requireSourceVersion, voiceWorkspaces, type PassageComment, type SourceReference, type Workspace } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { isDocxSource, isPdfSource } from "@/lib/sourceKind"
import { DocumentCommentButton, DocumentCommentMargin } from "./DocumentCommentMargin"
import { commentThreads, marksForComments, shownCommentThreads, type MarkAnchor } from "./documentCommentLayout"
import { isWorkspaceSourceReread, workspaceErrorMessage } from "./workspaceChatLogic"
import { foreignPassage, markIsLocked, textMarkSegments, visibleDocumentMarks } from "./workspaceDocumentFocus"
import { localSelectionMatchesReference, localUserAnchors, type LocalDocumentSelection } from "./workspaceLocalSelection"
import { passageCommentKey } from "./passageCommentKey"
const PdfKnowledgeViewer = lazy(() => import("@/components/underlag/PdfKnowledgeViewer").then((module) => ({ default: module.PdfKnowledgeViewer })))
const DocxKnowledgeViewer = lazy(() => import("@/components/underlag/DocxKnowledgeViewer").then((module) => ({ default: module.DocxKnowledgeViewer })))

export function WorkspaceSourcePane({ workspace, localSelection, reader, sourceId, page, zoom, reference, onNavigate, onSelection, onClearSelection, onCommentSaved, onCommentRemoved, onReady, onError }: {
  workspace: Workspace
  localSelection: LocalDocumentSelection | null
  reader: { id: string; name: string } | null
  sourceId: string
  page: number
  zoom: number
  reference?: SourceReference
  onNavigate: (page: number, zoom: number) => void
  onSelection: (anchor: DocumentKnowledgeAnchor, sourceVersion: string, sourceFileSha256?: string) => void
  onClearSelection: () => void
  onCommentSaved: (comment: PassageComment) => void
  onCommentRemoved: (id: string, removedReferenceIds: string[]) => void
  onReady: (sourceId: string) => void
  onError: (sourceId: string, message: string) => void
}) {
  const { t, intl } = useLocale()
  const textRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [docx, setDocx] = useState<Blob | null>(null)
  const [docxReady, setDocxReady] = useState(false)
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [count, setCount] = useState(1)
  const [commentsOpen, setCommentsOpen] = useState(false)
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const [commentPending, setCommentPending] = useState(false)
  const [textAnchors, setTextAnchors] = useState<MarkAnchor[]>([])
  const source = workspace.sources.find((row) => row.id === sourceId)
  const localSource = source !== undefined
  const sourceKind = source ? { content_type: source.content_type, filename: source.filename } : null
  const pdfSource = isPdfSource(sourceKind)
  const docxSource = isDocxSource(sourceKind)
  const referenceId = reference?.reference_id
  const [sourceVersion, setSourceVersion] = useState<string | null>(null)
  const [sourceFileSha256, setSourceFileSha256] = useState<string | undefined>(undefined)
  const local = localSelection?.sourceId === sourceId ? localSelection : localSelection?.clearedSourceIds?.includes(sourceId) ? { sourceId, selection: null } : null
  const drafts = useMemo(() => localUserAnchors(localSelection, sourceId), [localSelection, sourceId])
  const manualAnchor = drafts === null ? undefined : drafts.at(-1) ?? null
  const savedAnchor = workspace.state.selection?.source_id === sourceId ? workspace.state.selection.anchor : undefined
  const suppressReferenceReady = referenceId !== undefined && (local ? !localSelectionMatchesReference(local, reference!) : savedAnchor !== undefined)
  const focus = useMemo(
    () => marksForComments(visibleDocumentMarks(workspace.references, sourceId, null, manualAnchor !== undefined ? manualAnchor : savedAnchor ?? reference?.anchor, {
      cleared: drafts !== null && drafts.length === 0,
      manual: manualAnchor != null,
      drafts: drafts ?? undefined,
      user: reader,
    }), workspace.comments ?? [], sourceId),
    [drafts, manualAnchor, reader, reference, savedAnchor, sourceId, workspace.comments, workspace.references],
  )
  const threads = useMemo(() => shownCommentThreads(commentThreads(focus, workspace.comments ?? [], sourceId), activeKey), [activeKey, focus, sourceId, workspace.comments])
  const commentCount = (workspace.comments ?? []).filter((row) => row.source_id === sourceId).length
  const [shown, setShown] = useState(page)
  const pendingPage = useRef<number | null>(null)
  const pageTimer = useRef<number | null>(null)
  const navigateRef = useRef(onNavigate)
  const zoomRef = useRef(zoom)
  navigateRef.current = onNavigate
  zoomRef.current = zoom
  useEffect(() => () => { if (pageTimer.current != null) window.clearTimeout(pageTimer.current) }, [])
  useEffect(() => {
    if (pendingPage.current != null && pendingPage.current !== page) {
      if (pageTimer.current != null) window.clearTimeout(pageTimer.current)
      pageTimer.current = null
      pendingPage.current = null
    }
    setShown(page)
  }, [page])
  const showPage = useCallback((next: number) => {
    setShown((current) => (current === next ? current : next))
    if (pendingPage.current === next && pageTimer.current != null) return
    pendingPage.current = next
    if (pageTimer.current != null) window.clearTimeout(pageTimer.current)
    pageTimer.current = window.setTimeout(() => {
      pageTimer.current = null
      const target = pendingPage.current
      pendingPage.current = null
      if (target != null) navigateRef.current(target, zoomRef.current)
    }, 300)
  }, [])
  const go = (nextPage: number, nextZoom: number) => {
    if (pageTimer.current != null) window.clearTimeout(pageTimer.current)
    pageTimer.current = null
    pendingPage.current = null
    setShown(nextPage)
    onNavigate(nextPage, nextZoom)
  }
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
    setError(null); setUrl(null); setDocx(null); setDocxReady(false); setText(null); setSourceVersion(null); setSourceFileSha256(undefined)
    if (stale) { reportError(t("voiceWorkspaceChat.stale")); return }
    const load = async () => {
      if (pdfSource || docxSource) {
        const read = () => voiceWorkspaces.sourceFileWithVersion(workspace.id, sourceId)
        const result = await read().catch((error: unknown) => { if (!isWorkspaceSourceReread(error)) throw error; return read() })
        if (cancelled) return
        setSourceVersion(result.sourceVersion)
        setSourceFileSha256(result.sourceFileSha256)
        if (docxSource) setDocx(result.blob)
        else { objectUrl = URL.createObjectURL(result.blob); setUrl(objectUrl) }
      } else {
        const result = localSource ? await voiceWorkspaces.source(workspace.id, sourceId) : await voiceWorkspaces.tool(workspace.id, "read_source", { reference_id: remoteReferenceId, source_id: sourceId })
        if ("stale" in result && result.stale) throw new Error(t("voiceWorkspaceChat.stale"))
        const content = "extracted_text" in result ? result.extracted_text : "text" in result && result.text ? result.text : "snapshot" in result ? result.snapshot?.excerpt : null
        if (!content) throw new Error(t("voiceWorkspaceChat.notReady"))
        const version = requireSourceVersion("source_version" in result ? result.source_version : reference?.source_version)
        if (!cancelled) { setSourceVersion(version); setText(content) }
      }
    }
    void load().catch((caught: unknown) => { if (!cancelled) reportError(workspaceErrorMessage(caught, t, "voiceWorkspaceChat.presentationError")) })
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
    // Depend on stable source identity fields, not the workspace.sources row object —
    // PATCH after a tab switch returns a new array and would otherwise reload the file.
  }, [remoteReferenceId, stale, reportError, localSource, pdfSource, docxSource, sourceId, t, workspace.id, reference?.source_version])
  useEffect(() => {
    if (text === null) return
    const exact = reference?.anchor?.exact_text ?? reference?.excerpt
    if (exact && !text.includes(exact)) { reportError(t("voiceWorkspaceChat.presentationError")); return }
    reportReady()
  }, [reference, reportError, reportReady, t, text, workspace.revision])
  const label = source?.filename ?? reference?.title ?? sourceId
  const segments = text ? textMarkSegments(text, focus) : []
  const passageSignature = focus.map((mark) => mark.passageKey).join("|")
  useLayoutEffect(() => {
    const stage = stageRef.current
    if (!stage || url || !commentsOpen) return
    const origin = stage.getBoundingClientRect().top
    const seen = new Set<string>()
    const next: MarkAnchor[] = []
    for (const node of stage.querySelectorAll<HTMLElement>("[data-passage-key]")) {
      const key = node.dataset.passageKey
      if (!key || seen.has(key)) continue
      seen.add(key)
      const rect = node.getBoundingClientRect()
      next.push({ key, top: rect.top - origin, height: rect.height })
    }
    setTextAnchors((current) => sameAnchors(current, next) ? current : next)
  }, [commentsOpen, docxReady, passageSignature, text, url])
  const saveComment = async (anchor: DocumentKnowledgeAnchor, body: string) => {
    setCommentPending(true)
    try {
      const saved = await voiceWorkspaces.addPassageComment(workspace.id, { source_id: sourceId, anchor, body })
      onCommentSaved(saved)
      setActiveKey(saved.passage_key)
    } catch (caught) {
      reportError(workspaceErrorMessage(caught, t, "voiceWorkspaceChat.operationError"))
      throw caught
    } finally { setCommentPending(false) }
  }
  const editComment = async (id: string, body: string) => {
    try {
      onCommentSaved(await voiceWorkspaces.updatePassageComment(workspace.id, id, body))
    } catch (caught) { reportError(workspaceErrorMessage(caught, t, "voiceWorkspaceChat.operationError")) }
  }
  const deleteComment = async (id: string) => {
    try {
      const removed = await voiceWorkspaces.deletePassageComment(workspace.id, id)
      onCommentRemoved(id, removed.removed_reference_ids)
    } catch (caught) { reportError(workspaceErrorMessage(caught, t, "voiceWorkspaceChat.operationError")) }
  }
  const margin = (anchors: MarkAnchor[]) => <DocumentCommentMargin threads={threads} anchors={anchors} activeKey={activeKey} reader={reader} pending={commentPending} onActivate={setActiveKey} onSubmit={saveComment} onEdit={editComment} onDelete={deleteComment} />
  const focusPassage = (key: string) => { setCommentsOpen(true); setActiveKey(key) }
  const seenSource = useRef(sourceId)
  const seenComments = useRef(new Set<string>())
  const seenReady = useRef(false)
  useEffect(() => {
    if (seenSource.current !== sourceId) {
      seenSource.current = sourceId
      seenComments.current = new Set()
      seenReady.current = false
    }
    const rows = (workspace.comments ?? []).filter((row) => row.source_id === sourceId)
    const fresh = rows.filter((row) => !seenComments.current.has(row.id))
    for (const row of rows) seenComments.current.add(row.id)
    if (!seenReady.current) { seenReady.current = true; return }
    const recent = fresh.find((row) => Date.now() - new Date(row.created_at).getTime() < 60_000)
    if (recent) focusPassage(recent.passage_key)
  }, [sourceId, workspace.comments])
  const remember = (anchor: DocumentKnowledgeAnchor) => { if (commentsOpen) setActiveKey(passageCommentKey(sourceId, anchor)) }
  const toggleComments = () => {
    setCommentsOpen((open) => {
      const next = !open
      if (next) {
        const latest = [...focus].reverse().find((mark) => mark.authorKind === "user") ?? focus.at(-1)
        if (latest) setActiveKey(latest.passageKey)
      }
      return next
    })
  }
  const capture = (anchor: DocumentKnowledgeAnchor) => {
    const foreign = foreignPassage(focus, anchor, sourceId, reader?.id ?? null)
    if (foreign) { focusPassage(foreign.passageKey); window.getSelection()?.removeAllRanges(); return }
    if (!sourceVersion) { reportError(workspaceErrorMessage(new Error("workspace_source_version_missing"), t, "voiceWorkspaceChat.presentationError")); return }
    onSelection(anchor, sourceVersion, sourceFileSha256)
    remember(anchor)
  }
  const captureText = () => {
    const selection = window.getSelection()
    if (!selection?.anchorNode || !selection.focusNode || !textRef.current?.contains(selection.anchorNode) || !textRef.current.contains(selection.focusNode)) return
    if (selection.isCollapsed) { if (drafts?.length || focus.length) onClearSelection(); return }
    const selected = selection.toString().trim()
    if (!selected || !textRef.current) return
    const before = plainTextBefore(textRef.current, selection.anchorNode, selection.anchorOffset)
    const anchor = { anchor_type: "text" as const, page_number: null, locator: "document", rects: [], suffix_text: null, asset_id: null, exact_text: selected, prefix_text: before.slice(-80) || null }
    capture(anchor)
  }
  const docxHighlights = focus.map((mark) => ({
    exact_text: mark.anchor.exact_text,
    authorKind: mark.authorKind,
    authorId: mark.authorId,
    authorName: mark.authorName,
    passageKey: mark.passageKey,
    locked: markIsLocked(mark, reader?.id ?? null),
  }))
  return <section className="flex min-h-0 min-w-0 flex-1 flex-col border-r border-[color:var(--border-hairline)] last:border-0">
    <header className="flex min-h-12 shrink-0 flex-wrap items-center gap-2 border-b border-[color:var(--border-hairline)] bg-white px-3 py-2 text-xs">
      <strong className="min-w-0 flex-1 truncate">{label}</strong>
      <DocumentCommentButton open={commentsOpen} count={commentCount} onClick={toggleComments} />
      {url || docx ? <><button type="button" aria-label={t("voiceWorkspaceChat.previousPage")} disabled={shown <= 1} onClick={() => go(shown - 1, zoom)}><ChevronLeft size={15} /></button><span>{t("voiceWorkspaceChat.page")} {shown}/{count}</span><button type="button" aria-label={t("voiceWorkspaceChat.nextPage")} disabled={shown >= count} onClick={() => go(shown + 1, zoom)}><ChevronRight size={15} /></button><button type="button" aria-label={t("voiceWorkspaceChat.zoomOut")} disabled={zoom <= 0.5} onClick={() => go(shown, zoom - 0.1)}><Minus size={15} /></button><span>{new Intl.NumberFormat(intl, { style: "percent" }).format(zoom)}</span><button type="button" aria-label={t("voiceWorkspaceChat.zoomIn")} disabled={zoom >= 2} onClick={() => go(shown, zoom + 0.1)}><Plus size={15} /></button></> : null}
    </header>
    {error ? <p className="shrink-0 p-4 text-sm text-destructive" role="alert">{error}</p> : null}
    {url ? <div className="min-h-0 flex-1"><Suspense fallback={<p className="p-4 text-sm">{t("underlag.previewPdfLoading")}</p>}><PdfKnowledgeViewer url={url} pageNumber={shown} zoom={zoom} focusAnchors={focus} presentationRevision={workspace.revision} selectionActive commentsOpen={commentsOpen} readerId={reader?.id ?? null} onFocusPassage={focusPassage} renderComments={margin} onPageCount={reportCount} onVisiblePage={showPage} onReady={reportReady} onError={reportError} onSelection={capture} onClearSelection={() => { if (drafts?.length || focus.length) onClearSelection() }} /></Suspense></div> : docx ? <div className="flex min-h-0 flex-1"><div ref={stageRef} className="flex min-h-0 min-w-0 flex-1"><Suspense fallback={<p className="p-4 text-sm">{t("underlag.previewDocxLoading")}</p>}><DocxKnowledgeViewer blob={docx} zoom={zoom} pageNumber={shown} focusAnchors={docxHighlights} commentsOpen={commentsOpen} onFocusPassage={focusPassage} onPageCount={reportCount} onVisiblePage={showPage} onReady={() => { setDocxReady(true); reportReady() }} onError={reportError} onSelection={capture} onClearSelection={() => { if (drafts?.length || focus.length) onClearSelection() }} /></Suspense></div>{commentsOpen ? <div className="relative w-[296px] shrink-0 border-l border-[color:var(--border-hairline)] bg-db-ink-50">{margin(textAnchors)}</div> : null}</div> : text !== null ? <div className="min-h-0 flex-1 overflow-auto"><div ref={stageRef} className="flex min-h-full"><div ref={textRef} className="min-w-0 flex-1 whitespace-pre-wrap bg-white p-6 text-sm leading-relaxed" onMouseUp={(event) => { if (event.button !== 0) return; const node = event.target instanceof Element ? event.target.closest<HTMLElement>("[data-passage-key]") : null; const key = node?.dataset.passageKey; if (key && (commentsOpen || node?.dataset.markForeign === "true")) { focusPassage(key); window.getSelection()?.removeAllRanges(); return }; captureText() }}>{segments.map((segment, index) => segment.mark ? <TextMark key={index} text={segment.text} kind={segment.mark.authorKind} authorId={segment.mark.authorId} name={segment.mark.authorName} passageKey={segment.mark.passageKey} locked={markIsLocked(segment.mark, reader?.id ?? null)} /> : <span key={index}>{segment.text}</span>)}</div>{commentsOpen ? <div className="relative w-[296px] shrink-0 border-l border-[color:var(--border-hairline)] bg-db-ink-50">{margin(textAnchors)}</div> : null}</div></div> : !error ? <p className="p-4 text-sm text-muted-foreground">{t("sme.loading")}</p> : null}
  </section>
}

function TextMark({ text, kind, authorId, name, passageKey, locked }: { text: string; kind: "user" | "expert" | "passage"; authorId: string | null; name: string | null; passageKey: string; locked: boolean }) {
  const tone = markColor(kind, authorId)
  return <mark data-passage-key={passageKey} data-mark-foreign={locked ? "true" : undefined} className="rounded px-0.5" style={{ backgroundColor: tone.fill }}>{name ? <span data-mark-label="" className="mr-1 select-none text-[10px] font-medium" style={{ color: tone.ink }}>{name}</span> : null}{text}</mark>
}

function plainTextBefore(root: HTMLElement, node: Node, offset: number): string {
  const range = root.ownerDocument.createRange()
  range.setStart(root, 0)
  range.setEnd(node, offset)
  const copy = range.cloneContents()
  copy.querySelectorAll("[data-mark-label]").forEach((label) => label.remove())
  return copy.textContent ?? ""
}

function sameAnchors(left: MarkAnchor[], right: MarkAnchor[]): boolean {
  return left.length === right.length && left.every((row, index) => row.key === right[index]?.key && Math.abs(row.top - (right[index]?.top ?? 0)) < 0.5 && Math.abs(row.height - (right[index]?.height ?? 0)) < 0.5)
}
