import { useState } from "react"
import { useAuth } from "@/auth/AuthProvider"
import { expertWriteFromCandidate } from "@/components/experts/expertCandidate"
import { SuggestExpertsModal } from "@/components/experts/SuggestExpertsModal"
import { AdminButton } from "@/components/ui/admin-button"
import { addPopulationMember, deletePopulation } from "@/api/populations"
import { createPersona, type ExpertCandidate } from "@/api/personas"
import { personaInitials } from "@/data/library"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { customerIdForExpertWrite } from "@/lib/scoping"

export function ExpertPanelActions({
  panelId,
  customerId,
  onChanged,
  onDeleted,
  onToast,
}: {
  panelId: number
  customerId?: number
  onChanged: () => void
  onDeleted: () => void
  onToast: (message: string) => void
}) {
  const { t } = useLocale()
  const { user } = useAuth()
  const [suggestOpen, setSuggestOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const ownerId = customerId ?? customerIdForExpertWrite(user?.kundId)

  async function addGenerated(candidates: ExpertCandidate[]) {
    for (const candidate of candidates) {
      const created = await createPersona(expertWriteFromCandidate(candidate, ownerId))
      await addPopulationMember(panelId, {
        persona_id: created.id,
        name: created.name,
        initials: created.profile.initials || personaInitials(created.name),
        age: created.age ?? 0,
        occ: created.occ,
        district: created.district,
        trait: created.quote,
      })
    }
    onChanged()
    onToast(t("expertPanels.detail.generated", { count: candidates.length }))
  }

  async function removePanel() {
    try {
      await deletePopulation(panelId)
      onToast(t("expertPanels.list.deleted"))
      onDeleted()
    } catch (err: unknown) {
      onToast(err instanceof ApiError ? err.message : t("common.deleteError"))
      setConfirming(false)
    }
  }

  return (
    <>
      <AdminButton variant="secondary" size="sm" onClick={() => setSuggestOpen(true)}>
        {t("expertPanels.detail.generateExpert")}
      </AdminButton>
      {confirming ? (
        <>
          <AdminButton variant="secondary" size="sm" onClick={() => setConfirming(false)}>
            {t("common.cancel")}
          </AdminButton>
          <AdminButton variant="accent" size="sm" onClick={() => void removePanel()}>
            {t("common.deleteConfirm")}
          </AdminButton>
        </>
      ) : (
        <AdminButton variant="secondary" size="sm" onClick={() => setConfirming(true)}>
          {t("expertPanels.detail.deletePanel")}
        </AdminButton>
      )}
      <SuggestExpertsModal
        open={suggestOpen}
        onOpenChange={setSuggestOpen}
        onConfirm={addGenerated}
      />
    </>
  )
}
