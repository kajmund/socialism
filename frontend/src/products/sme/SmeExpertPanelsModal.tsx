import { UsersRound, X } from "lucide-react"
import { useEffect, useState, type ReactNode } from "react"
import { useAuth } from "@/auth/AuthProvider"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ExpertPanelsPage } from "@/pages/ExpertPanelsPage"
import { PopulationBuilderPage } from "@/pages/PopulationBuilderPage"
import { PopulationDetailPage } from "@/pages/PopulationDetailPage"
import { SmeExpertEditorModal } from "@/products/sme/SmeExpertEditorModal"

function EmbedShell({ children }: { children: ReactNode }) {
  return <>{children}</>
}

type PanelView = { kind: "list" } | { kind: "new" } | { kind: "panel"; id: number }

export function SmeExpertPanelsModal({
  open,
  onClose,
  onStarted,
}: {
  open: boolean
  onClose: () => void
  onStarted?: (panelId: number) => void
}) {
  const { t } = useLocale()
  const { user } = useAuth()
  const customerId = user?.kundId ?? undefined
  const [view, setView] = useState<PanelView>({ kind: "list" })
  const [expert, setExpert] = useState<{ id: string; name: string } | null>(null)

  useEffect(() => {
    if (!open) return
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape" || expert) return
      onClose()
    }
    window.addEventListener("keydown", closeOnEscape)
    return () => window.removeEventListener("keydown", closeOnEscape)
  }, [expert, onClose, open])

  useEffect(() => {
    if (open) return
    setView({ kind: "list" })
    setExpert(null)
  }, [open])

  if (!open) return null

  return (
    <>
      <div
        className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/60 p-3 sm:p-6"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sme-expert-panels-modal-title"
        onClick={(event) => {
          if (event.target === event.currentTarget) onClose()
        }}
      >
        <div className="flex h-[min(92vh,900px)] w-full max-w-5xl flex-col overflow-hidden rounded-[var(--radius-lg)] border border-white/15 bg-db-ink-0 shadow-2xl">
          <header className="flex h-14 shrink-0 items-center gap-2 border-b border-[color:var(--border-hairline)] bg-db-ink-950 px-4 text-db-ink-0">
            <UsersRound size={18} className="text-db-gold-500" aria-hidden="true" />
            <h2 id="sme-expert-panels-modal-title" className="text-sm font-medium">
              {t("sme.expertPanelsTitle")}
            </h2>
            {view.kind === "new" ? (
              <button
                type="button"
                className="ml-auto text-sm text-white/80 hover:text-white"
                onClick={() => setView({ kind: "list" })}
              >
                {t("expertPanels.detail.back")}
              </button>
            ) : null}
            <AdminButton
              variant="accent"
              size="sm"
              className={view.kind === "new" ? "gap-1.5" : "ml-auto gap-1.5"}
              onClick={onClose}
            >
              <X size={15} aria-hidden="true" />
              {t("sme.closeExpertPanels")}
            </AdminButton>
          </header>
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <div className="theme-admin admin-shell h-full min-h-0 w-full">
              <div className="admin-main-scroll">
                {view.kind === "list" ? (
                  <ExpertPanelsPage
                    customerId={customerId}
                    onOpen={(id) => setView({ kind: "panel", id })}
                    onCreate={() => setView({ kind: "new" })}
                    onChat={onStarted}
                  />
                ) : null}
                {view.kind === "new" ? (
                  <PopulationBuilderPage
                    kind="expert_panel"
                    Shell={EmbedShell}
                    basePath="/bolag/expertpaneler"
                    customerId={customerId}
                    onCreated={(id) => onStarted?.(id)}
                  />
                ) : null}
                {view.kind === "panel" ? (
                  <PopulationDetailPage
                    Shell={EmbedShell}
                    basePath="/bolag/expertpaneler"
                    expectedKind="expert_panel"
                    populationId={view.id}
                    customerId={customerId}
                    onBack={() => setView({ kind: "list" })}
                    onDuplicated={(id) => setView({ kind: "panel", id })}
                    onOpenExpert={(id, name) => setExpert({ id, name })}
                  />
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>
      <SmeExpertEditorModal
        open={expert != null}
        expertId={expert?.id ?? ""}
        expertName={expert?.name ?? ""}
        onClose={() => setExpert(null)}
      />
    </>
  )
}
