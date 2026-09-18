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

GlobalWorkerOptions.workerSrc = workerUrl

export function PdfKnowledgeViewer({
  url,
  focusAnchor,
  onSelection,
  onError,
}: {
  url: string
  focusAnchor: DocumentKnowledgeAnchor | null
  onSelection: (anchor: DocumentKnowledgeAnchor) => void
  onError: (message: string) => void
}) {
  const { t } = useLocale()
  const viewportRef = useRef<HTMLDivElement>(null)
  const pagesRef = useRef<HTMLDivElement>(null)
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
        if (!cancelled) setDocument(pdf)
      })
      .catch((error: unknown) => {
        if (!cancelled) onError(error instanceof Error ? error.message : t("underlag.previewPdfError"))
      })
    return () => {
      cancelled = true
      setDocument(null)
      void task.destroy()
    }
  }, [onError, t, url])

  useEffect(() => {
    const root = pagesRef.current
    if (!document || !root || width <= 0) return
    const pdf = document
    const rootNode = root
    let cancelled = false
    rootNode.replaceChildren()

    async function renderPages() {
      for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
        if (cancelled) return
        const page = await pdf.getPage(pageNumber)
        const baseViewport = page.getViewport({ scale: 1 })
        const available = Math.max(240, width - 32)
        const scale = Math.min(2, available / baseViewport.width)
        const viewport = page.getViewport({ scale })
        const wrapper = window.document.createElement("div")
        wrapper.className = "pdf-page relative mx-auto bg-white shadow-sm"
        wrapper.dataset.pageNumber = String(pageNumber)
        wrapper.style.width = `${viewport.width}px`
        wrapper.style.height = `${viewport.height}px`

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
      if (!cancelled) setRendered((value) => value + 1)
    }

    void renderPages().catch((error: unknown) => {
      if (!cancelled) onError(error instanceof Error ? error.message : t("underlag.previewPdfError"))
    })
    return () => {
      cancelled = true
      rootNode.replaceChildren()
    }
  }, [document, onError, t, width])

  useEffect(() => {
    const root = pagesRef.current
    if (!root) return
    root.querySelectorAll("[data-document-anchor-highlight]").forEach((node) => node.remove())
    if (!focusAnchor?.page_number) return
    const page = root.querySelector<HTMLElement>(
      `[data-page-number="${focusAnchor.page_number}"]`,
    )
    if (!page) return
    for (const rect of focusAnchor.rects) {
      const marker = window.document.createElement("div")
      marker.dataset.documentAnchorHighlight = "true"
      marker.className = "pointer-events-none absolute z-20 rounded-sm bg-db-gold-400/35 ring-1 ring-db-gold-500/70"
      marker.style.left = `${rect.x * 100}%`
      marker.style.top = `${rect.y * 100}%`
      marker.style.width = `${rect.width * 100}%`
      marker.style.height = `${rect.height * 100}%`
      page.append(marker)
    }
    page.scrollIntoView({ behavior: "smooth", block: "center" })
  }, [focusAnchor, rendered])

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
      .map((rect) => ({
        x: clamp((rect.left - bounds.left) / bounds.width),
        y: clamp((rect.top - bounds.top) / bounds.height),
        width: clamp(rect.width / bounds.width, 0.0001),
        height: clamp(rect.height / bounds.height, 0.0001),
      }))
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
      className="h-full overflow-y-auto bg-db-ink-950/5 px-2 py-4"
      onMouseUp={captureSelection}
    >
      <div ref={pagesRef} className="flex min-h-full flex-col gap-4" />
    </div>
  )
}

function closestPage(node: Node): HTMLElement | null {
  const element = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement
  return element?.closest<HTMLElement>("[data-page-number]") ?? null
}

function clamp(value: number, minimum = 0): number {
  return Math.max(minimum, Math.min(1, value))
}
