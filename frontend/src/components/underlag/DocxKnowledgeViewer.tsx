import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { renderAsync } from "docx-preview"
import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import { useLocale } from "@/i18n"
import { markColor, type MarkAuthorKind } from "./documentMarkColor"
import { docxSelectionAnchor } from "./docxSelection"

export type DocxHighlight = {
  exact_text?: string | null
  authorKind?: MarkAuthorKind
  authorId?: string | null
  authorName?: string | null
  passageKey?: string
  locked?: boolean
}

export function DocxKnowledgeViewer({
  blob,
  zoom = 1,
  pageNumber,
  focusAnchors = [],
  onReady,
  onError,
  onPageCount,
  onVisiblePage,
  onSelection,
  onClearSelection,
  onFocusPassage,
  commentsOpen = false,
}: {
  blob: Blob
  zoom?: number
  pageNumber?: number
  focusAnchors?: DocxHighlight[]
  onReady?: () => void
  onError: (message: string) => void
  onPageCount?: (count: number) => void
  onVisiblePage?: (page: number) => void
  onSelection?: (anchor: DocumentKnowledgeAnchor) => void
  onClearSelection?: () => void
  onFocusPassage?: (passageKey: string) => void
  commentsOpen?: boolean
}) {
  const { t } = useLocale()
  const hostRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const [rendered, setRendered] = useState(0)
  const callbacks = useRef({ onReady, onError, onPageCount })
  callbacks.current = { onReady, onError, onPageCount }

  useEffect(() => {
    const body = bodyRef.current
    if (!body) return
    let cancelled = false
    body.replaceChildren()
    void renderAsync(blob, body, undefined, {
      className: "docx",
      inWrapper: true,
      breakPages: true,
      ignoreLastRenderedPageBreak: false,
      experimental: true,
      useBase64URL: true,
    }).then(() => {
      if (cancelled) return
      callbacks.current.onPageCount?.(docxPages(body).length)
      setRendered((value) => value + 1)
      callbacks.current.onReady?.()
    }).catch(() => {
      if (!cancelled) callbacks.current.onError(t("underlag.previewDocxError"))
    })
    return () => {
      cancelled = true
      body.replaceChildren()
    }
  }, [blob, t])

  useLayoutEffect(() => {
    const body = bodyRef.current
    if (!body) return
    paintDocxMarks(body, focusAnchors)
  }, [blob, focusAnchors, rendered])

  useEffect(() => {
    const host = hostRef.current
    const body = bodyRef.current
    if (!host || !body || pageNumber == null) return
    const page = docxPages(body)[pageNumber - 1]
    if (page) host.scrollTo({ top: page.offsetTop, behavior: "auto" })
  }, [blob, pageNumber])

  return (
    <div
      ref={hostRef}
      className="docx-preview-host h-full min-h-0 flex-1 overflow-auto bg-db-ink-100"
      onScroll={() => {
        const host = hostRef.current
        const body = bodyRef.current
        if (!host || !body || !onVisiblePage) return
        const top = host.scrollTop + 24
        const pages = docxPages(body)
        let visible = 1
        for (const [index, page] of pages.entries()) {
          if (page.offsetTop <= top) visible = index + 1
        }
        onVisiblePage(visible)
      }}
      onMouseUp={(event) => {
        if (event.button !== 0) return
        const node = event.target instanceof Element ? event.target.closest<HTMLElement>("[data-passage-key]") : null
        const key = node?.dataset.passageKey
        if (key && (commentsOpen || node?.dataset.markForeign === "true")) {
          onFocusPassage?.(key)
          window.getSelection()?.removeAllRanges()
          return
        }
        const selection = window.getSelection()
        const body = bodyRef.current
        if (!selection || !body) return
        const anchor = docxSelectionAnchor(body, selection)
        if (anchor) onSelection?.(anchor)
        else if (selection.isCollapsed) onClearSelection?.()
      }}
    >
      <div className="docx-preview-scale origin-top" style={{ transform: `scale(${zoom})`, width: `${100 / zoom}%` }}>
        <div ref={bodyRef} />
      </div>
    </div>
  )
}

function docxPages(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(":scope .docx-wrapper > section")]
}

function paintDocxMarks(root: HTMLElement, highlights: DocxHighlight[]) {
  root.querySelectorAll("[data-docx-mark]").forEach((node) => {
    const parent = node.parentNode
    if (!parent) return
    node.querySelector("[data-mark-label]")?.remove()
    parent.replaceChild(document.createTextNode(node.textContent ?? ""), node)
    parent.normalize()
  })
  for (const highlight of highlights) {
    const exact = highlight.exact_text?.trim()
    if (!exact) continue
    wrapExactText(root, exact, highlight)
  }
}

function wrapExactText(root: HTMLElement, exact: string, highlight: DocxHighlight) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node) {
    const text = node as Text
    const index = text.data.indexOf(exact)
    if (index === -1) {
      node = walker.nextNode()
      continue
    }
    const range = document.createRange()
    range.setStart(text, index)
    range.setEnd(text, index + exact.length)
    const mark = document.createElement("mark")
    mark.dataset.docxMark = "true"
    if (highlight.passageKey) mark.dataset.passageKey = highlight.passageKey
    if (highlight.locked) mark.dataset.markForeign = "true"
    const tone = markColor(highlight.authorKind, highlight.authorId)
    mark.className = "rounded px-0.5"
    mark.style.backgroundColor = tone.fill
    if (highlight.authorName) {
      const label = document.createElement("span")
      label.dataset.markLabel = ""
      label.className = "mr-1 select-none text-[10px] font-medium"
      label.style.color = tone.ink
      label.textContent = highlight.authorName
      mark.append(label)
    }
    range.surroundContents(mark)
    return
  }
}
