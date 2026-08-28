import { BolagShell } from "@/components/layout/BolagShell"
import { PersonaComposerPage } from "@/pages/PersonaComposerPage"
import { BOLAG_DEMO_CUSTOMER_ID } from "@/lib/scoping"

export function ExpertComposerPage() {
  return (
    <PersonaComposerPage
      kind="expert"
      basePath="/bolag/experter"
      Shell={BolagShell}
      customerId={BOLAG_DEMO_CUSTOMER_ID}
    />
  )
}
