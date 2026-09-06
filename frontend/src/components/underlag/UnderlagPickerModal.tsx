import { useEffect, useRef, useState } from "react"
import { ChevronRight, Folder } from "lucide-react"
import {
  createUnderlagFolder,
  getUnderlag,
  listUnderlag,
  uploadUnderlag,
  type UnderlagExtractionStatus,
  type UnderlagFile,
  type UnderlagFolder,
} from "@/api/underlag"
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
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

const ACCEPT = ".txt,.md,.markdown,.pdf,.docx"

type Crumb = { id: string | null; name: string }

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

export function UnderlagPickerModal({
  open,
  module,
  listAllModules = false,
  onOpenChange,
  onSelect,
}: {
  open: boolean
  module: string
  listAllModules?: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (file: UnderlagFile) => void
}) {
  const { t, intl } = useLocale()
  const dateFmt = new Intl.DateTimeFormat(intl, { dateStyle: "medium" })
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderNameRef = useRef<HTMLInputElement>(null)
  const [path, setPath] = useState<Crumb[]>([])
  const [folders, setFolders] = useState<UnderlagFolder[]>([])
  const [rows, setRows] = useState<UnderlagFile[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [creatingFolder, setCreatingFolder] = useState(false)
  const [namingFolder, setNamingFolder] = useState(false)
  const [folderName, setFolderName] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<UnderlagFile | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const folderId = path.length === 0 ? null : path[path.length - 1].id

  useEffect(() => {
    setPath([])
    setFolders([])
    setRows([])
    setPreview(null)
    setNamingFolder(false)
    setFolderName("")
    setError(null)
  }, [module])

  useEffect(() => {
    if (open) return
    setPath([])
    setPreview(null)
    setNamingFolder(false)
    setFolderName("")
    setError(null)
  }, [open])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setPreview(null)
    listUnderlag(listAllModules ? null : module, listAllModules ? null : folderId)
      .then((listed) => {
        if (!cancelled) {
          setFolders(listed.folders)
          setRows(listed.files)
        }
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
  }, [folderId, listAllModules, module, open, t])

  useEffect(() => {
    if (namingFolder) folderNameRef.current?.focus()
  }, [namingFolder])

  async function loadPreview(id: string) {
    setPreviewLoading(true)
    setError(null)
    try {
      const row = await getUnderlag(id)
      setPreview(row)
      setRows((current) => current.map((item) => (item.id === row.id ? { ...item, ...row } : item)))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("underlag.loadError"))
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleUpload(file: File) {
    setUploading(true)
    setError(null)
    try {
      const uploaded = await uploadUnderlag(file, module, folderId)
      setRows((current) => [uploaded, ...current.filter((row) => row.id !== uploaded.id)])
      setPreview(uploaded)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("underlag.uploadError"))
    } finally {
      setUploading(false)
    }
  }

  async function handleCreateFolder() {
    const name = folderName.trim()
    if (!name || creatingFolder) return
    setCreatingFolder(true)
    setError(null)
    try {
      const created = await createUnderlagFolder({
        module,
        name,
        parent_id: folderId,
      })
      setFolders((current) =>
        [...current.filter((folder) => folder.id !== created.id), created].sort((a, b) =>
          a.name.localeCompare(b.name, intl),
        ),
      )
      setFolderName("")
      setNamingFolder(false)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("underlag.folderError"))
    } finally {
      setCreatingFolder(false)
    }
  }

  const empty = folders.length === 0 && rows.length === 0 && !namingFolder

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="theme-admin flex h-[min(880px,92vh)] w-full max-w-4xl flex-col overflow-hidden bg-db-ink-0 p-0 sm:max-w-4xl"
        showCloseButton={false}
      >
        <div className="flex min-h-0 flex-1 flex-col">
          <DialogHeader className="shrink-0 border-b border-[color:var(--border-hairline)] px-5 py-4">
            <DialogTitle>{t("underlag.modalTitle")}</DialogTitle>
            <DialogDescription>{t("underlag.modalIntro")}</DialogDescription>
          </DialogHeader>

          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden px-5 py-4">
            <div className="flex min-h-0 w-full flex-1 flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={ACCEPT}
                  className="sr-only"
                  disabled={uploading}
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    event.target.value = ""
                    if (file) void handleUpload(file)
                  }}
                />
                <AdminButton
                  variant="accent"
                  size="sm"
                  disabled={uploading}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {uploading ? t("underlag.uploading") : t("underlag.upload")}
                </AdminButton>
                <AdminButton
                  variant="secondary"
                  size="sm"
                  disabled={creatingFolder}
                  onClick={() => {
                    setNamingFolder(true)
                    setFolderName("")
                  }}
                >
                  {t("underlag.createFolder")}
                </AdminButton>
                <p className="text-xs text-muted-foreground">{t("underlag.acceptHint")}</p>
              </div>

              <nav aria-label={t("underlag.rootBreadcrumb")} className="flex flex-wrap items-center gap-1 text-xs">
                <button
                  type="button"
                  className={cn(
                    "rounded px-1 py-0.5 hover:bg-muted/60",
                    folderId == null ? "font-medium text-foreground" : "text-muted-foreground",
                  )}
                  onClick={() => setPath([])}
                >
                  {t("underlag.rootBreadcrumb")}
                </button>
                {path.map((crumb, index) => (
                  <span key={crumb.id ?? "root"} className="inline-flex items-center gap-1">
                    <ChevronRight className="size-3 text-muted-foreground" aria-hidden />
                    <button
                      type="button"
                      className={cn(
                        "rounded px-1 py-0.5 hover:bg-muted/60",
                        index === path.length - 1
                          ? "font-medium text-foreground"
                          : "text-muted-foreground",
                      )}
                      onClick={() => setPath(path.slice(0, index + 1))}
                    >
                      {crumb.name}
                    </button>
                  </span>
                ))}
              </nav>

              {error ? (
                <div className="no-match text-left" role="alert">
                  {error}
                </div>
              ) : null}

              <div className="min-h-0 flex-1 overflow-y-auto rounded-md border border-[color:var(--border-hairline)]">
                {loading ? (
                  <p className="px-3 py-4 text-sm text-muted-foreground">{t("underlag.loading")}</p>
                ) : (
                  <ul className="divide-y divide-[color:var(--border-hairline)]">
                    {namingFolder ? (
                      <li className="flex items-center gap-2 px-3 py-2">
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
                      </li>
                    ) : null}
                    {empty ? (
                      <li className="px-3 py-4 text-sm text-muted-foreground">
                        {folderId == null ? t("underlag.empty") : t("underlag.folderEmpty")}
                      </li>
                    ) : null}
                    {folders.map((folder) => (
                      <li key={folder.id}>
                        <button
                          type="button"
                          className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-muted/60"
                          onClick={() => setPath((current) => [...current, { id: folder.id, name: folder.name }])}
                        >
                          <Folder className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                          <span className="text-sm font-medium">{folder.name}</span>
                        </button>
                      </li>
                    ))}
                    {rows.map((row) => {
                      const selected = preview?.id === row.id
                      return (
                        <li key={row.id}>
                          <button
                            type="button"
                            className={cn(
                              "flex w-full flex-col items-start gap-1 px-3 py-2.5 text-left hover:bg-muted/60",
                              selected && "bg-muted",
                            )}
                            onClick={() => void loadPreview(row.id)}
                          >
                            <span className="text-sm font-medium">{row.filename}</span>
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
                    })}
                  </ul>
                )}
              </div>
            </div>

            <div className="flex min-h-0 min-w-0 w-full flex-1 flex-col gap-2">
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {t("underlag.preview")}
              </p>
              <div className="min-h-0 w-full flex-1 overflow-y-auto rounded-md border border-[color:var(--border-hairline)] bg-muted/20 px-3 py-3">
                {previewLoading ? (
                  <p className="text-sm text-muted-foreground">{t("underlag.loading")}</p>
                ) : preview == null ? (
                  <p className="text-sm text-muted-foreground">{t("underlag.previewEmpty")}</p>
                ) : preview.extracted_text ? (
                  <Markdown content={preview.extracted_text} />
                ) : (
                  <p className="text-sm text-muted-foreground">{t("underlag.previewUnavailable")}</p>
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
              disabled={preview == null}
              onClick={() => {
                if (!preview) return
                onSelect(preview)
                onOpenChange(false)
              }}
            >
              {t("underlag.useFile")}
            </AdminButton>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  )
}
