import { useEffect, useState } from "react"
import { FileText, X } from "lucide-react"
import { getUnderlag, type UnderlagExtractionStatus, type UnderlagFile } from "@/api/underlag"
import { UnderlagPickerModal } from "@/components/underlag/UnderlagPickerModal"
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
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

export type UnderlagSelection = {
  objectId: string
  filename: string
  extractedText: string
  status: UnderlagExtractionStatus
  contentType: string
}

function statusKey(status: UnderlagExtractionStatus): MessageKey {
  switch (status) {
    case "pending":
      return "underlag.status.pending"
    case "ok":
      return "underlag.status.ok"
    case "failed":
      return "underlag.status.failed"
    case "empty":
      return "underlag.status.empty"
    case "unsupported":
      return "underlag.status.unsupported"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function badgeVariant(
  status: UnderlagExtractionStatus,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "pending":
      return "secondary"
    case "ok":
      return "default"
    case "failed":
    case "unsupported":
      return "destructive"
    case "empty":
      return "outline"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function toSelection(file: UnderlagFile): UnderlagSelection {
  return {
    objectId: file.id,
    filename: file.filename,
    extractedText: file.extracted_text ?? "",
    status: file.extraction_status ?? "pending",
    contentType: file.content_type,
  }
}

export function UnderlagPicker({
  value,
  onChange,
  module,
  listAllModules = false,
  disabled = false,
}: {
  value: UnderlagSelection | null
  onChange: (value: UnderlagSelection | null) => void
  module: string
  listAllModules?: boolean
  disabled?: boolean
}) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const [textOpen, setTextOpen] = useState(false)
  const [textLoading, setTextLoading] = useState(false)
  const [textError, setTextError] = useState<string | null>(null)
  const [textBody, setTextBody] = useState("")
  const [textStatus, setTextStatus] = useState<UnderlagExtractionStatus | null>(null)

  useEffect(() => {
    if (!textOpen || value == null) {
      setTextLoading(false)
      setTextError(null)
      setTextBody("")
      setTextStatus(null)
      return
    }
    const objectId = value.objectId
    let cancelled = false
    setTextLoading(true)
    setTextError(null)
    setTextBody(value.extractedText)
    setTextStatus(value.status)
    void getUnderlag(objectId)
      .then((file) => {
        if (cancelled) return
        setTextBody(file.extracted_text ?? "")
        setTextStatus(file.extraction_status ?? "pending")
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setTextError(err instanceof ApiError ? err.message : t("underlag.loadError"))
      })
      .finally(() => {
        if (!cancelled) setTextLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t, textOpen, value?.extractedText, value?.objectId, value?.status])

  return (
    <div className="flex flex-wrap items-center gap-2">
      <AdminButton
        variant="secondary"
        size="sm"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        {value ? t("underlag.change") : t("underlag.pick")}
      </AdminButton>
      {value ? (
        <span className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-[color:var(--border-hairline)] bg-muted/40 px-2 py-1">
          <span className="truncate text-sm">{value.filename}</span>
          <Badge variant={badgeVariant(value.status)}>{t(statusKey(value.status))}</Badge>
          <button
            type="button"
            className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-[color:var(--text-body)] disabled:opacity-40"
            disabled={disabled}
            aria-label={t("underlag.viewExtracted")}
            title={t("underlag.viewExtracted")}
            onClick={() => setTextOpen(true)}
          >
            <FileText className="size-3.5" aria-hidden />
          </button>
          <button
            type="button"
            className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-[color:var(--text-body)] disabled:opacity-40"
            disabled={disabled}
            aria-label={t("underlag.clear")}
            title={t("underlag.clear")}
            onClick={() => onChange(null)}
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </span>
      ) : null}
      <UnderlagPickerModal
        open={open}
        module={module}
        listAllModules={listAllModules}
        onOpenChange={setOpen}
        onSelect={(file) => onChange(toSelection(file))}
        onDeleted={(objectId) => {
          if (value?.objectId === objectId) onChange(null)
        }}
      />
      <Dialog open={textOpen} onOpenChange={setTextOpen}>
        <DialogContent
          className="theme-admin max-h-[min(720px,90vh)] w-full max-w-2xl overflow-hidden bg-db-ink-0 p-0 sm:max-w-2xl"
          showCloseButton={false}
        >
          <div className="flex max-h-[min(720px,90vh)] flex-col">
            <DialogHeader className="border-b border-[color:var(--border-hairline)] px-5 py-4">
              <DialogTitle>{t("underlag.extractedModalTitle")}</DialogTitle>
              <DialogDescription>
                {value?.filename ?? t("underlag.extractedModalFallback")}
              </DialogDescription>
            </DialogHeader>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              {textLoading ? (
                <p className="text-sm text-muted-foreground">{t("underlag.loading")}</p>
              ) : textError ? (
                <p className="text-sm text-destructive" role="alert">
                  {textError}
                </p>
              ) : textBody.trim() ? (
                <pre className="whitespace-pre-wrap font-sans text-sm text-[color:var(--text-body)]">
                  {textBody}
                </pre>
              ) : textStatus === "pending" ? (
                <p className="text-sm text-muted-foreground">{t("underlag.previewDeferred")}</p>
              ) : (
                <p className="text-sm text-muted-foreground">{t("underlag.previewUnavailable")}</p>
              )}
            </div>
            <DialogFooter className="mx-0 mb-0 shrink-0 border-[color:var(--border-hairline)] bg-db-ink-0">
              <AdminButton variant="secondary" size="sm" onClick={() => setTextOpen(false)}>
                {t("common.close")}
              </AdminButton>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
