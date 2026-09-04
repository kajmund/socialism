import { useEffect, useRef, useState } from "react"
import {
  getUnderlag,
  listUnderlag,
  uploadUnderlag,
  type UnderlagExtractionStatus,
  type UnderlagFile,
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

function canUseUnderlag(file: UnderlagFile): boolean {
  return file.extraction_status === "ok" && Boolean(file.extracted_text?.trim())
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
  onOpenChange,
  onSelect,
}: {
  open: boolean
  module: string
  onOpenChange: (open: boolean) => void
  onSelect: (file: UnderlagFile) => void
}) {
  const { t, intl } = useLocale()
  const dateFmt = new Intl.DateTimeFormat(intl, { dateStyle: "medium" })
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [rows, setRows] = useState<UnderlagFile[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<UnderlagFile | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setPreview(null)
    listUnderlag(module)
      .then((listed) => {
        if (!cancelled) setRows(listed)
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
  }, [module, open, t])

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
      const uploaded = await uploadUnderlag(file, module)
      setRows((current) => [uploaded, ...current.filter((row) => row.id !== uploaded.id)])
      setPreview(uploaded)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("underlag.uploadError"))
    } finally {
      setUploading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="theme-admin max-h-[min(880px,92vh)] w-full max-w-3xl overflow-hidden bg-db-ink-0 p-0 sm:max-w-3xl"
        showCloseButton={false}
      >
        <div className="flex max-h-[min(880px,92vh)] flex-col">
          <DialogHeader className="border-b border-[color:var(--border-hairline)] px-5 py-4">
            <DialogTitle>{t("underlag.modalTitle")}</DialogTitle>
            <DialogDescription>{t("underlag.modalIntro")}</DialogDescription>
          </DialogHeader>

          <div className="flex flex-1 flex-col gap-4 overflow-hidden px-5 py-4 md:flex-row">
            <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
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
                <p className="text-xs text-muted-foreground">{t("underlag.acceptHint")}</p>
              </div>

              {error ? (
                <div className="no-match text-left" role="alert">
                  {error}
                </div>
              ) : null}

              <div className="min-h-0 flex-1 overflow-y-auto rounded-md border border-[color:var(--border-hairline)]">
                {loading ? (
                  <p className="px-3 py-4 text-sm text-muted-foreground">{t("underlag.loading")}</p>
                ) : rows.length === 0 ? (
                  <p className="px-3 py-4 text-sm text-muted-foreground">{t("underlag.empty")}</p>
                ) : (
                  <ul className="divide-y divide-[color:var(--border-hairline)]">
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

            <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {t("underlag.preview")}
              </p>
              <div className="min-h-[12rem] flex-1 overflow-y-auto rounded-md border border-[color:var(--border-hairline)] bg-muted/20 px-3 py-3">
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

          <DialogFooter className="mx-0 mb-0 border-[color:var(--border-hairline)] bg-db-ink-0">
            <AdminButton variant="secondary" size="sm" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </AdminButton>
            <AdminButton
              variant="primary"
              size="sm"
              disabled={preview == null || !canUseUnderlag(preview)}
              onClick={() => {
                if (!preview || !canUseUnderlag(preview)) return
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
