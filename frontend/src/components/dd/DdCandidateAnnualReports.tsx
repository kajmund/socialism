import { useEffect, useRef, useState } from "react"
import {
  deleteCandidateFile,
  downloadCandidateFile,
  listCandidateFiles,
  uploadCandidateFile,
  type StoredObject,
} from "@/api/dd"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

function formatBytes(value: number, intl: string): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) {
    return `${new Intl.NumberFormat(intl, { maximumFractionDigits: 1 }).format(value / 1024)} KB`
  }
  return `${new Intl.NumberFormat(intl, { maximumFractionDigits: 1 }).format(value / (1024 * 1024))} MB`
}

export function DdCandidateAnnualReports({
  campaignId,
  candidateId,
}: {
  campaignId: number
  candidateId: string
}) {
  const { t, intl } = useLocale()
  const inputRef = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<StoredObject[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listCandidateFiles(campaignId, candidateId)
      .then((rows) => {
        if (!cancelled) setFiles(rows)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("dd.sourcing.annualReports.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [campaignId, candidateId, t])

  async function onPick(file: File | undefined) {
    if (!file) return
    setError(null)
    setUploading(true)
    try {
      const row = await uploadCandidateFile(campaignId, candidateId, file)
      setFiles((prev) => [row, ...prev])
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("dd.sourcing.annualReports.uploadError"))
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ""
    }
  }

  async function onDownload(row: StoredObject) {
    setError(null)
    try {
      const blob = await downloadCandidateFile(campaignId, candidateId, row.id)
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = row.filename
      link.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("dd.sourcing.annualReports.downloadError"))
    }
  }

  async function onDelete(row: StoredObject) {
    setError(null)
    try {
      await deleteCandidateFile(campaignId, candidateId, row.id)
      setFiles((prev) => prev.filter((item) => item.id !== row.id))
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : t("dd.sourcing.annualReports.deleteError"))
    }
  }

  return (
    <div className="mb-6 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("dd.sourcing.annualReports.title")}
          </h4>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            {t("dd.sourcing.annualReports.intro")}
          </p>
        </div>
        <>
          <input
            ref={inputRef}
            type="file"
            className="sr-only"
            accept=".pdf,application/pdf,.png,.jpg,.jpeg,.webp"
            disabled={uploading}
            onChange={(event) => void onPick(event.target.files?.[0])}
          />
          <button
            type="button"
            className="primary"
            disabled={uploading}
            onClick={() => inputRef.current?.click()}
          >
            {uploading
              ? t("dd.sourcing.annualReports.uploading")
              : t("dd.sourcing.annualReports.upload")}
          </button>
        </>
      </div>

      {error ? (
        <p className="text-sm text-[var(--text-body)]" role="alert">
          {error}
        </p>
      ) : null}

      {loading ? (
        <p className="text-sm text-[var(--text-muted)]">{t("dd.sourcing.annualReports.loading")}</p>
      ) : files.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">{t("dd.sourcing.annualReports.empty")}</p>
      ) : (
        <ul className="space-y-2">
          {files.map((row) => (
            <li
              key={row.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[color:var(--border-hairline)] px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-[var(--text-body)]">{row.filename}</p>
                <p className="text-xs text-[var(--text-muted)]">
                  {formatBytes(row.size_bytes, intl)}
                  {row.created_at ? ` · ${row.created_at}` : ""}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="text-sm underline"
                  onClick={() => void onDownload(row)}
                >
                  {t("dd.sourcing.annualReports.download")}
                </button>
                <button
                  type="button"
                  className="text-sm underline"
                  onClick={() => void onDelete(row)}
                >
                  {t("dd.sourcing.annualReports.delete")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
