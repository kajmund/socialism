import { UsersRound } from "lucide-react"
import { useState } from "react"
import { useLocale } from "@/i18n"
import { SmeExpertPanelsModal } from "@/products/sme/SmeExpertPanelsModal"

export function SmeExpertPanelsButton({
  editPanelId = null,
  onEditClosed,
  onClosed,
  onStarted,
}: {
  editPanelId?: number | null
  onEditClosed?: () => void
  onClosed?: () => void
  onStarted?: (panelId: number) => void
}) {
  const { t } = useLocale()
  const [listOpen, setListOpen] = useState(false)
  const open = listOpen || editPanelId != null

  function close() {
    setListOpen(false)
    onEditClosed?.()
    onClosed?.()
  }

  function started(panelId: number) {
    setListOpen(false)
    onEditClosed?.()
    onStarted?.(panelId)
  }

  return (
    <>
      <button
        type="button"
        className="grid size-9 place-items-center rounded-full text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        aria-label={t("sme.expertPanelsAria")}
        title={t("sme.expertPanelsTitle")}
        onClick={() => {
          onEditClosed?.()
          setListOpen(true)
        }}
      >
        <UsersRound size={18} aria-hidden="true" />
      </button>
      <SmeExpertPanelsModal
        open={open}
        panelId={listOpen ? null : editPanelId}
        onClose={close}
        onStarted={started}
      />
    </>
  )
}
