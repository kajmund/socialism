import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import {
  getDocument,
  GlobalWorkerOptions,
  TextLayer,
  type PDFDocumentProxy,
  type PDFPageProxy,
} from "pdfjs-dist"
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url"
import "pdfjs-dist/web/pdf_viewer.css"
import type {
  DocumentKnowledgeAnchor,
  DocumentAnchorRect,
} from "@/api/underlag"
import { useLocale } from "@/i18n"
import { markColor, type MarkAuthorKind } from "./documentMarkColor"
import { pdfAnchorKind, pdfAnchorRectangles, pdfPresentationStatus } from "./pdfAnchorPresentation"
import { holdProgrammaticScroll, markerOutsideViewport, pageAtViewportTop } from "./pdfPageScroll"
import { pdfSelectionGesture } from "./pdfSelectionGesture"
import { pdfSelectionText, type PdfSelectionFragment } from "./pdfSelectionText"

export type PdfHighlight = {
  anchor: DocumentKnowledgeAnchor
  authorKind?: MarkAuthorKind
  authorId?: string | null
  authorName?: string | null
  passageKey?: string
}

export type PdfMarkAnchor = { key: string; top: number; height: number }

const COMMENT_RAIL_PX = 296

GlobalWorkerOptions.workerSrc = workerUrl

