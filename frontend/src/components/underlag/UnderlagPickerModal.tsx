import { useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react"
import { FileText, Folder } from "lucide-react"
import { getReportHtml, listReports, type Report } from "@/api/reports"
import {
  createUnderlagFolder,
  deleteUnderlag,
  getUnderlag,
  getUnderlagFile,
  listUnderlag,
  listUnderlagFolders,
  moveUnderlag,
  uploadUnderlag,
  type UnderlagExtractionStatus,
  type UnderlagFile,
  type UnderlagFolder,
} from "@/api/underlag"
import { useAuth } from "@/auth/AuthProvider"
import { AdminButton } from "@/components/ui/admin-button"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Markdown } from "@/components/ui/markdown"
import { htmlToPlainText } from "@/components/underlag/htmlToPlainText"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { moduleForReport, reportModulesForUser } from "@/lib/report-modules"
import { cn } from "@/lib/utils"
import { MODULE_REGISTRY } from "@/modules/moduleRegistry"

const ACCEPT = ".txt,.md,.markdown,.pdf,.docx"

type PreviewTab = "pdf" | "text" | "html"

type BrowseLoc =
  | { kind: "underlag"; folderId: string | null }
  | { kind: "reports"; moduleId: string }

type PreviewState =
  | { kind: "underlag"; file: UnderlagFile }
  | {
      kind: "report"
      report: Report
      html: string | null
      text: string | null
      loading: boolean
      error: string | null
    }

function statusKey(status: UnderlagExtractionStatus | null): MessageKey {
  switch (status) {
    case "ok":
      return "underlag.status.ok"
    case "failed":
      return "underlag.status.failed"
    case "empty":
      return "underlag.status.empty"
    case "unsupported":
      return "underlag.status.unsupported"
    case null:
      return "underlag.status.failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function statusVariant(
  status: UnderlagExtractionStatus | null,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "ok":
      return "default"
    case "failed":
    case "unsupported":
      return "destructive"
    case "empty":
      return "outline"
    case null:
      return "secondary"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function isPdf(file: UnderlagFile): boolean {
  return file.content_type === "application/pdf"
}

function childrenOf(
  all: UnderlagFolder[],
  parentId: string | null,
  locale: string,
): UnderlagFolder[] {
  return all
    .filter((folder) => folder.parent_id === parentId)
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name, locale))
}

function safeUploadName(title: string): string {
  const cleaned = title.replace(/[^\w\-åäöÅÄÖ ]+/gi, "").trim().slice(0, 60)
  return `${cleaned || "rapport"}.txt`
}

