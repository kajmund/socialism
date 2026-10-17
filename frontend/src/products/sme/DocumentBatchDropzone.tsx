import { useRef, useState } from "react"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { BATCH_ACCEPT, acceptedBatchFile } from "./documentBatch"

export function DocumentBatchDropzone({
  disabled,
  onFiles,
}: {
  disabled: boolean
  onFiles: (files: File[]) => void
}) {
  const { t } = useLocale()
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  function take(list: FileList | File[]) {
    onFiles(Array.from(list).filter(acceptedBatchFile))
  }

  return (
    <div
      className={`grid gap-3 rounded-xl border border-dashed p-6 ${over ? "border-db-gold-500 bg-db-gold-500/5" : "border-db-ink-200"}`}
      onDragOver={(event) => { event.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault()
        setOver(false)
        if (!disabled) take(event.dataTransfer.files)
      }}
    >
      <p className="text-sm">{t("documentBatch.drop")}</p>
      <div>
        <AdminButton type="button" variant="secondary" disabled={disabled} onClick={() => input.current?.click()}>
          {t("documentBatch.choose")}
        </AdminButton>
        <input
          ref={input}
          type="file"
          multiple
          accept={BATCH_ACCEPT}
          className="sr-only"
          disabled={disabled}
          onChange={(event) => {
            if (event.target.files) take(event.target.files)
            event.target.value = ""
          }}
        />
      </div>
    </div>
  )
}