export function PdfKnowledgeViewer({
  url,
  focusAnchors,
  selectionActive,
  onSelection,
  onClearSelection,
  onError,
  pageNumber,
  zoom = 1,
  onReady,
  onPageCount,
  onVisiblePage,
  presentationRevision,
  commentsOpen = false,
  readerId = null,
  onFocusPassage,
  renderComments,
}: {
  url: string
  focusAnchors: Array<DocumentKnowledgeAnchor | PdfHighlight>
  selectionActive: boolean
  onSelection: (anchor: DocumentKnowledgeAnchor) => void
  onClearSelection: () => void
  onError: (message: string) => void
  pageNumber?: number
  zoom?: number
  onReady?: () => void
  onPageCount?: (count: number) => void
  onVisiblePage?: (page: number) => void
  presentationRevision?: number
  commentsOpen?: boolean
  readerId?: string | null
  onFocusPassage?: (passageKey: string) => void
  renderComments?: (anchors: PdfMarkAnchor[]) => ReactNode
}) {
  const { t } = useLocale()
  const viewportRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const pagesRef = useRef<HTMLDivElement>(null)
  const [markAnchors, setMarkAnchors] = useState<PdfMarkAnchor[]>([])
  const gestureRef = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const requestedPage = useRef(pageNumber)
  const scrolledTo = useRef<number | null>(null)
  const followedPage = useRef("")
  const appliedFocus = useRef<string | null>(null)
  const suppressScroll = useRef(false)
  const cancelScrollHold = useRef<(() => void) | null>(null)
  const onVisiblePageRef = useRef(onVisiblePage)
  requestedPage.current = pageNumber
  onVisiblePageRef.current = onVisiblePage
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [width, setWidth] = useState(0)
  const [rendered, setRendered] = useState(0)
  const layoutWidth = commentsOpen ? Math.max(0, width - COMMENT_RAIL_PX) : width

  useLayoutEffect(() => {
    const node = viewportRef.current
    if (!node) return
    const measure = () => {
      const next = Math.round(node.clientWidth)
      if (next > 0) setWidth((current) => (current === next ? current : next))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let cancelled = false
    const task = getDocument(url)
    void task.promise
      .then((pdf) => {
        if (!cancelled) { setDocument(pdf); onPageCount?.(pdf.numPages) }
      })
      .catch((error: unknown) => {
        if (!cancelled) onError(error instanceof Error ? error.message : t("underlag.previewPdfError"))
      })
    return () => {
      cancelled = true
      setDocument(null)
      void task.destroy()
    }
  }, [onError, onPageCount, t, url])

  useEffect(() => {
    const root = pagesRef.current
    if (!document || !root || layoutWidth <= 0) return
    const pdf = document
    const rootNode = root
    let cancelled = false
    suppressScroll.current = true
    followedPage.current = ""
    scrolledTo.current = null
    appliedFocus.current = null
    rootNode.replaceChildren()
    rootNode.dataset.renderComplete = "false"

    async function renderPages() {
      const requested = requestedPage.current
      if (requested != null && (requested < 1 || requested > pdf.numPages)) {
        throw new Error(t("voiceWorkspaceChat.presentationError"))
      }
      const pages: {
        page: PDFPageProxy
        canvas: HTMLCanvasElement
        textNode: HTMLDivElement
        viewport: ReturnType<PDFPageProxy["getViewport"]>
        outputScale: number
      }[] = []
      for (let number = 1; number <= pdf.numPages; number += 1) {
        if (cancelled) return
        const page = await pdf.getPage(number)
        if (cancelled) return
        const baseViewport = page.getViewport({ scale: 1 })
        const available = Math.max(240, layoutWidth - 32)
        const scale = Math.min(2, available / baseViewport.width) * zoom
        const viewport = page.getViewport({ scale })
        const wrapper = window.document.createElement("div")
        wrapper.className = "pdf-page relative mx-auto bg-white shadow-sm"
        wrapper.dataset.pageNumber = String(number)
        wrapper.dataset.pdfWidth = String(baseViewport.width)
        wrapper.style.width = `${viewport.width}px`
        wrapper.style.height = `${viewport.height}px`
        wrapper.style.setProperty("--total-scale-factor", String(scale * page.userUnit))
        const canvas = window.document.createElement("canvas")
        canvas.className = "absolute inset-0 block"
        const outputScale = window.devicePixelRatio || 1
        canvas.width = Math.floor(viewport.width * outputScale)
        canvas.height = Math.floor(viewport.height * outputScale)
        canvas.style.width = `${viewport.width}px`
        canvas.style.height = `${viewport.height}px`
        wrapper.append(canvas)
        const textNode = window.document.createElement("div")
        textNode.className = "textLayer"
        wrapper.append(textNode)
        rootNode.append(wrapper)
        pages.push({ page, canvas, textNode, viewport, outputScale })
      }
      if (cancelled) return
      rootNode.dataset.renderComplete = "true"
      setRendered((value) => value + 1)
      for (const item of pages) {
        if (cancelled) return
        const context = item.canvas.getContext("2d")
        if (!context) throw new Error("Canvas is unavailable")
        await item.page.render({
          canvas: item.canvas,
          canvasContext: context,
          viewport: item.viewport,
          transform: item.outputScale === 1 ? undefined : [item.outputScale, 0, 0, item.outputScale, 0, 0],
        }).promise
        const textContent = await item.page.getTextContent()
        await new TextLayer({
          textContentSource: textContent,
          container: item.textNode,
          viewport: item.viewport,
        }).render()
      }
    }

    void renderPages().catch((error: unknown) => {
      if (cancelled) return
      suppressScroll.current = false
      onError(error instanceof Error ? error.message : t("underlag.previewPdfError"))
    })
    return () => {
      cancelled = true
      rootNode.replaceChildren()
    }
  }, [document, layoutWidth, onError, t, zoom])

  useEffect(() => {
    const viewport = viewportRef.current
    const root = pagesRef.current
    if (!viewport || !root || rendered === 0) return
    const report = () => {
      if (suppressScroll.current || !onVisiblePageRef.current) return
      const pages = [...root.querySelectorAll<HTMLElement>("[data-page-number]")].flatMap((node) => {
        const page = Number(node.dataset.pageNumber)
        if (!Number.isInteger(page) || page < 1) return []
        const rect = node.getBoundingClientRect()
        return [{ page, top: rect.top, bottom: rect.bottom }]
      })
      const next = pageAtViewportTop(pages, viewport.getBoundingClientRect().top)
      if (next == null || next === requestedPage.current) return
      scrolledTo.current = next
      onVisiblePageRef.current(next)
    }
    viewport.addEventListener("scroll", report, { passive: true })
    return () => {
      viewport.removeEventListener("scroll", report)
      cancelScrollHold.current?.()
    }
  }, [rendered])

  useEffect(() => {
    const viewport = viewportRef.current
    const root = pagesRef.current
    if (!viewport || !root || pageNumber == null || rendered === 0) {
      suppressScroll.current = false
      return
    }
    const key = `${layoutWidth}:${zoom}:${pageNumber}`
    if (followedPage.current === key) return
    if (scrolledTo.current === pageNumber) {
      followedPage.current = key
      suppressScroll.current = false
      return
    }
    const page = root.querySelector<HTMLElement>(`[data-page-number="${pageNumber}"]`)
    if (!page) return
    followedPage.current = key
    const delta = page.getBoundingClientRect().top - viewport.getBoundingClientRect().top
    if (Math.abs(delta) < 1) return
    holdProgrammaticScroll(viewport, suppressScroll, cancelScrollHold)
    viewport.scrollTop += delta
  }, [layoutWidth, pageNumber, rendered, zoom])

  useEffect(() => {
    const root = pagesRef.current
    if (!root) return
    root.querySelectorAll("[data-document-anchor-highlight]").forEach((node) => node.remove())
    const highlights = focusAnchors.map(highlightOf)
    let firstMarker: HTMLElement | null = null
    let userMarker: HTMLElement | null = null
    let matchedAnchors = 0
    for (const highlight of highlights) {
      const anchor = highlight.anchor
      if (pdfAnchorKind(anchor) !== "page") continue
      const page = root.querySelector<HTMLElement>(
        `[data-page-number="${anchor.page_number}"]`,
      )
      if (!page) continue
      const rectangles = pdfAnchorRectangles(anchor)
      if (rectangles.length > 0) matchedAnchors += 1
      const color = markColor(highlight.authorKind, highlight.authorId)
      for (const [index, rect] of rectangles.entries()) {
        const marker = window.document.createElement("div")
        marker.dataset.documentAnchorHighlight = "true"
        const locked = highlight.authorKind === "expert" || (readerId != null && highlight.authorKind === "user" && !!highlight.authorId && highlight.authorId !== readerId)
        if (highlight.passageKey) marker.dataset.passageKey = highlight.passageKey
        if (locked) marker.dataset.markForeign = "true"
        marker.className = `${locked || (commentsOpen && highlight.passageKey) ? "cursor-pointer" : "pointer-events-none"} absolute z-20 rounded-sm mix-blend-multiply`
        marker.style.backgroundColor = color.fill
        marker.style.boxShadow = `inset 0 0 0 1px ${color.ring}`
        marker.style.left = `${rect.x * 100}%`
        marker.style.top = `${rect.y * 100}%`
        marker.style.width = `${rect.width * 100}%`
        marker.style.height = `${rect.height * 100}%`
        page.append(marker)
        if (firstMarker === null) firstMarker = marker
        if (highlight.authorKind === "user" && index === 0) userMarker = marker
        if (index === 0 && highlight.authorName) page.append(markLabel(rect, highlight.authorName, color.ink, color.ring))
      }
    }
    const focusKey = highlights.map((highlight) => `${highlight.anchor.page_number ?? ""}:${highlight.authorKind ?? ""}:${highlight.authorName ?? ""}:${highlight.anchor.exact_text ?? ""}:${highlight.anchor.rects?.length ?? 0}`).join("|")
    const scrollMarker = userMarker ?? firstMarker
    const markerPage = Number(scrollMarker?.closest<HTMLElement>("[data-page-number]")?.dataset.pageNumber)
    const focusChanged = appliedFocus.current !== focusKey
    appliedFocus.current = focusKey
    const viewport = viewportRef.current
    if (focusChanged && scrollMarker && viewport && (requestedPage.current == null || markerPage === requestedPage.current)) {
      const viewportRect = viewport.getBoundingClientRect()
      const markerRect = scrollMarker.getBoundingClientRect()
      const delta = markerRect.top + markerRect.height / 2 - (viewportRect.top + viewportRect.height / 2)
      if (markerOutsideViewport(markerRect, viewportRect) && Math.abs(delta) >= 1) {
        holdProgrammaticScroll(viewport, suppressScroll, cancelScrollHold)
        viewport.scrollTop += delta
      }
    }
    const stage = stageRef.current
    const nextAnchors: PdfMarkAnchor[] = []
    if (commentsOpen && stage) {
      const origin = stage.getBoundingClientRect().top
      const seen = new Set<string>()
      for (const node of root.querySelectorAll<HTMLElement>("[data-passage-key]")) {
        const key = node.dataset.passageKey
        if (!key || seen.has(key)) continue
        seen.add(key)
        const rect = node.getBoundingClientRect()
        nextAnchors.push({ key, top: rect.top - origin, height: rect.height })
      }
    }
    setMarkAnchors((current) => sameMarkAnchors(current, nextAnchors) ? current : nextAnchors)
    const status = pdfPresentationStatus(highlights.map((highlight) => highlight.anchor), rendered > 0 && root.dataset.renderComplete === "true", matchedAnchors)
    if (status === "anchor_missing") onError(t("voiceWorkspaceChat.presentationError"))
    else if (status === "ready") onReady?.()
  }, [commentsOpen, focusAnchors, onError, onReady, presentationRevision, readerId, rendered, t])

  useEffect(() => {
    if (selectionActive) return
    const root = pagesRef.current
    const selection = window.getSelection()
    if (!root || !selection || selection.rangeCount === 0) return
    const anchorInside = selection.anchorNode != null && root.contains(selection.anchorNode)
    const focusInside = selection.focusNode != null && root.contains(selection.focusNode)
    if (anchorInside || focusInside) selection.removeAllRanges()
  }, [selectionActive])

  function captureSelection() {
    const selection = window.getSelection()
    const root = pagesRef.current
    if (!selection || selection.isCollapsed || selection.rangeCount === 0 || !root) return
    const range = selection.getRangeAt(0)
    const start = closestPage(range.startContainer)
    const end = closestPage(range.endContainer)
    if (!start || start !== end || !root.contains(start)) return
    const bounds = start.getBoundingClientRect()
    const pdfWidth = Number(start.dataset.pdfWidth)
    if (!(pdfWidth > 0) || !(bounds.width > 0)) return
    const fragments: PdfSelectionFragment[] = []
    const selectedRects: DOMRect[] = []
    const walker = window.document.createTreeWalker(start.querySelector(".textLayer")!, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!range.intersectsNode(node)) continue
      const part = window.document.createRange()
      part.selectNodeContents(node)
      if (range.compareBoundaryPoints(Range.START_TO_START, part) > 0) part.setStart(range.startContainer, range.startOffset)
      if (range.compareBoundaryPoints(Range.END_TO_END, part) < 0) part.setEnd(range.endContainer, range.endOffset)
      if (part.collapsed || !part.toString()) continue
      const position = part.getBoundingClientRect(), scale = pdfWidth / bounds.width
      fragments.push({ text: part.toString(), x: (position.left - bounds.left) * scale, y: (position.top - bounds.top) * scale, width: position.width * scale })
      selectedRects.push(...Array.from(part.getClientRects()))
    }
    const exactText = pdfSelectionText(fragments)
    if (!exactText) return
    const rects: DocumentAnchorRect[] = selectedRects
      .filter((rect) => rect.width > 0 && rect.height > 0)
      .flatMap((rect) => {
        const x = clamp((rect.left - bounds.left) / bounds.width), right = clamp((rect.right - bounds.left) / bounds.width)
        const y = clamp((rect.top - bounds.top) / bounds.height), bottom = clamp((rect.bottom - bounds.top) / bounds.height)
        return right > x && bottom > y ? [{ x, y, width: right - x, height: bottom - y }] : []
      })
    const pageNumber = Number(start.dataset.pageNumber)
    if (!Number.isInteger(pageNumber) || pageNumber < 1 || rects.length === 0) return
    onSelection({
      anchor_type: "text",
      page_number: pageNumber,
      locator: `page:${pageNumber}`,
      exact_text: exactText,
      prefix_text: null,
      suffix_text: null,
      rects,
      asset_id: null,
    })
  }

  return (
    <div
      ref={viewportRef}
      className="h-full overflow-auto bg-db-ink-950/5 px-2 py-4 [scrollbar-gutter:stable]"
      onMouseDown={(event) => {
        gestureRef.current = event.button === 0 && event.target instanceof Node && pagesRef.current?.contains(event.target) && closestPage(event.target)
          ? { x: event.clientX, y: event.clientY, moved: false } : null
      }}
      onMouseMove={(event) => {
        const gesture = gestureRef.current
        if (gesture && Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) >= 3) gesture.moved = true
      }}
      onPointerCancel={() => { gestureRef.current = null }}
      onDragStart={() => { gestureRef.current = null }}
      onMouseUp={(event) => {
        const gesture = gestureRef.current
        gestureRef.current = null
        const action = pdfSelectionGesture({ button: event.button, started: gesture !== null, moved: gesture?.moved === true || (gesture !== null && Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) >= 3), clickCount: event.detail, shiftKey: event.shiftKey })
        if (action === "select") { captureSelection(); return }
        if (action !== "clear") return
        const passage = event.target instanceof Element ? event.target.closest<HTMLElement>("[data-passage-key]") : null
        const key = passage?.dataset.passageKey
        if (key && (commentsOpen || passage?.dataset.markForeign === "true")) { onFocusPassage?.(key); return }
        const root = pagesRef.current
        root?.querySelectorAll("[data-document-anchor-highlight]").forEach((node) => node.remove())
        const selection = window.getSelection()
        if (selection && ((selection.anchorNode && root?.contains(selection.anchorNode)) || (selection.focusNode && root?.contains(selection.focusNode)))) selection.removeAllRanges()
        onClearSelection()
      }}
    >
      <div ref={stageRef} className="flex min-h-full">
        <div ref={pagesRef} className="flex min-w-0 flex-1 flex-col gap-4" />
        {commentsOpen ? <div className="relative w-[296px] shrink-0 border-l border-[color:var(--border-hairline)] bg-db-ink-50">{renderComments?.(markAnchors)}</div> : null}
      </div>
    </div>
  )
}

