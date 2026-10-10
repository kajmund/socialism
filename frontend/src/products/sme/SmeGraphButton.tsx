import { Network } from "lucide-react"
import { useState } from "react"
import { useAuth } from "@/auth/AuthProvider"
import { useLocale } from "@/i18n"
import { SmeGraphModal } from "@/products/sme/SmeGraphModal"

export function SmeGraphButton() {
  const { t } = useLocale()
  const { isAdmin } = useAuth()
  const [open, setOpen] = useState(false)
  if (!isAdmin) return null

  return (
    <>
      <button
        type="button"
        className="grid size-9 place-items-center rounded-full text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        aria-label={t("sme.graphAria")}
        title={t("sme.graphTitle")}
        onClick={() => setOpen(true)}
      >
        <Network size={18} aria-hidden="true" />
      </button>
      <SmeGraphModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}
