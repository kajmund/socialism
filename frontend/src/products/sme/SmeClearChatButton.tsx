import { useState } from "react"
import { Trash2 } from "lucide-react"
import { AdminButton } from "@/components/ui/admin-button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale } from "@/i18n"
import { workspaceErrorMessage } from "./workspaceChatLogic"

export function SmeClearChatButton({ name, disabled, onClear }: {
  name: string
  disabled: boolean
  onClear: () => Promise<void>
}) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function confirm() {
    setBusy(true)
    setError(null)
    try {
      await onClear()
      setOpen(false)
    } catch (caught) {
      setError(workspaceErrorMessage(caught, t, "sme.clearChatError"))
    } finally {
      setBusy(false)
    }
  }

  return <>
    <AdminButton variant="secondary" size="sm" className="size-8 px-0" disabled={disabled || busy} aria-label={t("sme.clearChatAria", { name })} title={t("sme.clearChat")} onClick={() => { setError(null); setOpen(true) }}>
      <Trash2 size={15} aria-hidden="true" />
    </AdminButton>
    <Dialog open={open} onOpenChange={(next) => { if (!busy) setOpen(next) }}>
      <DialogContent className="theme-admin max-w-md">
        <DialogHeader>
          <DialogTitle>{t("sme.clearChatTitle")}</DialogTitle>
          <DialogDescription>{t("sme.clearChatDescription")}</DialogDescription>
        </DialogHeader>
        {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
        <div className="flex justify-end gap-2">
          <AdminButton variant="secondary" size="sm" disabled={busy} onClick={() => setOpen(false)}>{t("common.cancel")}</AdminButton>
          <AdminButton size="sm" disabled={busy} onClick={() => { void confirm() }}>{busy ? t("sme.clearingChat") : t("sme.clearChatConfirm")}</AdminButton>
        </div>
      </DialogContent>
    </Dialog>
  </>
}