function sameMarkAnchors(left: PdfMarkAnchor[], right: PdfMarkAnchor[]): boolean {
  return left.length === right.length && left.every((row, index) => row.key === right[index]?.key && Math.abs(row.top - (right[index]?.top ?? 0)) < 0.5 && Math.abs(row.height - (right[index]?.height ?? 0)) < 0.5)
}

function isPdfHighlight(value: DocumentKnowledgeAnchor | PdfHighlight): value is PdfHighlight {
  return "anchor" in value && value.anchor != null && typeof value.anchor === "object" && "anchor_type" in value.anchor
}

function highlightOf(value: DocumentKnowledgeAnchor | PdfHighlight): PdfHighlight {
  if (isPdfHighlight(value)) return value
  return { anchor: value }
}

function markLabel(rect: DocumentAnchorRect, name: string, ink: string, ring: string): HTMLDivElement {
  const label = window.document.createElement("div")
  label.dataset.documentAnchorHighlight = "label"
  label.textContent = name
  label.className = "pointer-events-none absolute z-30 max-w-[9rem] truncate rounded-sm bg-white/90 px-1 text-[10px] leading-4"
  label.style.color = ink
  label.style.boxShadow = `inset 2px 0 0 ${ring}`
  label.style.left = `${rect.x * 100}%`
  const above = rect.y > 0.035
  label.style.top = above ? `${rect.y * 100}%` : `${(rect.y + rect.height) * 100}%`
  if (above) label.style.transform = "translateY(-100%)"
  return label
}

function closestPage(node: Node): HTMLElement | null {
  const element = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement
  return element?.closest<HTMLElement>("[data-page-number]") ?? null
}

function clamp(value: number): number {
  return Math.max(0, Math.min(1, value))
}
