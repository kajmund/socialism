import { Outlet } from "react-router-dom"
import { AdminShell } from "@/components/layout/AdminShell"

type BolagShellProps = {
  children?: React.ReactNode
}

/** Content wrapper for pages already rendered inside the /bolag layout route. */
export function NestedBolagPage({ children }: BolagShellProps) {
  return <>{children}</>
}

export function BolagShell({ children }: BolagShellProps) {
  return (
    <AdminShell
      brandTo="/bolag"
      navAriaLabelKey="bolag.nav.ariaMain"
      mobileMenuTitleKey="bolag.product"
      jobToasts
      customerScope="bolag"
      menuId="bolag-main-menu"
    >
      {children ?? <Outlet />}
    </AdminShell>
  )
}
