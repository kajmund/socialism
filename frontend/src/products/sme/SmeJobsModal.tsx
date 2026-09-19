import { Briefcase, X } from "lucide-react"
import { useEffect } from "react"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { JobsPage } from "@/pages/JobsPage"
import { SmeEmbedPanelShell } from "@/products/sme/SmeEmbedPanelShell"

export function SmeJobsModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const { t } = useLocale()

  useEffect(() => {
    if (!open) return
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", closeOnEscape)
    return () => window.removeEventListener("keydown", closeOnEscape)
  }, [onClose, open])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/60 p-3 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sme-jobs-modal-title"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="flex h-[min(92vh,900px)] w-full max-w-5xl flex-col overflow-hidden rounded-[var(--radius-lg)] border border-white/15 bg-db-ink-0 shadow-2xl">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-[color:var(--border-hairline)] bg-db-ink-950 px-4 text-db-ink-0">
          <Briefcase size={18} className="text-db-gold-500" aria-hidden="true" />
          <h2 id="sme-jobs-modal-title" className="text-sm font-medium">
            {t("sme.jobs")}
          </h2>
          <AdminButton
            variant="accent"
            size="sm"
            className="ml-auto gap-1.5"
            onClick={onClose}
          >
            <X size={15} aria-hidden="true" />
            {t("sme.closeJobs")}
          </AdminButton>
        </header>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <JobsPage embedded Shell={SmeEmbedPanelShell} />
        </div>
      </div>
    </div>
  )
}
