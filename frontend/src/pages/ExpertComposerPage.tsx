import { useAuth } from "@/auth/AuthProvider"
import { NestedBolagPage } from "@/components/layout/BolagShell"
import { customerIdForExpertWrite } from "@/lib/scoping"
import { PersonaComposerPage } from "@/pages/PersonaComposerPage"

export function ExpertComposerPage() {
  const { user } = useAuth()
  return (
    <PersonaComposerPage
      kind="expert"
      basePath="/bolag/experter"
      Shell={NestedBolagPage}
      customerId={customerIdForExpertWrite(user?.kundId)}
    />
  )
}
