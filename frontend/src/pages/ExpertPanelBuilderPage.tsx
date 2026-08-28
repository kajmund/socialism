import { NestedBolagPage } from "@/components/layout/BolagShell"
import { PopulationBuilderPage } from "@/pages/PopulationBuilderPage"

export function ExpertPanelBuilderPage() {
  return (
    <PopulationBuilderPage
      kind="expert_panel"
      Shell={NestedBolagPage}
      basePath="/bolag/expertpaneler"
    />
  )
}
