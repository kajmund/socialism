import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react"
import { MessageCircle } from "lucide-react"
import { useAuth } from "@/auth/AuthProvider"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale } from "@/i18n"

const PersonaComposerPage = lazy(async () => {
  const module = await import("@/pages/PersonaComposerPage")
  return { default: module.PersonaComposerPage }
})

function InterviewShell({ children }: { children: ReactNode }) {
  return <div className="theme-admin flex min-h-0 flex-1 flex-col overflow-hidden bg-db-ink-0">{children}</div>
}

export function SmeExpertInterviewButton({ expertId, expertName, workspaceKind, customerId, beforeOpen, onSaved }: {
  expertId: string
  expertName: string
  workspaceKind: "company" | "client"
  customerId?: number
  beforeOpen: () => Promise<void>
  onSaved?: () => void
}) {
  const { user, loading } = useAuth()
  const { t } = useLocale()
  const companyId = customerId ?? user?.kundId
  const identity = `${workspaceKind}:${companyId}:${expertId}`
  const latest = useRef(identity)
  latest.current = identity
  const [openedFor, setOpenedFor] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    setOpenedFor(null)
    setError(false)
  }, [identity])

  async function open() {
    setBusy(true)
    setError(false)
    try {
      await beforeOpen()
      if (latest.current === identity) setOpenedFor(identity)
    } catch {
      if (latest.current === identity) setError(true)
    } finally {
      setBusy(false)
    }
  }

  if (workspaceKind !== "company") return null

  return <>
    <AdminButton variant="secondary" size="sm" disabled={loading || busy || companyId == null || !expertId} aria-label={t("sme.companyInterviewAria", { name: expertName })} title={t("sme.companyInterview")} onClick={() => { void open() }}>
      <MessageCircle size={16} aria-hidden="true" />
      <span className="hidden sm:inline">{t("personas.composer.interviewTab")}</span>
    </AdminButton>
    {error ? <span role="alert" className="text-xs text-destructive">{t("sme.companyInterviewError")}</span> : null}
    <Dialog open={openedFor === identity} onOpenChange={(next) => { if (!next) setOpenedFor(null) }}>
      <DialogContent showCloseButton={false} style={{ minHeight: 0 }} className="theme-admin flex h-[min(90dvh,800px)] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
        <DialogHeader className="flex-row items-start border-b px-4 py-3">
          <div className="min-w-0 flex-1"><DialogTitle>{t("sme.companyInterview")} · {expertName}</DialogTitle><DialogDescription className="mt-1">{t("sme.companyInterviewIntro")}</DialogDescription></div>
          <DialogClose render={<AdminButton variant="secondary" size="sm" aria-label={t("common.close")}>{t("common.close")}</AdminButton>}>{t("common.close")}</DialogClose>
        </DialogHeader>
        {openedFor === identity && companyId != null ? <Suspense fallback={<p role="status" className="p-4 text-sm text-muted-foreground">{t("sme.loading")}</p>}>
          <PersonaComposerPage key={identity} kind="expert" personaId={expertId} customerId={companyId} embedded embeddedInterview workspaceChatEnabled={false} Shell={InterviewShell} onSaved={() => onSaved?.()} />
        </Suspense> : null}
      </DialogContent>
    </Dialog>
  </>
}
