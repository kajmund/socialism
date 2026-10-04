import { useEffect, useRef, useState } from "react"
import {
  getDocument,
  GlobalWorkerOptions,
  TextLayer,
  type PDFDocumentProxy,
} from "pdfjs-dist"
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url"
import "pdfjs-dist/web/pdf_viewer.css"
import type {
  DocumentKnowledgeAnchor,
  DocumentAnchorRect,
} from "@/api/underlag"
import { useLocale } from "@/i18n"
import { pdfAnchorKind, pdfAnchorRectangles, pdfPresentationStatus } from "./pdfAnchorPresentation"
import { pdfSelectionGesture } from "./pdfSelectionGesture"

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
  presentationRevision,
}: {
  url: string
  focusAnchors: DocumentKnowledgeAnchor[]
  selectionActive: boolean
  onSelection: (anchor: DocumentKnowledgeAnchor) => void
  onClearSelection: () => void
  onError: (message: string) => void
  pageNumber?: number
  zoom?: number
  onReady?: () => void
  onPageCount?: (count: number) => void
  presentationRevision?: number
}) {
  const { t } = useLocale()
  const viewportRef = useRef<HTMLDivElement>(null)
  const pagesRef = useRef<HTMLDivElement>(null)
  const gestureRef = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null)
  const [width, setWidth] = useState(0)
  const [rendered, setRendered] = useState(0)

  useEffect(() => {
    const node = viewportRef.current
    if (!node) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
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
    if (!document || !root || width <= 0) return
    const pdf = document
    const rootNode = root
    let cancelled = false
    rootNode.replaceChildren()
    rootNode.dataset.renderComplete = "false"

    async function renderPages() {
      const first = pageNumber ?? 1
      const last = pageNumber ?? pdf.numPages
      if (first < 1 || last > pdf.numPages) throw new Error(t("voiceWorkspaceChat.presentationError"))
      for (let pageNumber = first; pageNumber <= last; pageNumber += 1) {
        if (cancelled) return
        const page = await pdf.getPage(pageNumber)
        if (cancelled) return
        const baseViewport = page.getViewport({ scale: 1 })
        const available = Math.max(240, width - 32)
        const scale = Math.min(2, available / baseViewport.width) * zoom
        const viewport = page.getViewport({ scale })
        const wrapper = window.document.createElement("div")
        wrapper.className = "pdf-page relative mx-auto bg-white shadow-sm"
        wrapper.dataset.pageNumber = String(pageNumber)
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

        const context = canvas.getContext("2d")
        if (!context) throw new Error("Canvas is unavailable")
        await page.render({
          canvas,
          canvasContext: context,
          viewport,
          transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
        }).promise
        const textContent = await page.getTextContent()
        await new TextLayer({
          textContentSource: textContent,
          container: textNode,
          viewport,
        }).render()
      }
      if (!cancelled) { rootNode.dataset.renderComplete = "true"; setRendered((value) => value + 1) }
    }

    void renderPages().catch((error: unknown) => {
      if (!cancelled) onError(error instanceof Error ? error.message : t("underlag.previewPdfError"))
    })
    return () => {
      cancelled = true
      rootNode.replaceChildren()
    }
  }, [document, onError, pageNumber, t, width, zoom])

  useEffect(() => {
    const root = pagesRef.current
    if (!root) return
    root.querySelectorAll("[data-document-anchor-highlight]").forEach((node) => node.remove())
    let firstMarker: HTMLElement | null = null
    let matchedAnchors = 0
    for (const anchor of focusAnchors) {
      if (pdfAnchorKind(anchor) !== "page") continue
      const page = root.querySelector<HTMLElement>(
        `[data-page-number="${anchor.page_number}"]`,
      )
      if (!page) continue
      const rectangles = pdfAnchorRectangles(anchor)
      if (rectangles.length > 0) matchedAnchors += 1
      for (const rect of rectangles) {
        const marker = window.document.createElement("div")
        marker.dataset.documentAnchorHighlight = "true"
        marker.className = "pointer-events-none absolute z-20 rounded-sm bg-db-gold-500/60 mix-blend-multiply ring-1 ring-db-gold-700"
        marker.style.left = `${rect.x * 100}%`
        marker.style.top = `${rect.y * 100}%`
        marker.style.width = `${rect.width * 100}%`
        marker.style.height = `${rect.height * 100}%`
        page.append(marker)
        firstMarker ??= marker
      }
    }
    firstMarker?.scrollIntoView({ behavior: "smooth", block: "center" })
    const status = pdfPresentationStatus(focusAnchors, rendered > 0 && root.dataset.renderComplete === "true", matchedAnchors)
    if (status === "anchor_missing") onError(t("voiceWorkspaceChat.presentationError"))
    else if (status === "ready") onReady?.()
  }, [focusAnchors, onError, onReady, presentationRevision, rendered, t])

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
    const exactText = selection.toString().split(/\s+/).join(" ").trim()
    if (!exactText) return
    const bounds = start.getBoundingClientRect()
    const rects: DocumentAnchorRect[] = Array.from(range.getClientRects())
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
      className="h-full overflow-auto bg-db-ink-950/5 px-2 py-4"
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
        const root = pagesRef.current
        root?.querySelectorAll("[data-document-anchor-highlight]").forEach((node) => node.remove())
        const selection = window.getSelection()
        if (selection && ((selection.anchorNode && root?.contains(selection.anchorNode)) || (selection.focusNode && root?.contains(selection.focusNode)))) selection.removeAllRanges()
        onClearSelection()
      }}
    >
      <div ref={pagesRef} className="flex min-h-full flex-col gap-4" />
    </div>
  )
}

function closestPage(node: Node): HTMLElement | null {
  const element = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement
  return element?.closest<HTMLElement>("[data-page-number]") ?? null
}

function clamp(value: number): number {
  return Math.max(0, Math.min(1, value))
}
