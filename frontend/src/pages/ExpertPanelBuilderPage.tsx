import { BolagShell } from "@/components/layout/BolagShell"
import { PopulationBuilderPage } from "@/pages/PopulationBuilderPage"
import { BOLAG_DEMO_CUSTOMER_ID } from "@/lib/scoping"

export function ExpertPanelBuilderPage() {
  return (
    <PopulationBuilderPage
      kind="expert_panel"
      Shell={BolagShell}
      basePath="/bolag/expertpaneler"
      customerId={BOLAG_DEMO_CUSTOMER_ID}
    />
  )
}
