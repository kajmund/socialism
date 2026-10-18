import { useEffect, useRef, useState } from "react"
import { renderAsync } from "docx-preview"
import type { PDFDocumentLoadingTask } from "pdfjs-dist"
import type { UnderlagFile } from "@/api/underlag"
import { voiceWorkspaces } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { isDocxSource, isPdfSource } from "@/lib/sourceKind"

export function DocumentThumbnail({ workspaceId, source }: {
  workspaceId: string
  source: UnderlagFile
}) {
  const { t } = useLocale()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const docxRef = useRef<HTMLDivElement>(null)
  const [blob, setBlob] = useState<Blob | null>(null)
  const [text, setText] = useState("")
  const [error, setError] = useState(false)
  const sourceId = source.id
  const contentType = source.content_type
  const filename = source.filename
  const kind = { content_type: contentType, filename }
  const pdfSource = isPdfSource(kind)
  const docxSource = isDocxSource(kind)

  useEffect(() => {
    let cancelled = false
    setBlob(null)
    setText("")
    setError(false)
    void voiceWorkspaces.sourceFile(workspaceId, sourceId).then(async (file) => {
      if (cancelled) return
      setBlob(file)
      if (!pdfSource && !docxSource) setText((await file.text()).slice(0, 1200))
    }).catch(() => {
      if (!cancelled) setError(true)
    })
    return () => { cancelled = true }
  }, [docxSource, pdfSource, sourceId, workspaceId])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!blob || !canvas || !pdfSource) return
    let cancelled = false
    let task: PDFDocumentLoadingTask | null = null
    void Promise.all([
      import("pdfjs-dist"),
      import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
      blob.arrayBuffer(),
    ]).then(async ([pdfjs, worker, data]) => {
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default
      task = pdfjs.getDocument({ data })
      const document = await task.promise
      const page = await document.getPage(1)
      if (cancelled) return
      const viewport = page.getViewport({ scale: 0.45 })
      const context = canvas.getContext("2d")
      if (!context) throw new Error("thumbnail_canvas_unavailable")
      canvas.width = Math.floor(viewport.width)
      canvas.height = Math.floor(viewport.height)
      await page.render({ canvas, canvasContext: context, viewport }).promise
    }).catch(() => {
      if (!cancelled) setError(true)
    })
    return () => {
      cancelled = true
      if (task) void task.destroy()
    }
  }, [blob, pdfSource])

  useEffect(() => {
    const host = docxRef.current
    if (!blob || !host || !docxSource) return
    let cancelled = false
    host.replaceChildren()
    void renderAsync(blob, host, undefined, {
      className: "docx-thumbnail",
      inWrapper: true,
      breakPages: true,
      ignoreLastRenderedPageBreak: false,
      experimental: true,
      useBase64URL: true,
    }).then(() => {
      if (cancelled) return
      const pages = host.querySelectorAll(":scope .docx-wrapper > section")
      pages.forEach((page, index) => { if (index > 0) page.remove() })
    }).catch(() => {
      if (!cancelled) setError(true)
    })
    return () => {
      cancelled = true
      host.replaceChildren()
    }
  }, [blob, docxSource])

  if (error) return <div className="grid h-full place-items-center p-3 text-center text-xs text-destructive">{t("voiceWorkspaceChat.thumbnailError")}</div>
  if (!blob) return <div className="grid h-full place-items-center text-xs text-muted-foreground">{t("voiceWorkspaceChat.thumbnailLoading")}</div>
  if (pdfSource) return <canvas ref={canvasRef} className="block h-full w-full object-contain object-top" />
  if (docxSource) {
    return <div className="h-full overflow-hidden bg-white">
      <div className="origin-top-left scale-[0.22] [&_.docx-wrapper]:!p-0" style={{ width: "454.55%" }} ref={docxRef} />
    </div>
  }
  return <div className="h-full overflow-hidden whitespace-pre-wrap bg-white p-4 text-[8px] leading-3 text-db-ink-700">{text}</div>
}
