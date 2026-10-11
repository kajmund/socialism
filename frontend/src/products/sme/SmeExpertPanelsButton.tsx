import { UsersRound } from "lucide-react"
import { useState } from "react"
import { useLocale } from "@/i18n"
import { SmeExpertPanelsModal } from "@/products/sme/SmeExpertPanelsModal"

export function SmeExpertPanelsButton({
  onClosed,
  onStarted,
}: {
  onClosed?: () => void
  onStarted?: (panelId: number) => void
}) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)

  function close() {
    setOpen(false)
    onClosed?.()
  }

  function started(panelId: number) {
    setOpen(false)
    onStarted?.(panelId)
  }

  return (
    <>
      <button
        type="button"
        className="grid size-9 place-items-center rounded-full text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        aria-label={t("sme.expertPanelsAria")}
        title={t("sme.expertPanelsTitle")}
        onClick={() => setOpen(true)}
      >
        <UsersRound size={18} aria-hidden="true" />
      </button>
      <SmeExpertPanelsModal open={open} onClose={close} onStarted={started} />
    </>
  )
}
