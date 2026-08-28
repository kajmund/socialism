import { NestedBolagPage } from "@/components/layout/BolagShell"
import { PopulationDetailPage } from "@/pages/PopulationDetailPage"

export function ExpertPanelDetailPage() {
  return (
    <PopulationDetailPage
      Shell={NestedBolagPage}
      basePath="/bolag/expertpaneler"
      expectedKind="expert_panel"
    />
  )
}
