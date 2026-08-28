import { Outlet } from "react-router-dom"
import { AdminShell, type ShellNavItem } from "@/components/layout/AdminShell"

const BOLAG_NAV_ITEMS: ShellNavItem[] = [
  { key: "bolag.nav.experter", to: "/bolag/experter", match: "/bolag/experter" },
  { key: "bolag.nav.campaigns", to: "/bolag/campaigns", match: "/bolag/campaigns" },
]

type BolagShellProps = {
  children?: React.ReactNode
}

export function BolagShell({ children }: BolagShellProps) {
  return (
    <AdminShell
      navItems={BOLAG_NAV_ITEMS}
      brandTo="/bolag"
      navAriaLabelKey="bolag.nav.ariaMain"
      mobileMenuTitleKey="bolag.product"
      showTools={false}
      jobToasts
      menuId="bolag-main-menu"
    >
      {children ?? <Outlet />}
    </AdminShell>
  )
}
