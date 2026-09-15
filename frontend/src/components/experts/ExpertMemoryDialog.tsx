import { useEffect, useState } from "react"
import { ExpertMemoryLog } from "@/components/experts/ExpertMemoryLog"
import type { ExpertMemory } from "@/api/expertMemory"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"

export function ExpertMemoryDialog({
  open,
  name,
  memories,
  loading,
  error,
  formatWhen,
  onSave,
  onDelete,
  onClearAll,
  onClose,
}: {
  open: boolean
  name: string
  memories: ExpertMemory[]
  loading: boolean
  error: string | null
  formatWhen: (iso: string) => string
  onSave?: (row: ExpertMemory, text: string) => Promise<ExpertMemory>
  onDelete?: (row: ExpertMemory) => Promise<void>
  onClearAll?: () => Promise<void>
  onClose: () => void
}) {
  const { t } = useLocale()
  const [confirmClear, setConfirmClear] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [clearError, setClearError] = useState<string | null>(null)

  useEffect(() => {
    if (open) return
    setConfirmClear(false)
    setClearing(false)
    setClearError(null)
  }, [open])

  if (!open) return null

  async function clearAll() {
    if (!onClearAll) return
    setClearing(true)
    setClearError(null)
    try {
      await onClearAll()
      setConfirmClear(false)
    } catch (err) {
      setClearError(err instanceof ApiError ? err.message : t("experts.memory.clearError"))
    } finally {
      setClearing(false)
    }
  }

  return (
    <div
      className="theme-admin fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="expert-memory-log-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-[color:var(--border-hairline)] px-5 py-4">
          <h2 id="expert-memory-log-title" className="text-base font-medium text-foreground">
            {t("experts.memory.logTitle", { name })}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("experts.memory.logIntro")}</p>
        </div>
        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          {clearError ? (
            <p className="mb-3 text-sm text-destructive" role="alert">
              {clearError}
            </p>
          ) : null}
          {loading ? <p className="text-sm text-muted-foreground">{t("tools.memory.loading")}</p> : null}
          {!loading && !error ? (
            <ExpertMemoryLog
              memories={memories}
              empty={t("experts.memory.logEmpty")}
              formatWhen={formatWhen}
              onSave={onSave}
              onDelete={onDelete}
            />
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[color:var(--border-hairline)] px-5 py-3">
          {onClearAll && memories.length > 0 ? (
            confirmClear ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  {t("experts.memory.confirmClear", { name })}
                </span>
                <AdminButton
                  type="button"
                  variant="primary"
                  size="sm"
                  disabled={clearing}
                  onClick={() => void clearAll()}
                >
                  {clearing ? t("experts.memory.clearing") : t("experts.memory.clearConfirm")}
                </AdminButton>
                <AdminButton
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={clearing}
                  onClick={() => setConfirmClear(false)}
                >
                  {t("experts.memory.cancel")}
                </AdminButton>
              </div>
            ) : (
              <AdminButton
                type="button"
                variant="secondary"
                size="sm"
                disabled={loading || clearing}
                onClick={() => setConfirmClear(true)}
              >
                {t("experts.memory.clear")}
              </AdminButton>
            )
          ) : (
            <span />
          )}
          <AdminButton type="button" variant="secondary" size="sm" onClick={onClose}>
            {t("experts.memory.close")}
          </AdminButton>
        </div>
      </div>
    </div>
  )
}
