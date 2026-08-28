import { BolagShell } from "@/components/layout/BolagShell"
import { PopulationDetailPage } from "@/pages/PopulationDetailPage"

export function ExpertPanelDetailPage() {
  return (
    <PopulationDetailPage
      Shell={BolagShell}
      basePath="/bolag/expertpaneler"
      expectedKind="expert_panel"
    />
  )
}