export function UnderlagPickerModal({
  open,
  module,
  onOpenChange,
  onSelect,
  onDeleted,
}: {
  open: boolean
  module: string
  onOpenChange: (open: boolean) => void
  onSelect: (file: UnderlagFile) => void
  onDeleted?: (objectId: string) => void
}) {
  const { t, intl } = useLocale()
  const { user, resolvedModules } = useAuth()
  const kundSlug = user?.kundSlug?.trim() || t("underlag.treeKundFallback")
  const dateFmt = new Intl.DateTimeFormat(intl, { dateStyle: "medium" })
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderNameRef = useRef<HTMLInputElement>(null)
  const pdfObjectUrlRef = useRef<string | null>(null)
  const draggingFileIdRef = useRef<string | null>(null)
  const [browse, setBrowse] = useState<BrowseLoc>({ kind: "underlag", folderId: null })
  const [allFolders, setAllFolders] = useState<UnderlagFolder[]>([])
  const [rows, setRows] = useState<UnderlagFile[]>([])
  const [reports, setReports] = useState<Report[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [creatingFolder, setCreatingFolder] = useState(false)
  const [namingFolder, setNamingFolder] = useState(false)
  const [folderName, setFolderName] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewTab, setPreviewTab] = useState<PreviewTab>("pdf")
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const [dropTargetId, setDropTargetId] = useState<string | null>(null)
  const [moving, setMoving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [usingReport, setUsingReport] = useState(false)

  const folderId = browse.kind === "underlag" ? browse.folderId : null
  const browsingUnderlag = browse.kind === "underlag"
  const browsingReports = browse.kind === "reports"

  const moduleIds = useMemo(() => {
    const ids = new Set<string>()
    for (const id of reportModulesForUser(user)) ids.add(id)
    for (const id of resolvedModules) {
      if (id in MODULE_REGISTRY) ids.add(id)
    }
    if (module in MODULE_REGISTRY) ids.add(module)
    return [...ids]
  }, [module, resolvedModules, user])

  const reportsByModule = useMemo(() => {
    const map = new Map<string, Report[]>()
    for (const report of reports) {
      if (report.status !== "succeeded") continue
      let moduleId: string
      try {
        moduleId = moduleForReport(report)
      } catch {
        continue
      }
      const list = map.get(moduleId) ?? []
      list.push(report)
      map.set(moduleId, list)
    }
    for (const list of map.values()) {
      list.sort((a, b) => b.created_at.localeCompare(a.created_at))
    }
    return map
  }, [reports])

  function clearPdfUrl() {
    if (pdfObjectUrlRef.current) {
      URL.revokeObjectURL(pdfObjectUrlRef.current)
      pdfObjectUrlRef.current = null
    }
    setPdfUrl(null)
  }

  function clearPreview() {
    setPreview(null)
    setPreviewTab("pdf")
    setPdfError(null)
    setPdfLoading(false)
    clearPdfUrl()
    setConfirmDelete(false)
  }

  async function refreshFolders() {
    const listed = await listUnderlagFolders(module)
    setAllFolders(listed)
    return listed
  }

  useEffect(() => {
    setBrowse({ kind: "underlag", folderId: null })
    setAllFolders([])
    setRows([])
    setReports([])
    clearPreview()
    setNamingFolder(false)
    setFolderName("")
    setError(null)
  }, [module])

  useEffect(() => {
    if (open) return
    setBrowse({ kind: "underlag", folderId: null })
    clearPreview()
    setNamingFolder(false)
    setFolderName("")
    setError(null)
    setDropTargetId(null)
  }, [open])

  useEffect(() => {
    return () => {
      if (pdfObjectUrlRef.current) {
        URL.revokeObjectURL(pdfObjectUrlRef.current)
        pdfObjectUrlRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    listUnderlagFolders(module)
      .then((listed) => {
        if (!cancelled) setAllFolders(listed)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("underlag.loadError"))
        }
      })
    listReports({ status: "succeeded", limit: 100 })
      .then((listed) => {
        if (!cancelled) setReports(listed)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("underlag.reportsLoadError"))
        }
      })
    return () => {
      cancelled = true
    }
  }, [module, open, t])

  useEffect(() => {
    if (!open || !browsingUnderlag) return
    let cancelled = false
    setLoading(true)
    setError(null)
    listUnderlag(module, folderId)
      .then((listed) => {
        if (!cancelled) setRows(listed.files)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("underlag.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [browsingUnderlag, folderId, module, open, t])

  useEffect(() => {
    if (namingFolder) folderNameRef.current?.focus()
  }, [namingFolder])

  useEffect(() => {
    if (preview?.kind !== "underlag" || !isPdf(preview.file) || previewTab !== "pdf") {
      clearPdfUrl()
      setPdfError(null)
      setPdfLoading(false)
      return
    }
    let cancelled = false
    setPdfLoading(true)
    setPdfError(null)
    clearPdfUrl()
    getUnderlagFile(preview.file.id)
      .then((blob) => {
        if (cancelled) return
        const url = URL.createObjectURL(blob)
        pdfObjectUrlRef.current = url
        setPdfUrl(url)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setPdfError(err instanceof ApiError ? err.message : t("underlag.previewPdfError"))
        }
      })
      .finally(() => {
        if (!cancelled) setPdfLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [preview, previewTab, t])

  async function loadPreview(id: string) {
    setPreviewLoading(true)
    setError(null)
    setConfirmDelete(false)
    try {
      const row = await getUnderlag(id)
      setPreview({ kind: "underlag", file: row })
      setPreviewTab(isPdf(row) ? "pdf" : "text")
      setRows((current) => current.map((item) => (item.id === row.id ? { ...item, ...row } : item)))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("underlag.loadError"))
    } finally {
      setPreviewLoading(false)
    }
  }

  async function loadReportPreview(report: Report) {
    setPreviewLoading(true)
    setConfirmDelete(false)
    setPreview({
      kind: "report",
      report,
      html: null,
      text: null,
      loading: true,
      error: null,
    })
    setPreviewTab("html")
    try {
      const html = await getReportHtml(report.id)
      const text = htmlToPlainText(html)
      setPreview({
        kind: "report",
        report,
        html,
        text,
        loading: false,
        error: null,
      })
    } catch (err: unknown) {
      setPreview({
        kind: "report",
        report,
        html: null,
        text: null,
        loading: false,
        error: err instanceof ApiError ? err.message : t("underlag.previewReportError"),
      })
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleUpload(file: File) {
    if (!browsingUnderlag) return
    setUploading(true)
    setError(null)
    try {
      const uploaded = await uploadUnderlag(file, module, folderId)
      setRows((current) => [uploaded, ...current.filter((row) => row.id !== uploaded.id)])
      setPreview({ kind: "underlag", file: uploaded })
      setPreviewTab(isPdf(uploaded) ? "pdf" : "text")
      setConfirmDelete(false)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("underlag.uploadError"))
    } finally {
      setUploading(false)
    }
  }

  async function handleCreateFolder() {
    const name = folderName.trim()
    if (!name || creatingFolder || !browsingUnderlag) return
    setCreatingFolder(true)
    setError(null)
    try {
      await createUnderlagFolder({
        module,
        name,
        parent_id: folderId,
      })
      await refreshFolders()
      setFolderName("")
      setNamingFolder(false)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("underlag.folderError"))
    } finally {
      setCreatingFolder(false)
    }
  }

  async function handleMove(fileId: string, targetFolderId: string | null) {
    if (moving) return
    if (!browsingUnderlag) return
    if (targetFolderId === folderId) return
    setMoving(true)
    setError(null)
    setDropTargetId(null)
    try {
      await moveUnderlag(fileId, targetFolderId)
      setRows((current) => current.filter((row) => row.id !== fileId))
      if (preview?.kind === "underlag" && preview.file.id === fileId) clearPreview()
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("underlag.moveError"))
    } finally {
      setMoving(false)
    }
  }

  async function handleDelete() {
    if (preview?.kind !== "underlag" || deleting) return
    setDeleting(true)
    setError(null)
    const deletedId = preview.file.id
    try {
      await deleteUnderlag(deletedId)
      setRows((current) => current.filter((row) => row.id !== deletedId))
      clearPreview()
      onDeleted?.(deletedId)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("underlag.deleteError"))
    } finally {
      setDeleting(false)
    }
  }

  async function handleUse() {
    if (!preview) return
    if (preview.kind === "underlag") {
      onSelect(preview.file)
      onOpenChange(false)
      return
    }
    const text = preview.text?.trim()
    if (!text) {
      setError(t("underlag.previewUnavailable"))
      return
    }
    setUsingReport(true)
    setError(null)
    try {
      const file = new File([text], safeUploadName(preview.report.title), {
        type: "text/plain",
      })
      const uploaded = await uploadUnderlag(file, module, null)
      onSelect(uploaded)
      onOpenChange(false)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("underlag.uploadError"))
    } finally {
      setUsingReport(false)
    }
  }

  function dropTargetKey(id: string | null): string {
    return id ?? "__root__"
  }

  function onDragOverTarget(event: DragEvent, targetId: string | null) {
    if (!draggingFileIdRef.current) return
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    setDropTargetId(dropTargetKey(targetId))
  }

  function onDropTarget(event: DragEvent, targetId: string | null) {
    if (!draggingFileIdRef.current) return
    event.preventDefault()
    const fileId = event.dataTransfer.getData("text/plain") || draggingFileIdRef.current
    draggingFileIdRef.current = null
    setDropTargetId(null)
    if (!fileId) return
    void handleMove(fileId, targetId)
  }

  function openUnderlagRoot() {
    setBrowse({ kind: "underlag", folderId: null })
    setNamingFolder(false)
  }

  function navigateToFolder(id: string | null) {
    if (id == null) {
      openUnderlagRoot()
      return
    }
    setBrowse({ kind: "underlag", folderId: id })
    setNamingFolder(false)
  }

  function openReports(moduleId: string) {
    setBrowse({ kind: "reports", moduleId })
    setNamingFolder(false)
  }

  function renderFolderNodes(parentId: string | null, depth: number): ReactNode {
    return childrenOf(allFolders, parentId, intl).map((folder) => {
      const selected = browsingUnderlag && folderId === folder.id
      const childNodes = renderFolderNodes(folder.id, depth + 1)
      return (
        <li key={folder.id}>
          <button
            type="button"
            className={cn(
              "flex w-full items-center gap-2 py-1.5 pr-3 text-left hover:bg-muted/60",
              selected && "bg-muted font-medium",
              dropTargetId === dropTargetKey(folder.id) &&
                "bg-db-gold-500/20 ring-1 ring-inset ring-db-gold-500",
            )}
            style={{ paddingLeft: `${0.75 + depth * 0.85}rem` }}
            onClick={() => navigateToFolder(folder.id)}
            onDragOver={(event) => onDragOverTarget(event, folder.id)}
            onDragLeave={() =>
              setDropTargetId((current) => (current === dropTargetKey(folder.id) ? null : current))
            }
            onDrop={(event) => onDropTarget(event, folder.id)}
          >
            <Folder className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="truncate text-sm">{folder.name}</span>
          </button>
          {childNodes ? <ul>{childNodes}</ul> : null}
        </li>
      )
    })
  }

  const visibleReports =
    browsingReports ? (reportsByModule.get(browse.moduleId) ?? []) : []
  const emptyFiles = browsingUnderlag && rows.length === 0 && !namingFolder
  const emptyReports = browsingReports && visibleReports.length === 0
  const underlagPreview = preview?.kind === "underlag" ? preview.file : null
  const reportPreview = preview?.kind === "report" ? preview : null
  const showPdfTabs = underlagPreview != null && isPdf(underlagPreview)
  const showReportTabs = reportPreview != null
  const canUse =
    underlagPreview != null ||
    (reportPreview != null && !reportPreview.loading && Boolean(reportPreview.text?.trim()))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="theme-admin flex h-[min(880px,92vh)] w-full max-w-6xl flex-col overflow-hidden bg-db-ink-0 p-0 sm:max-w-6xl"
        showCloseButton={false}
      >
        <div className="flex min-h-0 flex-1 flex-col">
          <DialogHeader className="shrink-0 border-b border-[color:var(--border-hairline)] px-5 py-4">
            <DialogTitle>{t("underlag.modalTitle")}</DialogTitle>
            <DialogDescription>{t("underlag.modalIntro")}</DialogDescription>
          </DialogHeader>

          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[color:var(--border-hairline)] px-5 py-3">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              disabled={uploading || !browsingUnderlag}
              onChange={(event) => {
                const file = event.target.files?.[0]
                event.target.value = ""
                if (file) void handleUpload(file)
              }}
            />
            <AdminButton
              variant="accent"
              size="sm"
              disabled={uploading || !browsingUnderlag}
              onClick={() => fileInputRef.current?.click()}
            >
              {uploading ? t("underlag.uploading") : t("underlag.upload")}
            </AdminButton>
            <AdminButton
              variant="secondary"
              size="sm"
              disabled={creatingFolder || !browsingUnderlag}
              onClick={() => {
                setNamingFolder(true)
                setFolderName("")
              }}
            >
              {t("underlag.createFolder")}
            </AdminButton>
            <p className="text-xs text-muted-foreground">{t("underlag.acceptHint")}</p>
            <p className="w-full text-xs text-muted-foreground sm:ml-auto sm:w-auto">
              {t("underlag.dropHint")}
            </p>
          </div>

          {error ? (
            <div className="shrink-0 px-5 pt-3">
              <div className="no-match text-left" role="alert">
                {error}
              </div>
            </div>
          ) : null}

          <div className="flex min-h-0 flex-1 flex-col overflow-hidden md:grid md:grid-cols-[minmax(260px,36%)_minmax(0,1fr)]">
            <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 border-b border-[color:var(--border-hairline)] px-5 py-4 md:flex-none md:border-r md:border-b-0">
              <div className="min-h-0 flex-[0.9] overflow-y-auto rounded-md border border-[color:var(--border-hairline)]">
                <ul className="text-sm">
                  <li>
                    <div className="flex items-center gap-2 px-3 py-1.5 text-muted-foreground">
                      <Folder className="size-4 shrink-0" aria-hidden />
                      <span className="truncate font-medium">/{kundSlug}</span>
                    </div>
                    <ul>
                      {moduleIds.map((moduleId) => {
                        const manifest = MODULE_REGISTRY[moduleId]
                        const label = manifest ? t(manifest.nameKey) : moduleId
                        const moduleReports = reportsByModule.get(moduleId) ?? []
                        const showUnderlag = moduleId === module
                        return (
                          <li key={moduleId}>
                            <div
                              className="flex items-center gap-2 py-1.5 pr-3 text-muted-foreground"
                              style={{ paddingLeft: "1.5rem" }}
                            >
                              <Folder className="size-4 shrink-0" aria-hidden />
                              <span className="truncate">{label}</span>
                            </div>
                            <ul>
                              {showUnderlag ? (
                                <li>
                                  <button
                                    type="button"
                                    className={cn(
                                      "flex w-full items-center gap-2 py-1.5 pr-3 text-left hover:bg-muted/60",
                                      browsingUnderlag &&
                                        folderId == null &&
                                        "bg-muted font-medium",
                                      dropTargetId === dropTargetKey(null) &&
                                        "bg-db-gold-500/20 ring-1 ring-inset ring-db-gold-500",
                                    )}
                                    style={{ paddingLeft: "2.25rem" }}
                                    onClick={openUnderlagRoot}
                                    onDragOver={(event) => onDragOverTarget(event, null)}
                                    onDragLeave={() =>
                                      setDropTargetId((current) =>
                                        current === dropTargetKey(null) ? null : current,
                                      )
                                    }
                                    onDrop={(event) => onDropTarget(event, null)}
                                  >
                                    <Folder className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                                    <span className="truncate">{t("underlag.treeUnderlagSegment")}</span>
                                  </button>
                                  <ul>{renderFolderNodes(null, 3)}</ul>
                                </li>
                              ) : null}
                              <li>
                                <button
                                  type="button"
                                  className={cn(
                                    "flex w-full items-center gap-2 py-1.5 pr-3 text-left hover:bg-muted/60",
                                    browsingReports &&
                                      browse.moduleId === moduleId &&
                                      "bg-muted font-medium",
                                  )}
                                  style={{ paddingLeft: "2.25rem" }}
                                  onClick={() => openReports(moduleId)}
                                >
                                  <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                                  <span className="truncate">
                                    {t("underlag.treeReportsSegment")}
                                    {moduleReports.length > 0 ? ` (${moduleReports.length})` : ""}
                                  </span>
                                </button>
                              </li>
                            </ul>
                          </li>
                        )
                      })}
                    </ul>
                  </li>
                </ul>
              </div>

              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {browsingReports ? t("underlag.reportsInModule") : t("underlag.filesInFolder")}
              </p>

              <div className="min-h-0 flex-1 overflow-y-auto rounded-md border border-[color:var(--border-hairline)]">
                {loading && browsingUnderlag ? (
                  <p className="px-3 py-4 text-sm text-muted-foreground">{t("underlag.loading")}</p>
                ) : (
                  <ul className="divide-y divide-[color:var(--border-hairline)]">
                    {browsingUnderlag && namingFolder ? (
                      <li className="flex flex-col gap-2 px-3 py-2 sm:flex-row sm:items-center">
                        <div className="flex min-w-0 flex-1 items-center gap-2">
                          <Folder className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                          <input
                            ref={folderNameRef}
                            value={folderName}
                            maxLength={80}
                            disabled={creatingFolder}
                            placeholder={t("underlag.folderNamePlaceholder")}
                            className="min-w-0 flex-1 rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1 text-sm"
                            onChange={(event) => setFolderName(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault()
                                void handleCreateFolder()
                              }
                              if (event.key === "Escape") {
                                setNamingFolder(false)
                                setFolderName("")
                              }
                            }}
                          />
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <AdminButton
                            variant="primary"
                            size="sm"
                            disabled={creatingFolder || folderName.trim().length === 0}
                            onClick={() => void handleCreateFolder()}
                          >
                            {creatingFolder ? t("underlag.creatingFolder") : t("underlag.folderCreate")}
                          </AdminButton>
                          <AdminButton
                            variant="secondary"
                            size="sm"
                            disabled={creatingFolder}
                            onClick={() => {
                              setNamingFolder(false)
                              setFolderName("")
                            }}
                          >
                            {t("common.cancel")}
                          </AdminButton>
                        </div>
                      </li>
                    ) : null}
                    {emptyFiles ? (
                      <li className="px-3 py-4 text-sm text-muted-foreground">
                        {folderId == null ? t("underlag.emptyFiles") : t("underlag.folderEmptyFiles")}
                      </li>
                    ) : null}
                    {emptyReports ? (
                      <li className="px-3 py-4 text-sm text-muted-foreground">
                        {t("underlag.emptyReports")}
                      </li>
                    ) : null}
                    {browsingUnderlag
                      ? rows.map((row) => {
                          const selected =
                            preview?.kind === "underlag" && preview.file.id === row.id
                          return (
                            <li key={row.id}>
                              <button
                                type="button"
                                draggable
                                className={cn(
                                  "flex w-full cursor-grab flex-col items-start gap-1 px-3 py-2.5 text-left hover:bg-muted/60 active:cursor-grabbing",
                                  selected && "bg-muted",
                                )}
                                onClick={() => void loadPreview(row.id)}
                                onDragStart={(event) => {
                                  draggingFileIdRef.current = row.id
                                  event.dataTransfer.setData("text/plain", row.id)
                                  event.dataTransfer.effectAllowed = "move"
                                }}
                                onDragEnd={() => {
                                  draggingFileIdRef.current = null
                                  setDropTargetId(null)
                                }}
                              >
                                <span className="line-clamp-2 text-sm font-medium break-all">
                                  {row.filename}
                                </span>
                                <span className="flex flex-wrap items-center gap-2">
                                  <Badge variant={statusVariant(row.extraction_status)}>
                                    {t(statusKey(row.extraction_status))}
                                  </Badge>
                                  {row.created_at ? (
                                    <span className="text-xs text-muted-foreground">
                                      {dateFmt.format(new Date(row.created_at))}
                                    </span>
                                  ) : null}
                                </span>
                              </button>
                            </li>
                          )
                        })
                      : null}
                    {browsingReports
                      ? visibleReports.map((report) => {
                          const selected =
                            preview?.kind === "report" && preview.report.id === report.id
                          return (
                            <li key={report.id}>
                              <button
                                type="button"
                                className={cn(
                                  "flex w-full flex-col items-start gap-1 px-3 py-2.5 text-left hover:bg-muted/60",
                                  selected && "bg-muted",
                                )}
                                onClick={() => void loadReportPreview(report)}
                              >
                                <span className="line-clamp-2 text-sm font-medium">
                                  {report.title || report.id}
                                </span>
                                <span className="text-xs text-muted-foreground">
                                  {dateFmt.format(new Date(report.created_at))}
                                </span>
                              </button>
                            </li>
                          )
                        })
                      : null}
                  </ul>
                )}
              </div>
            </div>

            <div className="flex min-h-0 min-w-0 flex-[1.35] flex-col gap-2 px-5 py-4 md:flex-none">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  {t("underlag.preview")}
                </p>
                {underlagPreview ? (
                  confirmDelete ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-muted-foreground">{t("underlag.confirmDelete")}</span>
                      <AdminButton
                        variant="secondary"
                        size="sm"
                        disabled={deleting}
                        onClick={() => setConfirmDelete(false)}
                      >
                        {t("common.cancel")}
                      </AdminButton>
                      <AdminButton
                        variant="primary"
                        size="sm"
                        disabled={deleting}
                        onClick={() => void handleDelete()}
                      >
                        {deleting ? t("underlag.deleting") : t("underlag.confirmDeleteButton")}
                      </AdminButton>
                    </div>
                  ) : (
                    <AdminButton
                      variant="secondary"
                      size="sm"
                      disabled={deleting}
                      onClick={() => setConfirmDelete(true)}
                    >
                      {t("underlag.delete")}
                    </AdminButton>
                  )
                ) : null}
              </div>
              {showPdfTabs ? (
                <div className="flex gap-1 border-b border-[color:var(--border-hairline)]" role="tablist">
                  {(
                    [
                      { id: "pdf" as const, label: t("underlag.previewTabPdf") },
                      { id: "text" as const, label: t("underlag.previewTabText") },
                    ] as const
                  ).map((item) => {
                    const selected = item.id === previewTab
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="tab"
                        aria-selected={selected}
                        className={cn(
                          "-mb-px border-b-2 px-3 py-1.5 text-sm",
                          selected
                            ? "border-db-ink-950 font-medium text-[color:var(--text-body)]"
                            : "border-transparent text-muted-foreground hover:text-[color:var(--text-body)]",
                        )}
                        onClick={() => setPreviewTab(item.id)}
                      >
                        {item.label}
                      </button>
                    )
                  })}
                </div>
              ) : null}
              {showReportTabs ? (
                <div className="flex gap-1 border-b border-[color:var(--border-hairline)]" role="tablist">
                  {(
                    [
                      { id: "html" as const, label: t("underlag.previewTabReport") },
                      { id: "text" as const, label: t("underlag.previewTabText") },
                    ] as const
                  ).map((item) => {
                    const selected = item.id === previewTab
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="tab"
                        aria-selected={selected}
                        className={cn(
                          "-mb-px border-b-2 px-3 py-1.5 text-sm",
                          selected
                            ? "border-db-ink-950 font-medium text-[color:var(--text-body)]"
                            : "border-transparent text-muted-foreground hover:text-[color:var(--text-body)]",
                        )}
                        onClick={() => setPreviewTab(item.id)}
                      >
                        {item.label}
                      </button>
                    )
                  })}
                </div>
              ) : null}
              <div className="min-h-0 w-full flex-1 overflow-hidden rounded-md border border-[color:var(--border-hairline)] bg-muted/20">
                {previewLoading || reportPreview?.loading ? (
                  <p className="px-3 py-3 text-sm text-muted-foreground">{t("underlag.loading")}</p>
                ) : preview == null ? (
                  <p className="px-3 py-3 text-sm text-muted-foreground">{t("underlag.previewEmpty")}</p>
                ) : reportPreview ? (
                  reportPreview.error ? (
                    <p className="px-3 py-3 text-sm text-muted-foreground" role="alert">
                      {reportPreview.error}
                    </p>
                  ) : previewTab === "text" ? (
                    reportPreview.text ? (
                      <div className="h-full overflow-y-auto px-3 py-3 whitespace-pre-wrap text-sm">
                        {reportPreview.text}
                      </div>
                    ) : (
                      <p className="px-3 py-3 text-sm text-muted-foreground">
                        {t("underlag.previewUnavailable")}
                      </p>
                    )
                  ) : reportPreview.html ? (
                    <iframe
                      title={reportPreview.report.title || reportPreview.report.id}
                      srcDoc={reportPreview.html}
                      sandbox=""
                      className="h-full w-full border-0 bg-white"
                    />
                  ) : (
                    <p className="px-3 py-3 text-sm text-muted-foreground">
                      {t("underlag.previewReportError")}
                    </p>
                  )
                ) : showPdfTabs && previewTab === "pdf" ? (
                  pdfLoading ? (
                    <p className="px-3 py-3 text-sm text-muted-foreground">{t("underlag.previewPdfLoading")}</p>
                  ) : pdfError ? (
                    <p className="px-3 py-3 text-sm text-muted-foreground" role="alert">
                      {pdfError}
                    </p>
                  ) : pdfUrl && underlagPreview ? (
                    <iframe
                      title={underlagPreview.filename}
                      src={pdfUrl}
                      className="h-full w-full border-0 bg-white"
                    />
                  ) : (
                    <p className="px-3 py-3 text-sm text-muted-foreground">{t("underlag.previewPdfError")}</p>
                  )
                ) : underlagPreview?.extracted_text ? (
                  <div className="h-full overflow-y-auto px-3 py-3">
                    <Markdown content={underlagPreview.extracted_text} />
                  </div>
                ) : (
                  <p className="px-3 py-3 text-sm text-muted-foreground">{t("underlag.previewUnavailable")}</p>
                )}
              </div>
            </div>
          </div>

          <DialogFooter className="mx-0 mb-0 shrink-0 border-[color:var(--border-hairline)] bg-db-ink-0">
            <AdminButton variant="secondary" size="sm" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </AdminButton>
            <AdminButton
              variant="primary"
              size="sm"
              disabled={!canUse || usingReport}
              onClick={() => void handleUse()}
            >
              {usingReport ? t("underlag.usingReport") : t("underlag.useFile")}
            </AdminButton>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  )
}
