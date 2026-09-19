import { UserRound, X } from "lucide-react"
import { useEffect, type ReactNode } from "react"
import { useAuth } from "@/auth/AuthProvider"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { PersonaComposerPage } from "@/pages/PersonaComposerPage"

function SmeExpertEditorShell({ children }: { children: ReactNode }) {
  return (
    <div className="theme-admin flex min-h-0 flex-1 flex-col overflow-hidden bg-db-ink-0">
      {children}
    </div>
  )
}

export function SmeExpertEditorModal({
  open,
  expertId,
  expertName,
  onClose,
  onSaved,
}: {
  open: boolean
  expertId: string
  expertName: string
  onClose: () => void
  onSaved?: () => void
}) {
  const { t } = useLocale()
  const { loading, user } = useAuth()
  const kundId = user?.kundId

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
      aria-labelledby="sme-expert-editor-modal-title"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="flex h-[min(85vh,720px)] w-full max-w-xl flex-col overflow-hidden rounded-[var(--radius-lg)] border border-white/15 bg-db-ink-0 shadow-2xl">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-[color:var(--border-hairline)] bg-db-ink-950 px-4 text-db-ink-0">
          <UserRound size={18} className="text-db-gold-500" aria-hidden="true" />
          <h2
            id="sme-expert-editor-modal-title"
            className="min-w-0 truncate text-sm font-medium"
          >
            {expertName}
          </h2>
          <AdminButton
            variant="accent"
            size="sm"
            className="ml-auto gap-1.5"
            onClick={onClose}
          >
            <X size={15} aria-hidden="true" />
            {t("sme.closeExpertEditor")}
          </AdminButton>
        </header>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {loading ? (
            <p className="px-4 py-6 text-sm text-[color:var(--text-muted)]">
              {t("sme.loading")}
            </p>
          ) : kundId == null ? (
            <p className="px-4 py-6 text-sm text-[color:var(--text-muted)]">
              {t("sme.expertEditorMissingKund")}
            </p>
          ) : (
            <PersonaComposerPage
              key={expertId}
              kind="expert"
              personaId={expertId}
              customerId={kundId}
              embedded
              Shell={SmeExpertEditorShell}
              onSaved={() => onSaved?.()}
              onAvatarChange={() => onSaved?.()}
            />
          )}
        </div>
      </div>
    </div>
  )
}
