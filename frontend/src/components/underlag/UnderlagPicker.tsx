import { useState } from "react"
import type { UnderlagExtractionStatus, UnderlagFile } from "@/api/underlag"
import { UnderlagPickerModal } from "@/components/underlag/UnderlagPickerModal"
import { AdminButton } from "@/components/ui/admin-button"
import { Badge } from "@/components/ui/badge"
import { useLocale, type MessageKey } from "@/i18n"

export type UnderlagSelection = {
  objectId: string
  filename: string
  extractedText: string
  status: UnderlagExtractionStatus
}

function statusKey(status: UnderlagExtractionStatus): MessageKey {
  switch (status) {
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

function toSelection(file: UnderlagFile): UnderlagSelection {
  return {
    objectId: file.id,
    filename: file.filename,
    extractedText: file.extracted_text ?? "",
    status: file.extraction_status ?? "failed",
  }
}

export function UnderlagPicker({
  value,
  onChange,
  module,
  disabled = false,
}: {
  value: UnderlagSelection | null
  onChange: (value: UnderlagSelection | null) => void
  module: string
  disabled?: boolean
}) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)

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
        <span className="inline-flex max-w-full items-center gap-2 rounded-md border border-[color:var(--border-hairline)] bg-muted/40 px-2 py-1">
          <span className="truncate text-sm">{value.filename}</span>
          <Badge variant={value.status === "ok" ? "default" : "destructive"}>
            {t(statusKey(value.status))}
          </Badge>
          <button
            type="button"
            className="text-xs text-muted-foreground underline-offset-2 hover:underline disabled:opacity-40"
            disabled={disabled}
            onClick={() => onChange(null)}
          >
            {t("underlag.clear")}
          </button>
        </span>
      ) : null}
      <UnderlagPickerModal
        open={open}
        module={module}
        onOpenChange={setOpen}
        onSelect={(file) => onChange(toSelection(file))}
      />
    </div>
  )
}
